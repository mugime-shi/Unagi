"""
CloudWatch Alarm → SNS → Telegram forwarder.

Standalone Lambda handler (stdlib only — no Docker, deployed as a zip).
Triggered by SNS when a CloudWatch Alarm changes state to ALARM.

Environment variables:
  TELEGRAM_BOT_TOKEN — from @BotFather
  TELEGRAM_CHAT_ID   — target chat (same as price alerts)
"""

import json
import os
import urllib.request

_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
_API_URL = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"


def handler(event, _context):
    for record in event.get("Records", []):
        _forward(record["Sns"]["Message"])


def _forward(raw: str) -> None:
    """Parse the SNS alarm payload and send a Telegram message."""
    try:
        msg = json.loads(raw)
        alarm   = msg.get("AlarmName", "unknown")
        state   = msg.get("NewStateValue", "?")
        reason  = msg.get("NewStateReason", "")
        text = f"\U0001f6a8 *Namazu Alert*\nAlarm: `{alarm}`\nState: {state}\n{reason}"
    except Exception:
        # Non-JSON SNS message (test publish etc.) — forward as-is
        text = f"\U0001f6a8 *Namazu Alert*\n{raw}"

    if not _TOKEN or not _CHAT_ID:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping")
        return

    payload = json.dumps({
        "chat_id":    _CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }).encode()

    req = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"Telegram response: {resp.status}")
