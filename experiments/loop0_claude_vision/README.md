# Loop 0 — Claude-vision signal check

The cheapest possible test of the whole project's core assumption: **does
ordinary practice video contain coaching signal a real coach would agree with?**

No training, no hardware, no labeling. Sample frames from a clip, send them to
Claude's vision model with a coaching prompt, get a structured report back.

## Run it

```bash
python -m pip install -r ../../requirements.txt   # + ffmpeg on PATH
export ANTHROPIC_API_KEY=sk-ant-...
python analyze.py path/to/serves.mp4 --focus serve
```

Options:

- `--focus {serve,return,dink,drive,general}` — what the player is practicing.
- `--interval 0.5` — seconds between sampled frames (denser = more detail, more cost).
- `--max-frames 16` — cap on frames sent in one request.
- `--out report.json` — also write the report to a file.

## How to read the result

This is the **measure** step. Watch the clip yourself (or with a coach) and
compare against the report. Three outcomes:

1. **Feedback is genuinely useful** → the core assumption holds. Move to Loop 1
   (local quantified metrics) and start thinking about hardware.
2. **Feedback is plausible but vague** → try a tighter camera angle, a denser
   `--interval`, or a more specific `--focus`. The signal may be there but the
   capture is the bottleneck — which is itself a useful finding for Loop 2.
3. **Feedback is wrong or hallucinated** → look at `footage_quality` and
   `confidence`. Usually the angle or resolution is the problem, not the idea.

## Why frames, not video

Sampling stills is the fastest, cheapest probe and keeps token cost predictable.
It deliberately throws away motion/timing information — if still frames already
give useful feedback, full video or pose-tracking (Loop 1) will give more. If
stills give nothing, that's a strong early signal to fix capture before
investing in the pipeline.

## Next

Once this tells you the signal is real, Loop 1 swaps the "oracle" read for a
local pose + ball-tracking pipeline that produces hard numbers (contact height,
net clearance, return depth) — the on-device-capable, offline path. Claude's
reads here also double as labels to bootstrap that pipeline later.
