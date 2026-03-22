"""
VLR News module — vlrggapi /news endpoint.
Fetches recent VLR.gg headlines filtered to the past N days.
Poll interval and max_age_days read from state.cfg at call time.
Suppressed during live Valorant matches.
"""

import httpx
import logging
from datetime import datetime, timedelta

import state

logger = logging.getLogger(__name__)

NEWS_URL = "http://localhost:3001/news"
APP_NAME = "vlr_news"

# ── Module state ──────────────────────────────────────────────────────────────

_last_fetch: datetime = datetime.min
_cached_text: str | None = None


# ── Config helpers ────────────────────────────────────────────────────────────

def _ncfg() -> dict:
    return state.cfg.get("news", {})

def _poll_interval() -> int:
    return int(_ncfg().get("poll_interval_seconds", 1800))

def _max_age_days() -> int:
    return int(_ncfg().get("max_age_days", 5))

def _max_items() -> int:
    return int(_ncfg().get("max_items", 5))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_headlines() -> list[str] | None:
    """Return a list of headlines on success (possibly empty), None on fetch error."""
    try:
        resp = httpx.get(NEWS_URL, timeout=10)
        resp.raise_for_status()
        segments = resp.json().get("data", {}).get("segments", [])
    except Exception as e:
        logger.error(f"[news] fetch failed: {e}")
        return None

    cutoff = datetime.now() - timedelta(days=_max_age_days())
    headlines = []
    for item in segments:
        try:
            pub = datetime.strptime(item["date"], "%B %d, %Y")
        except (ValueError, KeyError):
            continue
        if pub < cutoff:
            continue
        title = item.get("title", "").strip()
        if title:
            headlines.append(title)

    headlines = headlines[:_max_items()]
    logger.info(f"[news] {len(headlines)} headline(s) within {_max_age_days()}d (of {len(segments)} fetched)")
    return headlines


def _push(awtrix, text: str) -> None:
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text":        text,
        "color":       state.get_app_color(APP_NAME),
        "scrollSpeed": scroll_spd,
        "lifetime":    _poll_interval(),
        "duration":   dur,
        "repeat":     1,
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        preview = text[:120] + ("…" if len(text) > 120 else "")
        state.active_apps[APP_NAME] = {
            "text":         preview,
            "color":        state.get_app_color(APP_NAME),
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
        logger.info(f"[news] pushed {len(text)} chars → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[news] push failed: {e}")


# ── Public interface ──────────────────────────────────────────────────────────

def tick(awtrix, is_live: bool) -> None:
    global _last_fetch, _cached_text

    now = datetime.now()
    due = (now - _last_fetch).total_seconds() >= _poll_interval()

    if due:
        headlines = _fetch_headlines()  # None=error, []=genuinely empty, [...]= content
        _last_fetch = now

        if headlines is None:
            # Fetch error — keep existing cache unchanged, don't update device
            logger.warning("[news] keeping stale cache due to fetch error")
        elif headlines:
            _cached_text = "   |   ".join(headlines)
            preview = _cached_text[:120] + ("…" if len(_cached_text) > 120 else "")
            state.active_apps[APP_NAME] = {
                "text":         preview,
                "color":        state.get_app_color(APP_NAME),
                "last_updated": datetime.now().strftime("%H:%M:%S"),
            }
        else:
            # Successful fetch but nothing qualifies — clear cache and device
            _cached_text = ""
            state.active_apps.pop(APP_NAME, None)
            try:
                awtrix.delete_app(APP_NAME)
            except Exception:
                pass
            logger.info("[news] no qualifying headlines — cleared app")

    if is_live:
        return  # suppressed — cached for restore after match

    if _cached_text and state.modules.get(APP_NAME, True) and due:
        _push(awtrix, _cached_text)


def force_refresh() -> None:
    global _last_fetch
    _last_fetch = datetime.min


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[news] cleared app")
    except Exception as e:
        logger.error(f"[news] clear failed: {e}")


def restore(awtrix) -> None:
    if _cached_text and state.modules.get(APP_NAME, True):
        _push(awtrix, _cached_text)
        logger.info("[news] restored from cache")
