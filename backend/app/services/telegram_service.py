r"""
Telegram Bot notification service.

Single-user design: sends price alerts to a fixed chat_id.
No subscription management or DB needed — just two env vars:
  TELEGRAM_BOT_TOKEN  — from @BotFather
  TELEGRAM_CHAT_ID    — your personal chat ID (get via /getUpdates after sending /start)

Message format example:
  ⚡ *Namazu — Monday, 16 Mar*
  🇸🇪 *SE3* · avg *0\.45* SEK/kWh · range 0\.22–0\.81
  ⬇️ Cheapest 2h: *02:00–04:00* · avg 0\.31 SEK/kWh
  ⬆️ Priciest 2h: *18:00–20:00* · avg 0\.78 SEK/kWh
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.services.price_service import get_prices_for_date

log = logging.getLogger(__name__)

_STOCKHOLM = ZoneInfo("Europe/Stockholm")
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _cheapest_window(slots: list[tuple[str, float]], hours: int) -> tuple[str, str, float] | None:
    """Return (start_label, end_label, avg_price) for cheapest consecutive `hours`-long window."""
    if len(slots) < hours:
        return None
    best = None
    for i in range(len(slots) - hours + 1):
        window = slots[i : i + hours]
        avg = sum(p for _, p in window) / hours
        if best is None or avg < best[2]:
            best = (slots[i][0], slots[i + hours - 1][0], avg)
    return best


def _priciest_window(slots: list[tuple[str, float]], hours: int) -> tuple[str, str, float] | None:
    """Return (start_label, end_label, avg_price) for most expensive consecutive `hours`-long window."""
    if len(slots) < hours:
        return None
    worst = None
    for i in range(len(slots) - hours + 1):
        window = slots[i : i + hours]
        avg = sum(p for _, p in window) / hours
        if worst is None or avg > worst[2]:
            worst = (slots[i][0], slots[i + hours - 1][0], avg)
    return worst


def _escape(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def build_telegram_message(db, area: str, target_date: date | None = None) -> str | None:
    """Build the Telegram message for the given date's prices. Defaults to tomorrow."""
    target = target_date or (datetime.now(tz=_STOCKHOLM) + timedelta(days=1)).date()
    rows = get_prices_for_date(db, target, area)
    if not rows:
        return None

    # Aggregate to hourly slots (average over 15-min slots within each hour)
    from collections import defaultdict

    hour_prices: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        ts = r.timestamp_utc
        local_hour = ts.astimezone(_STOCKHOLM).hour
        hour_prices[local_hour].append(float(r.price_sek_kwh))

    hourly: list[tuple[str, float]] = []
    for h in sorted(hour_prices):
        avg_h = sum(hour_prices[h]) / len(hour_prices[h])
        hourly.append((f"{h:02d}:00", avg_h))

    if not hourly:
        return None

    prices = [p for _, p in hourly]
    day_avg = sum(prices) / len(prices)
    day_min = min(prices)
    day_max = max(prices)
    day_label = target.strftime("%Y-%m-%d (%a)")  # e.g. "2024-03-16 (Sun)"

    cheap = _cheapest_window(hourly, 2)
    pricey = _priciest_window(hourly, 2)

    # Build MarkdownV2 message
    lines = [
        f"⚡ *{_escape(f'Namazu — {day_label}')}*",
        f"🇸🇪 *{area}* · avg *{_escape(f'{day_avg:.2f}')}* · range {_escape(f'{day_min:.2f}–{day_max:.2f}')} SEK/kWh",
    ]
    if cheap:
        lines.append(
            f"⬇️ Cheapest 2h: *{_escape(cheap[0])}–{_escape(cheap[1])}* · avg {_escape(f'{cheap[2]:.2f}')} SEK/kWh"
        )
    if pricey:
        lines.append(
            f"⬆️ Priciest 2h: *{_escape(pricey[0])}–{_escape(pricey[1])}* · avg {_escape(f'{pricey[2]:.2f}')} SEK/kWh"
        )

    return "\n".join(lines)


