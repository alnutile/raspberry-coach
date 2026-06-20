"""Shared core for the UI and the folder watcher.

Owns the SQLite history and the one function — `process_video` — that turns a
video file into a stored, analyzed session row. Both the web upload route and
the Dropbox-folder watcher call it, so there's exactly one analysis path.
"""

import json
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Reuse the CLI engine verbatim — one source of truth for the analysis.
LOOP0_DIR = Path(__file__).resolve().parent.parent / "experiments" / "loop0_claude_vision"
sys.path.insert(0, str(LOOP0_DIR))
import analyze as coach  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "coach.db"


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
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
        # Migration: tag where a run came from ('ui' upload vs 'watch' folder).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        if "source" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN source TEXT DEFAULT 'ui'")


def process_video(
    src_path: Path,
    filename: str,
    focus: str,
    subject: str | None,
    params: dict,
    source: str = "ui",
    note: str | None = None,
) -> dict:
    """Analyze a video and record it. Returns a summary dict (never raises for
    analysis failures — those are stored as status='error' rows)."""
    import tempfile

    sid = uuid.uuid4().hex[:12]
    ext = Path(filename).suffix or src_path.suffix or ".mp4"
    stored = UPLOAD_DIR / f"{sid}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, stored)
    params = {**params, "note": note}  # record the note alongside the run

    status, confidence, subj_analyzed, report_text, frames_used = "ok", None, None, None, None
    report: dict | None = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            frames = coach.extract_frames(
                stored, params["interval"], params["max_frames"], Path(tmp) / "frames",
                start=params.get("start"), duration=params.get("duration"),
            )
            frames_used = len(frames)
            report = coach.analyze(frames, focus, subject, note)
        report_text = json.dumps(report)
        confidence = report.get("confidence")
        subj_analyzed = report.get("subject_analyzed")
    except SystemExit as e:        # extract_frames/analyze call sys.exit on bad input
        status, report_text = "error", str(e)
    except Exception as e:         # API errors, unreadable video, etc.
        status, report_text = "error", f"{type(e).__name__}: {e}"

    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, filename, video_path, focus, "
            "subject, params, status, confidence, subject_analyzed, report, "
            "frames_used, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, datetime.now(timezone.utc).isoformat(), filename, str(stored),
             focus, subject, json.dumps(params), status, confidence, subj_analyzed,
             report_text, frames_used, source),
        )

    return {"sid": sid, "status": status, "confidence": confidence,
            "subject_analyzed": subj_analyzed, "report": report,
            "report_text": report_text, "filename": filename}
