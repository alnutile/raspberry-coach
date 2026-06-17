"""Email coaching results via Resend (https://resend.com).

Configured entirely through env vars so it's optional — if RESEND_API_KEY or
NOTIFY_EMAIL is missing, sending is skipped silently.

    RESEND_API_KEY   your Resend API key
    NOTIFY_EMAIL     where to send results
    RESEND_FROM      from-address (default onboarding@resend.dev — Resend's test
                     sender, which only delivers to your own account email; use a
                     verified domain to send anywhere)
    APP_BASE_URL     base for report links (default http://localhost:8000)
"""

import html
import os

import httpx

RESEND_ENDPOINT = "https://api.resend.com/emails"


def configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("NOTIFY_EMAIL"))


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def build_html(result: dict) -> str:
    """Render a result dict from core.process_video into an HTML email body."""
    base = os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    link = f"{base}/session/{result['sid']}"
    fname = _esc(result["filename"])

    if result["status"] != "ok" or not result.get("report"):
        return (
            f"<h2>🏓 Coaching run failed: {fname}</h2>"
            f"<p style='color:#b91c1c'>{_esc(result.get('report_text'))}</p>"
            f"<p><a href='{link}'>Open in raspberry-coach</a></p>"
        )

    rep = result["report"]
    obs = "".join(
        f"<li><strong>{_esc(o['aspect'])}</strong> "
        f"[{_esc(o['rating'])}]: {_esc(o['assessment'])}</li>"
        for o in rep.get("observations", [])
    )
    drills = "".join(f"<li>{_esc(d)}</li>" for d in rep.get("top_drills", []))
    return (
        f"<h2>🏓 Coaching report: {fname}</h2>"
        f"<p><strong>Confidence:</strong> {_esc(rep.get('confidence'))}<br>"
        f"<strong>Analyzed:</strong> {_esc(rep.get('subject_analyzed'))}</p>"
        f"<p><strong>Footage:</strong> {_esc(rep.get('footage_quality', {}).get('notes'))}</p>"
        f"<h3>Observations</h3><ul>{obs}</ul>"
        f"<h3>Top drills</h3><ol>{drills}</ol>"
        f"<p><a href='{link}'>Open the full report</a></p>"
    )


def send_report(result: dict) -> tuple[bool, str]:
    """Email a processed result. Returns (sent, message). Never raises."""
    if not configured():
        return False, "Resend not configured (need RESEND_API_KEY + NOTIFY_EMAIL)"

    conf = result.get("confidence") or result.get("status")
    subject = f"🏓 Coaching report: {result['filename']} ({conf})"
    payload = {
        "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
        "to": [os.environ["NOTIFY_EMAIL"]],
        "subject": subject,
        "html": build_html(result),
    }
    try:
        r = httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            json=payload,
            timeout=30,
        )
        if r.status_code >= 400:
            return False, f"Resend {r.status_code}: {r.text[:200]}"
        return True, "sent"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
