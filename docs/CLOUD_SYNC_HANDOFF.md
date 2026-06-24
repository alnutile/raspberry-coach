# Handoff: pbcoach cloud sync + frontend

> Paste this whole file into a new session (along with your Supabase URL, anon
> key, and any schema you already have) to continue. It is written to be read
> cold — no prior conversation context required.

## What this project is

**raspberry-coach** (repo: `alnutile/raspberry-coach`) is a DIY, open-source
pickleball coach. It samples frames from a practice video, sends them to Claude's
vision model, and returns a structured coaching report (per-aspect ratings,
drills, confidence, an honesty check). It runs **locally** on the user's machine
as a small FastAPI web app + a folder watcher, with a SQLite history. Strategy:
validate the analysis ("brain") before any hardware ("body"); Claude is the
oracle now and the label-generator for a future local model.

**Goal of this next phase:** a hosted frontend (separate repo
`alnutile/pbcoach-frontend`, Vite + Supabase) where users sign up, get a device
token, paste it into their local app, and then see their coaching results in the
cloud and trigger re-runs — pushed live. Auth is Supabase. Chat-with-the-coach
comes later.

## Architecture decisions (locked in)

1. **The local app is behind NAT — it cannot accept inbound connections.** So the
   cloud never pushes to it. Instead **the local app connects *outbound* to
   Supabase and subscribes to its own rows** (Supabase Realtime = a websocket the
   local app dials out). A periodic poll is the safety net for events missed
   during sleep/reconnect. Local pulls/subscribes outbound; cloud never initiates.

2. **Privacy principle (core, not optional):** the **video stays on the user's
   machine.** Only **metadata + one thumbnail frame + the report JSON** sync to
   Supabase. Real footage never leaves home unless the user explicitly uploads
   it. This is both a privacy promise and a selling point for the paid tier.

3. **Device auth — do NOT put the Supabase `service_role` key on user machines.**
   Instead:
   - Frontend user signs up (Supabase Auth) and generates a **per-device token**
     (stored hashed in a `devices` table).
   - User pastes the token into the local app's `.env` as `PBCOACH_DEVICE_TOKEN`
     (mirrors how `WATCH_DIR` / `RESEND_*` already work — see Conventions).
   - A Supabase **edge function** exchanges that device token for a short-lived
     scoped JWT; **Row-Level Security** ensures a device reads/writes only its own
     rows.

4. **Realtime + poll fallback**, not one or the other. Subscribe via Realtime for
   live updates; poll every N seconds to catch anything missed after a
   disconnect (dedupe by row id — same shape as a webhook-reconnect consolidation).

## Proposed Supabase data model

```
profiles     -- Supabase auth user
devices      id, user_id, name, token_hash, last_seen_at, created_at
reports      id, user_id, device_id, video_name, note, created_at,
             thumbnail_url, confidence, status,           -- 'ok' | 'error'
             report_json                                   -- the full coaching report
jobs         id, user_id, device_id, type,                -- 'rerun'
             report_id, status,                            -- 'pending'|'running'|'done'|'error'
             created_at, updated_at
```
Plus a Storage bucket (e.g. `thumbnails`) for the one representative frame.

**Two flows:**
- *New analysis* (Dropbox drop or UI upload): local inserts a `reports` row +
  uploads a thumbnail. Frontend shows it live via Realtime.
- *Rerun*: frontend inserts a `jobs` row (`pending`) → local (subscribed) claims
  it (`running`), re-analyzes the **locally stored** video, updates the `reports`
  row, marks the job `done`. Frontend updates live. Needs a status state machine
  so a job can't be double-claimed.

## Build phases (do not build all at once)

- **Phase A — one-way push (do this first; it proves the only unknown link).**
  Local app authenticates to Supabase with the device token and pushes report
  rows + thumbnails after each analysis. Verify they appear in Supabase.
- **Phase B — rerun loop.** Local subscribes to `jobs`, reruns, updates `reports`,
  marks job done; status state machine prevents double-runs.
- **Phase C — frontend (Vite + Supabase).** Live list of reports (name, date,
  thumbnail, results) + a Rerun button, all off Realtime; Supabase Auth for login
  and device-token generation.
- **Phase D — later.** Chat with the coach over a report + its video reference.

## Where the local code hooks in (current contract)

The local repo is already structured so cloud sync drops in as an **optional,
env-gated module** (`ui/sync.py`), exactly like the watcher and email features —
local-only must keep working untouched when no Supabase config is present.

Key integration seam: **`ui/core.py` → `process_video(...)` returns a result
dict** after every analysis (both UI uploads and watcher drops go through it):

```python
{ "sid", "status", "confidence", "subject_analyzed",
  "report" (dict|None), "report_text" (json str), "filename" }
```
After it inserts the local SQLite row, that's the natural place to also call
`sync.push_report(result, video_path, note)` when sync is enabled.

