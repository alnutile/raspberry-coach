# raspberry-coach

A DIY, open-source pickleball coach. Record a practice session on a cheap
battery-powered device (Raspberry Pi or an r1-class all-in-one with a camera),
then analyze the footage for classic coaching feedback: contact height, net
clearance, return depth, ready position, footwork, form. Analysis runs
wherever you want it — locally on a Mac, on a server, or through the Claude API.

![](images/respberry-coach.gif)

> No paid service, no lock-in. The device just captures; the brains are swappable.

## Get started in 2 minutes

You need three things: [`uv`](https://docs.astral.sh/uv/), `ffmpeg`, and an
[Anthropic API key](https://console.anthropic.com).

```bash
# macOS (Linux: see uv's install page)
brew install uv ffmpeg

git clone https://github.com/alnutile/raspberry-coach.git
cd raspberry-coach
./run.sh          # first run creates a .env — paste your key into it, then run again
```

`./run.sh` sets up a self-contained Python env, installs everything, and starts
the app at **http://localhost:8000**. Upload a practice clip, pick what you're
working on, and read the coaching report. That's it.

> **Why a script and not a downloadable app?** While this is moving fast, a
> one-command script keeps onboarding simple *and* lets you pull updates with a
> `git pull`. A packaged/double-click release makes sense later, once things
> settle — see [Roadmap](#status).

Prefer the command line, or want to script it? See
[`experiments/loop0_claude_vision/`](experiments/loop0_claude_vision/) for the
CLI, and [`ui/`](ui/) for UI details.

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

- [x] Loop 0 — Claude-vision coaching probe, CLI (`experiments/loop0_claude_vision/`)
- [x] Loop 0 — run on real footage (signal confirmed; capture angle is the limiter)
- [x] Local web UI — upload, render reports, SQLite history (`ui/`)
- [ ] Evals — promptfoo regression guard once there's a corpus of runs
- [ ] Loop 1 — local pose + ball-tracking metrics
- [ ] Loop 2 — hardware capture rig
- [ ] Loop 3 — distilled local model
- [ ] Packaged release — a double-click app once the tool stabilizes
      (premature while iterating; the `./run.sh` + `git pull` flow wins for now)

## Manual setup (under the hood / CLI)

`./run.sh` above does all of this for you. Here's what it's doing, for when you
want to run the CLI directly or debug the environment.

Use [`uv`](https://docs.astral.sh/uv/). It downloads a self-contained Python
that bundles its own libraries — which dodges a nasty Homebrew bug where the
bundled `pyexpat` is linked against the wrong system `libexpat` and crashes
`pip` itself (`Symbol not found: _XML_SetAlloc...`). Don't use Homebrew's
`python@3.x` for this; even a fresh install hits it.

```bash
# 1. uv (one-time)
brew install uv                    # or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Self-contained env + deps (needs ffmpeg on PATH: `brew install ffmpeg`)
uv venv --python 3.12              # standalone 3.12, no system-library mess
source .venv/bin/activate
uv pip install -r requirements.txt

# 3. API key — copy the example and fill it in
cp .env.example .env               # then edit .env, or: export ANTHROPIC_API_KEY=sk-ant-...

# 4a. Run the CLI probe
python experiments/loop0_claude_vision/analyze.py path/to/serves.mp4 --focus serve

# 4b. ...or launch the web UI (what ./run.sh starts)
uvicorn ui.app:app --reload        # then open http://localhost:8000
```

3.12 is deliberate — Loop 1's CV libraries (MediaPipe, etc.) don't ship 3.14
wheels yet. The script auto-loads `.env`, so once it's filled in you don't need
to export anything. You get a JSON coaching report — read it next to the video
and ask the only question that matters at this stage: *would a coach agree?*

### If you'd rather not use uv

A Homebrew-Python venv works *only* if its `pyexpat` is healthy. Check first:

```bash
python3.12 -c "import pyexpat, ssl; print('stdlib ok')"
```

- Prints `stdlib ok` → `python3.12 -m venv .venv && source .venv/bin/activate &&
  pip install -r requirements.txt`.
- Throws `Symbol not found: _XML_SetAlloc...` → the Homebrew bottle is broken;
  a venv or reinstall won't fix it. Use `uv` above (or a python.org installer).


```
python experiments/loop0_claude_vision/analyze.py videos/wall.mp4 --focus general \
  --subject "me hitting the wall" --start 8 --duration 4 --interval 0.25
```

```
python experiments/loop0_claude_vision/analyze.py videos/wall.mp4 --focus general \
  --subject "me hitting the wall" --interval 0.25
```