def send_telegram_alert(db, area: str = "SE3", target_date: date | None = None) -> dict:
    """
    Send price alert to the configured Telegram chat.
    Defaults to tomorrow's prices; pass target_date to override.
    Returns a status dict for logging.
    """
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.info("Telegram not configured — skipping (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")
        return {"status": "skipped", "reason": "not_configured"}

    message = build_telegram_message(db, area, target_date)
    if message is None:
        log.info("No tomorrow prices for %s — skipping Telegram alert", area)
        return {"status": "skipped", "reason": "no_data"}

    url = _TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "MarkdownV2",
                },
            )
        resp.raise_for_status()
        log.info("Telegram alert sent for %s", area)
        return {"status": "ok", "area": area}
    except httpx.HTTPStatusError as exc:
        log.error("Telegram API error %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


def build_degradation_message(area: str, alert_data: dict) -> str:
    """
    Build Telegram MarkdownV2 message for model degradation alert.

    alert_data: {mae_7d, mae_30d, ratio, threshold, degraded}
    """
    ratio_str = _escape(f"{alert_data['ratio']:.2f}")
    mae_7d_str = _escape(f"{alert_data['mae_7d']:.4f}")
    mae_30d_str = _escape(f"{alert_data['mae_30d']:.4f}")
    threshold_str = _escape(f"{alert_data['threshold']:.1f}")

    return "\n".join(
        [
            f"⚠️ *{_escape('Model Degradation Alert')}*",
            f"🇸🇪 *{area}* LGBM",
            f"7d MAE: *{mae_7d_str}* · 30d MAE: *{mae_30d_str}* SEK/kWh",
            f"Ratio: *{ratio_str}×* \\(threshold: {threshold_str}×\\)",
        ]
    )


def send_pipeline_alert(step_name: str, results: list[dict]) -> dict:
    """
    Send pipeline step failure alert to Telegram.

    Each result dict has {"status": str} plus optional "market", "date", "error" keys.
    Only sends when there are failures — caller should pre-check.
    """
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.info("Telegram not configured — skipping pipeline alert")
        return {"status": "skipped", "reason": "not_configured"}

    failed = [r for r in results if r["status"] == "error"]
    ok = [r for r in results if r["status"] in ("ok", "cached")]

    def _label(r: dict) -> str:
        parts = []
        if "market" in r:
            parts.append(r["market"])
        if "date" in r:
            parts.append(r["date"])
        return " ".join(parts) or "unknown"

    failed_str = ", ".join(_label(r) for r in failed)
    message = "\n".join(
        [
            f"🔴 *{_escape(f'Namazu — {step_name}')}*",
            f"Failed: {_escape(failed_str)}",
            f"OK: {_escape(f'{len(ok)} tasks succeeded')}",
        ]
    )

    url = _TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "MarkdownV2",
                },
            )
        resp.raise_for_status()
        log.info("Pipeline alert sent for %s (%d failed)", step_name, len(failed))
        return {"status": "ok", "step": step_name, "failed_count": len(failed)}
    except Exception as exc:
        log.error("Pipeline alert send failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


def send_degradation_alert(area: str, alert_data: dict) -> dict:
    """
    Send model degradation alert to the configured Telegram chat.
    Called by the daily pipeline when 7d MAE exceeds threshold × 30d MAE.
    """
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.info("Telegram not configured — skipping degradation alert")
        return {"status": "skipped", "reason": "not_configured"}

    message = build_degradation_message(area, alert_data)
    url = _TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "MarkdownV2",
                },
            )
        resp.raise_for_status()
        log.info("Degradation alert sent for %s (ratio=%.2f)", area, alert_data["ratio"])
        return {"status": "ok", "area": area, "ratio": alert_data["ratio"]}
    except httpx.HTTPStatusError as exc:
        log.error("Telegram degradation alert error %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        log.error("Telegram degradation alert failed: %s", exc)
        return {"status": "error", "reason": str(exc)}