**Thumbnail:** during `process_video`, ffmpeg already extracts frames into a temp
dir (`coach.extract_frames`). Phase A should grab one representative frame (e.g.
a mid-sequence frame) and keep it for upload, instead of letting the temp dir be
deleted. A small change to `process_video` (save one frame to `ui/data/thumbs/`)
gives both the cloud thumbnail and a nicer local history view.

### Current repo map (so a fresh session knows the codebase)

- `experiments/loop0_claude_vision/analyze.py` — the engine (CLI + importable).
  `extract_frames(video, interval, max_frames, out_dir, start=, duration=)`,
  `build_content(frames, focus, subject, note=)`,
  `analyze(frames, focus, subject, note=)` → report dict validated against
  `REPORT_SCHEMA`. `FOCUS_GUIDES` lists focus categories. CLI flags:
  `--focus --subject --note --start --duration --interval --max-frames --out`.
- `ui/core.py` — shared `db()`, `init_db()` (SQLite `sessions` table + `source`
  column migration), and `process_video(src_path, filename, focus, subject,
  params, source='ui', note=None)`. Paths: `DATA_DIR`, `UPLOAD_DIR`, `DB_PATH`
  (`ui/data/coach.db`). Imports the engine as `core.coach`.
- `ui/app.py` — FastAPI app. Routes: `/` (upload form + history + ⚙️ Setup panel
  + email test), `POST /analyze`, `/session/{sid}`, `/video/{sid}`,
  `POST /test-email`. Inline Jinja templates. Starts the watcher on startup.
- `ui/watcher.py` — folder watcher (polls `WATCH_DIR`, waits for size-stability,
  processes, moves to `processed/`/`failed/`, emails). `note_from_filename()`
  turns `backhand_drop-to-kitchen.mp4` into a coaching note and ignores generic
  camera names (`PXL_`, `IMG_`, …).
- `ui/notify.py` — Resend email (`send_report`, `build_html`, `sample_result`,
  `configured`). Optional/env-gated.
- `ui/__init__.py` — package marker (modules import via `from ui import ...`).
- `run.sh` — one-command launcher (uv venv + deps + `.env` scaffold + uvicorn).
- `requirements.txt`, `.env.example`, `README.md`, `ui/README.md`.

`sessions` table columns: `id, created_at, filename, video_path, focus, subject,
params (json, includes "note"), status, confidence, subject_analyzed, report
(json text), frames_used, source`.

## Env vars (existing + to add)

Existing (local): `ANTHROPIC_API_KEY`; `WATCH_DIR`, `WATCH_FOCUS`,
`WATCH_SUBJECT`, `WATCH_PROCESSED_DIR`, `WATCH_FAILED_DIR`, `WATCH_INTERVAL`,
`WATCH_MAX_FRAMES`, `WATCH_POLL_SECONDS`; `RESEND_API_KEY`, `NOTIFY_EMAIL`,
`RESEND_FROM`, `APP_BASE_URL`.

To add for cloud sync (Phase A):
```
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon key>
PBCOACH_DEVICE_TOKEN=<token the user generates in the frontend>
# PBCOACH_SYNC=1                  # or simply: enabled when the three above are set
```

## Conventions / gotchas (match these)

- **Optional features are env-gated** and degrade to no-ops when unconfigured
  (see watcher/email). Cloud sync must do the same — local-only keeps working.
- **`.env` is read only at startup** — the app must be restarted after edits.
  This is documented in `.env.example` (top banner) and the README; keep it true.
- **Python via `uv`, target 3.12.** Homebrew's `python@3.x` ships a broken
  `pyexpat` that crashes pip; `uv venv --python 3.12` sidesteps it. `run.sh`
  handles setup.
- **Testing without external services:** the suite stubs `coach.analyze` /
  `coach.extract_frames` and uses `starlette.testclient.TestClient`; mock
  `httpx.post` for Resend. Do the same for Supabase calls so tests run offline.
- **One analysis path:** both UI and watcher go through `core.process_video` —
  add cloud push there, once, not in two places.
- **Dev branch:** `claude/pickleball-coach-device-3w573r`. The repo started empty
  so this branch is currently the default; a `main` may need seeding before a PR.
- This session's GitHub scope was `alnutile/raspberry-coach` only. The frontend
  lives in `alnutile/pbcoach-frontend` — add it to the next session's scope to
  push there, or have the session hand you files to commit.

## What to provide in the next session

1. `SUPABASE_URL` and the **anon** key (never the service_role key on clients).
2. Confirm the auth approach (device-token → edge-function → scoped JWT + RLS),
   or describe what you'd prefer.
3. Any tables/schema you've already created (else use the model above).
4. Which to build first — recommended: **Phase A (one-way push)**, because it
   proves device auth + the Supabase connection, the only genuinely unknown part.
   Everything after it is wiring.
