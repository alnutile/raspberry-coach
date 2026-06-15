#!/usr/bin/env python3
"""Loop 0 UI — a local web app over the Claude-vision coaching probe.

Drag in a clip, set focus/subject/window, get the same structured report the
CLI produces — but stored in a local SQLite history so the runs accumulate into
a corpus (the thing we'll later eval against and use to train a local model).

Everything stays on your machine. Run it:

    uvicorn ui.app:app --reload         # from the repo root
    # open http://localhost:8000

Needs ANTHROPIC_API_KEY (export it or put it in a .env) and ffmpeg on PATH.
"""

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from jinja2 import Environment, select_autoescape

# Reuse the CLI engine verbatim — one source of truth for the analysis.
LOOP0_DIR = Path(__file__).resolve().parent.parent / "experiments" / "loop0_claude_vision"
sys.path.insert(0, str(LOOP0_DIR))
import analyze as coach  # noqa: E402

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "coach.db"

app = FastAPI(title="raspberry-coach")


# --------------------------------------------------------------------------- db
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                filename TEXT NOT NULL,
                video_path TEXT NOT NULL,
                focus TEXT NOT NULL,
                subject TEXT,
                params TEXT NOT NULL,
                status TEXT NOT NULL,          -- 'ok' or 'error'
                confidence TEXT,
                subject_analyzed TEXT,
                report TEXT,                   -- JSON report, or error message
                frames_used INTEGER
            )
            """
        )


@app.on_event("startup")
def _startup() -> None:
    init_db()


# -------------------------------------------------------------------- templates
env = Environment(autoescape=select_autoescape(["html"]))

BASE = """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>raspberry-coach</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 860px; margin: 2rem auto;
         padding: 0 1rem; }
  h1 { margin-bottom: .2rem; } h1 a { text-decoration: none; color: inherit; }
  .sub { color: #888; margin-top: 0; }
  form { display: grid; gap: .6rem; padding: 1rem; border: 1px solid #8884;
         border-radius: 10px; }
  .row { display: flex; gap: .6rem; flex-wrap: wrap; }
  label { display: grid; gap: .2rem; font-size: 13px; color: #888; }
  input, select { font: inherit; padding: .4rem; border-radius: 7px;
                  border: 1px solid #8886; background: #8881; color: inherit; }
  input[type=number] { width: 7rem; }
  button { font: inherit; padding: .5rem 1rem; border-radius: 8px; border: 0;
           background: #2563eb; color: #fff; cursor: pointer; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  td, th { text-align: left; padding: .5rem .4rem; border-bottom: 1px solid #8883; }
  a { color: #2563eb; }
  .badge { display: inline-block; padding: .1rem .5rem; border-radius: 999px;
           font-size: 12px; font-weight: 600; }
  .good { background: #16a34a22; color: #16a34a; }
  .okay, .medium { background: #d9770622; color: #d97706; }
  .needs_work, .low, .error { background: #dc262622; color: #dc2626; }
  .cant_tell { background: #6b728022; color: #6b7280; }
  .high { background: #16a34a22; color: #16a34a; }
  .card { border: 1px solid #8884; border-radius: 10px; padding: 1rem;
          margin: 1rem 0; }
  .obs { padding: .6rem 0; border-bottom: 1px solid #8883; }
  .obs:last-child { border: 0; }
  .aspect { font-weight: 600; }
  video { width: 100%; border-radius: 10px; margin-top: .5rem; }
  details { margin-top: 1rem; } pre { overflow:auto; background:#8881; padding:1rem;
            border-radius:8px; }
  .note { color:#888; font-size:13px; }
  button:disabled { opacity:.6; cursor:progress; }
  .working { display:flex; align-items:center; gap:.6rem; padding:.7rem .9rem;
             border-radius:8px; background:#2563eb18; color:#2563eb; font-size:14px; }
  .spinner { width:16px; height:16px; border:3px solid #2563eb44;
             border-top-color:#2563eb; border-radius:50%; flex:0 0 auto;
             animation:spin .8s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .done { background:#16a34a18; color:#16a34a; font-weight:600; }
</style></head><body>
<h1><a href="/">🏓 raspberry-coach</a></h1>
{% block body %}{% endblock %}
</body></html>
"""

INDEX = """
{% extends base %}{% block body %}
<p class="sub">Loop 0 — upload a practice clip, get coaching feedback. Local only.</p>
{% if not has_key %}
<p class="badge error">ANTHROPIC_API_KEY not set — export it or add a .env before analyzing.</p>
{% endif %}
<form action="/analyze" method="post" enctype="multipart/form-data" id="analyze-form">
  <label>Clip <input type="file" name="file" accept="video/*" required></label>
  <div class="row">
    <label>Focus
      <select name="focus">
        {% for f in focuses %}<option value="{{ f }}"
          {{ 'selected' if f == 'serve' else '' }}>{{ f }}</option>{% endfor %}
      </select>
    </label>
    <label>Subject (for doubles)
      <input type="text" name="subject" placeholder="player in the white shirt, near side">
    </label>
  </div>
  <div class="row">
    <label>Start (s)<input type="number" name="start" step="0.5" min="0" placeholder="optional"></label>
    <label>Duration (s)<input type="number" name="duration" step="0.5" min="0" placeholder="optional"></label>
    <label>Interval (s)<input type="number" name="interval" step="0.05" min="0.05" value="0.5"></label>
    <label>Max frames<input type="number" name="max_frames" min="1" value="16"></label>
  </div>
  <button type="submit" id="go">Analyze</button>
  <span class="note">Analysis runs Claude on the sampled frames — expect ~20–60s.</span>
  <div id="working" class="working" hidden>
    <span class="spinner"></span>
    <span>Analyzing… sampling frames and asking the coach (~20–60s). This page
      will jump to your report when it's done — no need to click again.</span>
  </div>
</form>
<script>
  var form = document.getElementById('analyze-form');
  var btn = document.getElementById('go');
  var working = document.getElementById('working');

  form.addEventListener('submit', function (e) {
    if (btn.disabled) { e.preventDefault(); return; }   // guard double-submit
    btn.disabled = true;
    btn.textContent = 'Analyzing…';
    working.hidden = false;
  });

  // Reset to a clean "ready" state whenever this page is shown — including when
  // the browser restores it from the back/forward cache after a run (otherwise
  // it reappears stuck in the disabled "Analyzing…" state).
  window.addEventListener('pageshow', function () {
    btn.disabled = false;
    btn.textContent = 'Analyze';
    working.hidden = true;
  });
</script>

<h2>History</h2>
{% if rows %}
<table>
  <tr><th>When</th><th>Clip</th><th>Focus</th><th>Confidence</th></tr>
  {% for r in rows %}
  <tr>
    <td>{{ r['created_at'][:16].replace('T',' ') }}</td>
    <td><a href="/session/{{ r['id'] }}">{{ r['filename'] }}</a></td>
    <td>{{ r['focus'] }}</td>
    <td>{% if r['status'] == 'ok' %}<span class="badge {{ r['confidence'] }}">{{ r['confidence'] }}</span>
        {% else %}<span class="badge error">error</span>{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% else %}<p class="note">No runs yet.</p>{% endif %}
{% endblock %}
"""

SESSION = """
{% extends base %}{% block body %}
<p><a href="/">← back</a></p>
<p class="sub">{{ row['filename'] }} · focus: {{ row['focus'] }}
   · {{ row['created_at'][:16].replace('T',' ') }}</p>
<video controls src="/video/{{ row['id'] }}"></video>

{% if row['status'] != 'ok' %}
  <div class="card"><span class="badge error">error</span>
    <p>{{ row['report'] }}</p></div>
{% else %}
  {% set rep = report %}
  <div class="card done">✓ Analysis complete — your report is below.</div>
  <div class="card">
    <span class="badge {{ rep['confidence'] }}">confidence: {{ rep['confidence'] }}</span>
    <p><strong>Analyzing:</strong> {{ rep['subject_analyzed'] }}</p>
    <p class="note"><strong>Footage:</strong>
       {{ 'usable' if rep['footage_quality']['usable'] else 'not usable' }} —
       {{ rep['footage_quality']['notes'] }}</p>
  </div>

  <div class="card">
    <h3>Observations</h3>
    {% for o in rep['observations'] %}
    <div class="obs">
      <span class="aspect">{{ o['aspect'] }}</span>
      <span class="badge {{ o['rating'] }}">{{ o['rating'].replace('_',' ') }}</span>
      <div>{{ o['assessment'] }}</div>
    </div>
    {% endfor %}
  </div>

  <div class="card">
    <h3>Top drills</h3>
    <ol>{% for d in rep['top_drills'] %}<li>{{ d }}</li>{% endfor %}</ol>
  </div>

  <details><summary>Raw JSON</summary><pre>{{ raw }}</pre></details>
{% endif %}
{% endblock %}
"""


def render(template: str, **ctx) -> str:
    return env.from_string(template).render(base=env.from_string(BASE), **ctx)


# ------------------------------------------------------------------------ routes
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    import os

    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return render(
        INDEX,
        rows=rows,
        focuses=sorted(coach.FOCUS_GUIDES),
        has_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
    )


@app.post("/analyze")
def run_analyze(
    file: UploadFile,
    focus: str = Form("serve"),
    subject: str = Form(""),
    start: str = Form(""),
    duration: str = Form(""),
    interval: float = Form(0.5),
    max_frames: int = Form(16),
) -> RedirectResponse:
    sid = uuid.uuid4().hex[:12]
    ext = Path(file.filename or "clip.mp4").suffix or ".mp4"
    video_path = UPLOAD_DIR / f"{sid}{ext}"
    video_path.write_bytes(file.file.read())

    def num(s: str):
        s = (s or "").strip()
        return float(s) if s else None

    params = {"start": num(start), "duration": num(duration),
              "interval": interval, "max_frames": max_frames}
    subject = subject.strip() or None

    status, confidence, subj_analyzed, report_text, frames_used = "ok", None, None, None, None
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmp:
            frames = coach.extract_frames(
                video_path, interval, max_frames, Path(tmp) / "frames",
                start=params["start"], duration=params["duration"],
            )
            frames_used = len(frames)
            report = coach.analyze(frames, focus, subject)
        report_text = json.dumps(report)
        confidence = report.get("confidence")
        subj_analyzed = report.get("subject_analyzed")
    except SystemExit as e:        # extract_frames/analyze call sys.exit on bad input
        status, report_text = "error", str(e)
    except Exception as e:         # API errors, bad video, etc.
        status, report_text = "error", f"{type(e).__name__}: {e}"

    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, filename, video_path, focus, "
            "subject, params, status, confidence, subject_analyzed, report, frames_used) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, datetime.now(timezone.utc).isoformat(), file.filename or "clip",
             str(video_path), focus, subject, json.dumps(params), status,
             confidence, subj_analyzed, report_text, frames_used),
        )
    return RedirectResponse(f"/session/{sid}", status_code=303)


@app.get("/session/{sid}", response_class=HTMLResponse)
def session(sid: str) -> HTMLResponse:
    with db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        return HTMLResponse("Not found", status_code=404)
    report = json.loads(row["report"]) if row["status"] == "ok" else None
    raw = json.dumps(report, indent=2) if report else row["report"]
    return HTMLResponse(render(SESSION, row=row, report=report, raw=raw))


@app.get("/video/{sid}")
def video(sid: str):
    with db() as conn:
        row = conn.execute("SELECT video_path FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None or not Path(row["video_path"]).exists():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(row["video_path"])
