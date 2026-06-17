"""Watch a local folder for new video clips and auto-process them.

Point WATCH_DIR at a folder your Dropbox desktop app syncs into. When a clip
lands and finishes syncing, it's analyzed, added to history, moved to a
processed/ (or failed/) subfolder, and emailed via Resend.

Why poll instead of inotify/watchdog: synced folders (Dropbox, network drives)
don't fire reliable filesystem events, and we must wait for the download to
finish anyway. Polling + a size-stability check is the robust choice.

    WATCH_DIR            absolute path to watch (feature is off if unset)
    WATCH_PROCESSED_DIR  where to move done files   (default <WATCH_DIR>/processed)
    WATCH_FAILED_DIR     where to move failed files (default <WATCH_DIR>/failed)
    WATCH_FOCUS          focus for dropped clips    (default 'general')
    WATCH_SUBJECT        optional subject for dropped clips
    WATCH_INTERVAL       frame sampling interval s  (default 1.0)
    WATCH_MAX_FRAMES     frames per clip            (default 16)
    WATCH_POLL_SECONDS   seconds between scans       (default 5)
"""

import os
import shutil
import threading
import time
from pathlib import Path

from ui import core, notify

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}
_started = False
_lock = threading.Lock()


def status() -> dict:
    """For surfacing watcher state in the UI."""
    watch = os.environ.get("WATCH_DIR")
    return {
        "enabled": bool(watch),
        "watch_dir": watch,
        "focus": os.environ.get("WATCH_FOCUS", "general"),
        "emails": notify.configured(),
    }


def _dirs(watch: Path) -> tuple[Path, Path]:
    processed = Path(os.environ.get("WATCH_PROCESSED_DIR", watch / "processed"))
    failed = Path(os.environ.get("WATCH_FAILED_DIR", watch / "failed"))
    processed.mkdir(parents=True, exist_ok=True)
    failed.mkdir(parents=True, exist_ok=True)
    return processed, failed


def _candidates(watch: Path, skip: set[Path]) -> list[Path]:
    out = []
    for entry in watch.iterdir():
        if entry.is_dir() or entry in skip:
            continue
        if entry.name.startswith(".") or entry.suffix.lower() not in VIDEO_EXTS:
            continue
        out.append(entry)
    return out


def _process_one(path: Path, processed: Path, failed: Path) -> None:
    focus = os.environ.get("WATCH_FOCUS", "general")
    if focus not in core.coach.FOCUS_GUIDES:
        focus = "general"
    subject = (os.environ.get("WATCH_SUBJECT") or "").strip() or None
    params = {
        "start": None, "duration": None,
        "interval": float(os.environ.get("WATCH_INTERVAL", "1.0")),
        "max_frames": int(os.environ.get("WATCH_MAX_FRAMES", "16")),
    }

    print(f"[watcher] processing {path.name}", flush=True)
    dest_dir = processed
    try:
        result = core.process_video(path, path.name, focus, subject, params, source="watch")
        if result["status"] != "ok":
            dest_dir = failed
        sent, msg = notify.send_report(result)
        print(f"[watcher] {path.name}: {result['status']}; email: {msg}", flush=True)
    except Exception as e:  # truly unexpected — keep the loop alive
        dest_dir = failed
        print(f"[watcher] ERROR on {path.name}: {e}", flush=True)

    # Move the original out of the watch folder (collision-safe).
    target = dest_dir / path.name
    if target.exists():
        target = dest_dir / f"{int(time.time())}_{path.name}"
    try:
        shutil.move(str(path), str(target))
    except Exception as e:
        print(f"[watcher] could not move {path.name}: {e}", flush=True)


def _loop(watch: Path, poll: float, stable_polls: int) -> None:
    processed, failed = _dirs(watch)
    # path -> (last_size, consecutive_stable_count)
    seen: dict[Path, tuple[int, int]] = {}
    skip = {processed, failed}
    while True:
        try:
            for path in _candidates(watch, skip):
                try:
                    size = path.stat().st_size
                except FileNotFoundError:
                    seen.pop(path, None)
                    continue
                last_size, count = seen.get(path, (-1, 0))
                if size > 0 and size == last_size:
                    count += 1
                else:
                    count = 0
                seen[path] = (size, count)
                if count >= stable_polls:        # size held steady -> sync done
                    seen.pop(path, None)
                    _process_one(path, processed, failed)
        except Exception as e:
            print(f"[watcher] scan error: {e}", flush=True)
        time.sleep(poll)


def start() -> dict:
    """Start the watcher thread if WATCH_DIR is set. Idempotent."""
    global _started
    with _lock:
        watch = os.environ.get("WATCH_DIR")
        if not watch or _started:
            return status()
        wpath = Path(watch).expanduser()
        if not wpath.is_dir():
            print(f"[watcher] WATCH_DIR is not a directory: {watch}", flush=True)
            return status()
        poll = float(os.environ.get("WATCH_POLL_SECONDS", "5"))
        stable = max(1, int(os.environ.get("WATCH_STABLE_POLLS", "2")))
        threading.Thread(
            target=_loop, args=(wpath, poll, stable), daemon=True, name="folder-watcher"
        ).start()
        _started = True
        print(f"[watcher] watching {wpath} (poll {poll}s)", flush=True)
        return status()
