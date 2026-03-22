import re
import httpx
import logging
from datetime import datetime, timedelta

import state
import teams

logger = logging.getLogger(__name__)

RESULTS_URL  = "http://localhost:3001/match?q=results"
UPCOMING_URL = "http://localhost:3001/match?q=upcoming"
APP_NAME = "valorant_recent"

_POLL_INTERVAL = 300   # seconds between API fetches
_PUSH_INTERVAL = 60    # seconds between display updates (countdown recalc)

# ── Module cache ──────────────────────────────────────────────────────────────

_cached_results:  list[dict] = []
_cached_upcoming: list[dict] = []
_last_fetch: datetime = datetime.min
_last_push:  datetime = datetime.min

# ── ETA parsing ───────────────────────────────────────────────────────────────

_ETA_RE = re.compile(
    r'(?:(\d+)\s*d(?:ay)?s?)?\s*'
    r'(?:(\d+)\s*h(?:r|our)?s?)?\s*'
    r'(?:(\d+)\s*m(?:in(?:ute)?s?)?)?',
    re.IGNORECASE,
)

def _parse_eta(s: str) -> timedelta | None:
    """Parse strings like '1d 2h', '14h 45m', '30m' into a timedelta."""
    if not s:
        return None
    m = _ETA_RE.match(s.strip())
    if not m or not any(m.groups()):
        return None
    days    = int(m.group(1) or 0)
    hours   = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    if days == hours == minutes == 0:
        return None
    return timedelta(days=days, hours=hours, minutes=minutes)


def _format_delta(delta: timedelta) -> str:
    """Format a timedelta into a compact display string."""
    total = int(delta.total_seconds())
    if total <= 0:
        return "STARTING"
    days    = total // 86400
    hours   = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_results() -> list[dict]:
    try:
        resp = httpx.get(RESULTS_URL, timeout=10)
        resp.raise_for_status()
        segments = resp.json().get("data", {}).get("segments", [])
        logger.info(f"[recent] results fetch OK — {len(segments)} match(es)")
        return segments[:5]
    except Exception as e:
        logger.error(f"[recent] results fetch failed: {e}")
        return []


def fetch_upcoming() -> list[dict]:
    """Fetch upcoming matches and attach abs_match_time to each entry."""
    try:
        resp = httpx.get(UPCOMING_URL, timeout=10)
        resp.raise_for_status()
        segments = resp.json().get("data", {}).get("segments", [])
        logger.info(f"[recent] upcoming fetch OK — {len(segments)} match(es)")
    except Exception as e:
        logger.error(f"[recent] upcoming fetch failed: {e}")
        return []

    now = datetime.now()
    for seg in segments:
        raw = (seg.get("time_until_match") or "").replace(" from now", "").strip()
        delta = _parse_eta(raw)
        seg["abs_match_time"] = (now + delta) if delta is not None else None

    return segments[:5]


# ── Format ────────────────────────────────────────────────────────────────────

def format_recent(results: list[dict], upcoming: list[dict]) -> dict:
    parts = []
    now = datetime.now()

    for m in upcoming[:3]:
        t1 = teams.get_tag(m.get("team1") or "?")
        t2 = teams.get_tag(m.get("team2") or "?")
        abs_time = m.get("abs_match_time")
        if abs_time is not None:
            eta = _format_delta(abs_time - now)
        else:
            raw = (m.get("time_until_match") or "").replace(" from now", "").strip()
            eta = raw
        parts.append(f"UP: {t1} v {t2}  {eta}" if eta else f"UP: {t1} v {t2}")

    for m in results[:3]:
        t1 = teams.get_tag(m.get("team1") or "?")
        t2 = teams.get_tag(m.get("team2") or "?")
        s1 = m.get("score1", "?")
        s2 = m.get("score2", "?")
        parts.append(f"RES: {t1} {s1}-{s2} {t2}")

    text = "   |   ".join(parts) if parts else "No Valorant matches"
    scroll_spd, dur = state.scroll_params_for_text(text)
    return {
        "text": text,
        "color": state.get_app_color(APP_NAME),
        "scrollSpeed": scroll_spd,
        "lifetime": 600,
        "duration": dur,
        "repeat": 1,
    }


# ── Push ──────────────────────────────────────────────────────────────────────

def push_recent(awtrix, results: list[dict], upcoming: list[dict]) -> None:
    global _cached_results, _cached_upcoming, _last_push
    _cached_results  = results
    _cached_upcoming = upcoming

    payload = format_recent(results, upcoming)
    state.active_apps[APP_NAME] = {
        "text": payload["text"],
        "color": payload["color"],
        "last_updated": datetime.now().strftime("%H:%M:%S"),
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        logger.info(
            f"[recent] pushed {len(upcoming)} upcoming + {len(results)} results "
            f"→ HTTP {resp.status_code}"
        )
    except Exception as e:
        logger.error(f"[recent] failed to push app: {e}")
    _last_push = datetime.now()


# ── Public interface ──────────────────────────────────────────────────────────

def tick(awtrix, is_live: bool) -> None:
    """Fetch on schedule; push recalculated countdowns every minute."""
    global _last_fetch

    now       = datetime.now()
    fetch_due = (now - _last_fetch).total_seconds() >= _POLL_INTERVAL
    push_due  = (now - _last_push).total_seconds()  >= _PUSH_INTERVAL

    if fetch_due:
        results  = fetch_results()
        upcoming = fetch_upcoming()
        _last_fetch = now
        _cached_results[:]  = results
        _cached_upcoming[:] = upcoming

        if results or upcoming:
            payload = format_recent(results, upcoming)
            state.active_apps[APP_NAME] = {
                "text":         payload["text"],
                "color":        payload["color"],
                "last_updated": datetime.now().strftime("%H:%M:%S"),
            }
        else:
            state.active_apps.pop(APP_NAME, None)
            if not is_live:
                try:
                    awtrix.delete_app(APP_NAME)
                except Exception:
                    pass
            logger.info("[recent] no matches — cleared app")

    if is_live:
        return  # suppressed on device — data cached for restore after match

    if (_cached_results or _cached_upcoming) and state.modules.get(APP_NAME, True) and push_due:
        push_recent(awtrix, _cached_results, _cached_upcoming)


def force_refresh() -> None:
    global _last_fetch, _last_push
    _last_fetch = datetime.min
    _last_push  = datetime.min


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[recent] cleared app")
    except Exception as e:
        logger.error(f"[recent] clear failed: {e}")


def restore(awtrix) -> None:
    if (_cached_results or _cached_upcoming) and state.modules.get(APP_NAME, True):
        push_recent(awtrix, _cached_results, _cached_upcoming)
        logger.info("[recent] restored from cache")
