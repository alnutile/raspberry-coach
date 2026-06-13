# raspberry-coach

A DIY, open-source pickleball coach. Record a practice session on a cheap
battery-powered device (Raspberry Pi or an r1-class all-in-one with a camera),
then analyze the footage for classic coaching feedback: contact height, net
clearance, return depth, ready position, footwork, form. Analysis runs
wherever you want it — locally on a Mac, on a server, or through the Claude API.

No paid service, no lock-in. The device just captures; the brains are swappable.

## The strategy: validate the brain before the body

The hardware (Pi + camera + battery + sync-home) is well-trodden and low-risk.
The risky, unproven assumption is the one worth testing first:

> **Can ordinary practice video be turned into coaching feedback that a real
> pickleball coach would agree with?**

If the answer is yes, everything downstream is engineering. If it's no, no
amount of nice hardware saves it. So we test that assumption as cheaply as
possible, before soldering anything.

### Build–measure–learn loops

**Loop 0 — Signal check (start here).** One phone video of you practicing
serves. Sample frames, send them to Claude's vision model with a coaching
prompt, get back structured feedback. Hours of work, no training, no hardware.
The question it answers: *is there extractable coaching signal in this footage
at all?* Claude here is the **oracle** — the fastest way to find out whether the
problem is even solvable, and later the thing that labels data for a local
model. → `experiments/loop0_claude_vision/`

**Loop 1 — Quantified metrics.** Add a local CV pipeline: pose estimation
(MediaPipe / MoveNet) + ball tracking to compute hard numbers — contact height,
net clearance, return depth, recovery to center. Compare against Loop 0's read.
Question: *can we get on-device-capable, quantitative metrics that agree with
the coach/Claude?* This is the real product engine and the free/offline path.

**Loop 2 — Hardware.** Put capture on the Pi / r1, run it off a battery,
record a real session, sync home (Wi-Fi / Tailscale / SD card). Question: *does
the capture rig produce footage good enough for Loop 1's pipeline?* (angle,
framerate, resolution, lighting). Note this is where hardware **finally**
enters — and only to feed the already-proven pipeline.

**Loop 3 — Distill & productize.** Use Claude-labeled clips to train a small
local model that runs cheaply on a Mac (or the device). This is the
"buy my trained model" endgame — Claude generates the labels, you distill them
into something fast and offline.

### Local vs. Claude: it's not either/or

- **Claude API** = the oracle and the premium path. Cheapest way to probe "is
  this possible," and the highest-quality analysis with zero training. Also the
  label generator that bootstraps the local model.
- **Local CV / trained model** = the free, offline, "works on your Mac the
  moment you get home" path.

The device captures; analysis is a swappable backend. Gen-1 Pi / r1 hardware
won't run heavy models well, so keep inference off the device for now.

## Status

- [x] Loop 0 scaffold — Claude-vision coaching probe (`experiments/loop0_claude_vision/`)
- [ ] Loop 0 run on real footage
- [ ] Loop 1 — local pose + ball-tracking metrics
- [ ] Loop 2 — hardware capture rig
- [ ] Loop 3 — distilled local model

## Quick start (Loop 0)

Use Python 3.12 in a virtualenv. **Avoid Python 3.14** — it's too new for the
CV libraries Loop 1 needs, and some Homebrew 3.14 builds ship a broken `pyexpat`
that breaks `pip` itself.

```bash
# 1. Working interpreter (skip if `python3.12` already runs)
brew install python@3.12          # macOS

# 2. Isolated env
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Dependencies (needs ffmpeg on PATH too: `brew install ffmpeg`)
pip install -r requirements.txt

# 4. API key — copy the example and fill it in
cp .env.example .env               # then edit .env, or: export ANTHROPIC_API_KEY=sk-ant-...

# 5. Run the probe
python experiments/loop0_claude_vision/analyze.py path/to/serves.mp4 --focus serve
```

The script auto-loads `.env`, so once it's filled in you don't need to export
anything. You get a JSON coaching report — read it next to the video and ask the
only question that matters at this stage: *would a coach agree?*

> **If `pip` itself crashes** with `Symbol not found: _XML_SetAlloc...` /
> `pyexpat`, your base Python (usually Homebrew 3.14) is broken against the
> system `libexpat`. A venv won't fix it — it reuses the same broken
> interpreter. Install 3.12 as above and build the venv from that.
