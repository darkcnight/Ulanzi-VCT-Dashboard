"""
Countdown timer module — shows days/hours until configured events.
Events are stored in config.json and managed via the dashboard.
"""

import logging
from datetime import datetime

import state

logger = logging.getLogger(__name__)

APP_NAME = "countdown"
_POLL_INTERVAL = 3600

_last_fetch: datetime = datetime.min
_cached_text: str | None = None


def _build_text() -> str:
    events = state.cfg.get("countdowns", {}).get("events", [])
    now = datetime.now()
    parts = []
    for ev in events:
        try:
            target = datetime.strptime(ev["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        delta = target - now
        if delta.total_seconds() < -86400:
            continue
        name = ev.get("name", "???")
        days = delta.days
        hours = delta.seconds // 3600
        if delta.total_seconds() <= 0:
            parts.append(f"{name} NOW!")
        elif days > 0:
            parts.append(f"{name} in {days} day{'s' if days != 1 else ''}")
        else:
            parts.append(f"{name} in {hours} hour{'s' if hours != 1 else ''}")
    return "   |   ".join(parts) if parts else ""


def _push(awtrix, text: str) -> None:
    color = state.get_app_color(APP_NAME)
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text": text,
        "color": color,
        "scrollSpeed": scroll_spd,
        "lifetime": _POLL_INTERVAL,
        "duration": dur,
        "repeat": 1,
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        state.active_apps[APP_NAME] = {
            "text": text[:120] + ("…" if len(text) > 120 else ""),
            "color": color,
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
        logger.info(f"[countdown] pushed → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[countdown] push failed: {e}")


def tick(awtrix, is_live: bool) -> None:
    global _last_fetch, _cached_text

    now = datetime.now()
    due = (now - _last_fetch).total_seconds() >= _POLL_INTERVAL

    if due:
        _cached_text = _build_text()
        _last_fetch = now
        if _cached_text:
            state.active_apps[APP_NAME] = {
                "text": _cached_text[:120] + ("…" if len(_cached_text) > 120 else ""),
                "color": state.get_app_color(APP_NAME),
                "last_updated": now.strftime("%H:%M:%S"),
            }
        else:
            state.active_apps.pop(APP_NAME, None)

    if is_live:
        return

    if _cached_text and state.modules.get(APP_NAME, True) and due:
        _push(awtrix, _cached_text)
    elif not _cached_text and due:
        try:
            awtrix.delete_app(APP_NAME)
        except Exception:
            pass


def force_refresh() -> None:
    global _last_fetch
    _last_fetch = datetime.min


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[countdown] cleared app")
    except Exception as e:
        logger.error(f"[countdown] clear failed: {e}")


def restore(awtrix) -> None:
    if _cached_text and state.modules.get(APP_NAME, True):
        _push(awtrix, _cached_text)
        logger.info("[countdown] restored from cache")
