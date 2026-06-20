#!/usr/bin/env python3
"""Loop 0 — the signal check.

Sample frames from a pickleball practice clip and ask Claude's vision model for
structured coaching feedback. This exists to answer one question as cheaply as
possible: is there extractable coaching signal in ordinary practice video?

No training, no hardware. Drop in a phone clip, read the report next to the
video, and judge whether a real coach would agree. That judgement is the
"measure" step of the loop.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python analyze.py serves.mp4 --focus serve
    python analyze.py rally.mp4 --focus return --interval 0.5 --max-frames 16

Requires `ffmpeg` on PATH for frame extraction.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import anthropic

# Opus 4.8 is the most capable vision model; for the signal check we want the
# strongest possible read so a weak result reflects the footage, not the model.
MODEL = "claude-opus-4-8"

# What a coach actually watches for, per practice focus. Kept short and concrete
# so the probe stays honest — these are things obvious to anyone who coaches.
FOCUS_GUIDES = {
    "serve": (
        "Legal serve mechanics (contact below the waist, upward arc, paddle "
        "below wrist), contact height, depth and placement, consistency of "
        "toss/drop and swing path, body rotation."
    ),
    "return": (
        "Return depth (deep returns push opponents back), net clearance, "
        "split-step timing, ready position and paddle-up between shots, "
        "recovery to center after the shot."
    ),
    "dink": (
        "Contact height relative to the net (low, controlled), soft hands, "
        "arc and landing in the kitchen, patience vs. attacking too early, "
        "knee bend and posture."
    ),
    "drive": (
        "Kinetic chain and body rotation, contact point out in front, paddle "
        "face control, follow-through, footwork into the shot."
    ),
    "general": (
        "Overall form, footwork and balance, ready position, contact height, "
        "shot selection, and anything a coach would flag on first watch."
    ),
}

# Schema for the coaching report. Kept simple to stay within structured-output
# constraints (no min/max, additionalProperties:false on every object).
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_analyzed": {
            "type": "string",
            "description": (
                "Which player on court this feedback is about (e.g. 'player in "
                "the white shirt, near side'). If you had to guess because no "
                "subject was specified, say so. If you lost track of them or "
                "they changed between frames, flag it here."
            ),
        },
        "footage_quality": {
            "type": "object",
            "properties": {
                "usable": {"type": "boolean"},
                "notes": {
                    "type": "string",
                    "description": "Angle/lighting/framerate issues that limit analysis.",
                },
            },
            "required": ["usable", "notes"],
            "additionalProperties": False,
        },
        "observations": {
            "type": "array",
            "description": "Concrete, coach-style observations grounded in what is visible.",
            "items": {
                "type": "object",
                "properties": {
                    "aspect": {
                        "type": "string",
                        "description": "e.g. 'contact height', 'net clearance', 'ready position'.",
                    },
                    "assessment": {"type": "string"},
                    "rating": {
                        "type": "string",
                        "enum": ["good", "okay", "needs_work", "cant_tell"],
                    },
                },
                "required": ["aspect", "assessment", "rating"],
                "additionalProperties": False,
            },
        },
        "top_drills": {
            "type": "array",
            "description": "One to three drills or cues to improve the biggest issues.",
            "items": {"type": "string"},
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "How much the feedback can be trusted given footage quality.",
        },
    },
    "required": ["subject_analyzed", "footage_quality", "observations", "top_drills", "confidence"],
    "additionalProperties": False,
}


def extract_frames(
    video: Path,
    interval: float,
    max_frames: int,
    out_dir: Path,
    start: float | None = None,
    duration: float | None = None,
) -> list[Path]:
    """Pull one frame every `interval` seconds, capped at `max_frames`.

    `start`/`duration` trim to the window that actually contains the action —
    crucial because spreading a handful of frames across a long clip skips the
    fast moments (like the serve contact) entirely.
    """
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH — install it (e.g. `brew install ffmpeg`).")

    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%04d.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]          # before -i: fast seek to the window
    cmd += ["-i", str(video)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    # fps=1/interval samples evenly; -qscale keeps JPEGs small but readable.
    cmd += ["-vf", f"fps=1/{interval}", "-qscale:v", "3", pattern]
    subprocess.run(cmd, check=True)
    frames = sorted(out_dir.glob("frame_*.jpg"))
    if not frames:
        sys.exit("No frames extracted — is the video readable?")
    return frames[:max_frames]


def build_content(frames: list[Path], focus: str, subject: str | None,
                  note: str | None = None) -> list[dict]:
    """Interleave labeled frames into a single vision message."""
    if subject:
        who = (
            f"Focus your analysis ONLY on: {subject}. Track this same person "
            "across all the frames; ignore the other players on court except as "
            "context. If you can't confidently find them in a frame, skip it."
        )
    else:
        who = (
            "There may be several people on court. Pick the one who is actively "
            f"practicing their {focus} (usually the most involved in the action) "
            "and analyze only that person, consistently, across all frames."
        )
    label = ""
    if note:
        label = (
            f' The player labeled this clip "{note}" — treat that as their own '
            "description of what they're practicing and tailor your feedback to "
            "it, but only report what you can actually see in the frames."
        )
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Here are {len(frames)} frames sampled in order from a pickleball "
                f"practice clip. The player is working on their {focus}.{label} {who} "
                "Analyze what you can actually see across the sequence."
            ),
        }
    ]
    for i, frame in enumerate(frames, 1):
        data = base64.standard_b64encode(frame.read_bytes()).decode("utf-8")
        content.append({"type": "text", "text": f"Frame {i}:"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
            }
        )
    return content


def analyze(frames: list[Path], focus: str, subject: str | None,
            note: str | None = None) -> dict:
    client = anthropic.Anthropic()
    guide = FOCUS_GUIDES.get(focus, FOCUS_GUIDES["general"])

    system = (
        "You are an experienced pickleball coach reviewing a player's practice "
        "footage. Give honest, concrete, encouraging feedback grounded only in "
        "what is visible in the frames. If the footage is too low-quality, the "
        "angle is wrong, or you genuinely cannot tell, say so plainly and rate "
        "those aspects 'cant_tell' — do not invent detail. Stay locked on the "
        "one player you're asked to analyze; don't blend in other people on "
        "court. "
        f"For this {focus} session, pay attention to: {guide}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": build_content(frames, focus, subject, note)}],
        output_config={"format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Loop 0: Claude-vision pickleball coaching probe.")
    parser.add_argument("video", type=Path, help="Path to a practice video clip.")
    parser.add_argument(
        "--focus",
        default="general",
        choices=sorted(FOCUS_GUIDES),
        help="What the player is practicing (default: general).",
    )
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between sampled frames (denser catches fast moments like contact).")
    parser.add_argument("--max-frames", type=int, default=16, help="Max frames to send.")
    parser.add_argument("--start", type=float, help="Trim: seconds into the clip to start sampling.")
    parser.add_argument("--duration", type=float, help="Trim: seconds of clip to sample from --start.")
    parser.add_argument("--subject", help="Who to analyze in plain language, e.g. 'player in the white shirt, near side'. Important for doubles footage.")
    parser.add_argument("--note", help="What you're working on, in your words, e.g. 'backhand drop to kitchen'. Given to the coach as context.")
    parser.add_argument("--out", type=Path, help="Write the JSON report here too.")
    args = parser.parse_args()

    # Load ANTHROPIC_API_KEY from a .env if present; real env vars still win.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if not args.video.exists():
        sys.exit(f"Video not found: {args.video}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY (export it or put it in a .env file).")

    with tempfile.TemporaryDirectory() as tmp:
        frames = extract_frames(
            args.video, args.interval, args.max_frames, Path(tmp) / "frames",
            start=args.start, duration=args.duration,
        )
        print(f"Sampled {len(frames)} frames; asking {MODEL} for a read...", file=sys.stderr)
        report = analyze(frames, args.focus, args.subject, args.note)

    out = json.dumps(report, indent=2)
    print(out)
    if args.out:
        args.out.write_text(out)
        print(f"\nSaved report to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
