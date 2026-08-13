"""Telegram Bot API delivery.

Two constraints shape this module:
  1. Telegram allows roughly 20 messages per minute to a single channel.
  2. A single message caps at 4096 characters.

So jobs are bundled into digest messages and sent with a deliberate pause.
"""

from __future__ import annotations

import time

from .http import session
from .logging_setup import get_logger
from .settings import get_settings

log = get_logger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"

MESSAGE_LIMIT = 4096
SECONDS_BETWEEN_MESSAGES = 3.5  # ~17 messages/minute, comfortably under the cap

# Characters Telegram requires escaping in MarkdownV2. Missing one of these is
# the single most common cause of a 400 from sendMessage.
_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"


class TelegramError(RuntimeError):
    pass


def escape_md(text: str | None) -> str:
    if not text:
        return ""
    out = []
    for ch in str(text):
        if ch in _MDV2_SPECIAL:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _call(method: str, payload: dict) -> dict:
    settings = get_settings()
    response = session().post(
        API.format(token=settings.telegram_bot_token, method=method),
        json=payload,
        timeout=30,
    )
    data = response.json() if response.content else {}

    if response.status_code == 429:
        retry_after = int(data.get("parameters", {}).get("retry_after", 30))
        log.warning("telegram rate limited, sleeping %ss", retry_after)
        time.sleep(retry_after + 1)
        return _call(method, payload)

    if not data.get("ok"):
        raise TelegramError(f"{method} failed: {response.status_code} {response.text[:300]}")
    return data["result"]


def send_message(chat_id: str, text: str, disable_preview: bool = True) -> int:
    """Send one MarkdownV2 message. Returns the Telegram message id."""
    if len(text) > MESSAGE_LIMIT:
        text = text[: MESSAGE_LIMIT - 20].rsplit("\n", 1)[0] + "\n\\.\\.\\."
    result = _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": disable_preview,
        },
    )
    return result.get("message_id", 0)


def format_job(job: dict) -> str:
    """Render one job as a MarkdownV2 block."""
    title = escape_md(job["title"])
    company = escape_md(job["company"])
    url = job["url"]

    lines = [f"*{title}*", f"🏢 {company}"]

    if job.get("location"):
        lines.append(f"📍 {escape_md(job['location'])}")

    meta = []
    if job.get("seniority"):
        meta.append(escape_md(job["seniority"]))
    if job.get("family"):
        meta.append(escape_md(job["family"]))
    if job.get("remote_policy") and job["remote_policy"] != "unclear":
        meta.append(escape_md(job["remote_policy"]))
    if meta:
        lines.append("🏷 " + escape_md(" · ").join(meta))

    if job.get("salary_min") or job.get("salary_max"):
        currency = escape_md(job.get("salary_currency") or "")
        low = f"{job['salary_min']:,.0f}" if job.get("salary_min") else "?"
        high = f"{job['salary_max']:,.0f}" if job.get("salary_max") else "?"
        lines.append(f"💰 {escape_md(low)}–{escape_md(high)} {currency}")

    skills = job.get("skills") or []
    if skills:
        lines.append("🛠 " + escape_md(", ".join(skills[:6])))

    if job.get("summary"):
        lines.append(f"_{escape_md(job['summary'])}_")

    lines.append(f"[Apply]({url})")
    return "\n".join(lines)


def send_digest(chat_id: str, jobs: list[dict]) -> int:
    """Send several jobs as one message. Returns the message id."""
    blocks = [format_job(j) for j in jobs]
    return send_message(chat_id, "\n\n➖➖➖\n\n".join(blocks))


def notify_failure(stage: str, error: str) -> None:
    """Best-effort alert. Never raises — a broken alert must not mask the real error."""
    settings = get_settings()
    channel = settings.telegram_alert_channel_id or settings.telegram_channel_id
    try:
        send_message(
            channel,
            f"⚠️ *Pipeline failure*\nStage: {escape_md(stage)}\n\n```\n{error[:600]}\n```",
        )
    except Exception as exc:  # noqa: BLE001 - alerting must never raise
        log.error("could not send failure alert: %s", exc)
