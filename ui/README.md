# Loop 0 UI — local upload + history

A thin local web app over the same `analyze.py` engine the CLI uses. Drag in a
clip, set focus/subject/window, get the structured coaching report rendered
nicely — and every run is saved to a local SQLite history.

It's not just convenience: the accumulating history **is** the corpus we'll
later eval against (promptfoo) and the labeled data that seeds a local model
(Loop 3). The fun path and the rigorous path are the same path.

## Run it

From the repo root, with the venv active and deps installed (see the top-level
README — use `uv`):

```bash
uvicorn ui.app:app --reload
# open http://localhost:8000
```

Needs `ANTHROPIC_API_KEY` (export it or put it in a `.env`) and `ffmpeg` on PATH.

## What it does

- **Upload** a clip and choose `focus`, optional `subject` (for doubles), and the
  sampling window (`start` / `duration` / `interval` / `max frames`) — the same
  knobs as the CLI.
- **Analyze** runs Claude on the sampled frames (~20–60s) and stores the report.
- **History** lists every run with its confidence; click through to the full
  report (subject analyzed, footage quality, per-aspect observations with rating
  badges, drills) alongside the playable clip.

## Watch a folder (Dropbox auto-processing)

Point the app at a local folder and it will auto-analyze any clip that lands
there — process it, add it to history, move it to a `processed/` (or `failed/`)
subfolder, and email you the result.

**About Dropbox:** watch the local folder your Dropbox *desktop app* syncs into.
Once synced, the file is a real local file — no Dropbox API or credentials
needed. Two things to know:
- The watcher waits until the file's size stops changing before processing, so
  it won't grab a half-synced download.
- Set that folder to **"Make available offline"** in Dropbox so files aren't
  online-only placeholders.

(If you have no desktop app and want to watch Dropbox *cloud* directly, that's a
different build using the Dropbox API — ask and we'll add it.)

Configure in `.env` (see `.env.example`), then restart:

```bash
WATCH_DIR=/Users/you/Dropbox/pickleball-incoming   # absolute path
WATCH_FOCUS=serve                                  # how to analyze dropped clips
# WATCH_SUBJECT=player in the white shirt, near side

# email results (optional):
RESEND_API_KEY=re_...
NOTIFY_EMAIL=you@example.com
# RESEND_FROM=onboarding@resend.dev   # test sender; verified domain for real sends
```

When enabled, the home page shows a "👀 Watching …" banner, and watched runs are
tagged `watch` in the history Source column. Dropped clips are analyzed across
the whole clip (no start/duration trim) — for precise contact analysis on a
specific rep, use the upload form with a tight window.

## Storage

Everything is local and gitignored:

- `ui/data/uploads/` — your clips.
- `ui/data/coach.db` — SQLite history (one row per run, full JSON report).

Nothing leaves your machine except the sampled frames sent to the Claude API for
analysis.

## Notes / next

- Analysis runs synchronously inside the request — fine for a single-user local
  tool. If runs start feeling slow to sit through, the obvious next step is a
  background job + a "processing" state in the history list.
- This is still Loop 0 (Claude as the oracle). When Loop 1's local pose/ball
  metrics land, they slot in next to the Claude read in the same report view.
