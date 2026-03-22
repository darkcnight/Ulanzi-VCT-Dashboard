"""
Word of the Day module — Merriam-Webster RSS feed (no API key required).
Fetches once per day, displays word + definition.
"""

import re
import httpx
import logging
from datetime import datetime
from html import unescape

import state

logger = logging.getLogger(__name__)

APP_NAME = "wordofday"
_POLL_INTERVAL = 86400
_RSS_URL = "https://www.merriam-webster.com/wotd/feed/rss2"

_last_fetch: datetime = datetime.min
_cached_text: str | None = None      # short version pushed to device
_cached_full_text: str | None = None  # full version for hover card
_last_date: str = ""


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _clean_text(text: str) -> str:
    """Remove Merriam-Webster branding from the definition text."""
    text = re.sub(r"Merriam-Webster'?s?\s*", '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _reformat_for_display(full: str) -> str:
    """Strip date, format as 'Word Of The Day: word • pronunciation • defn'."""
    # Remove "WORD — Word of the Day for March 10, 2026 is: " prefix
    text = re.sub(
        r'^[A-Z\s]+ — Word of the Day for [^:]+: ',
        '',
        full,
        flags=re.IGNORECASE,
    ).strip()
    if text:
        return "Word Of The Day: " + text
    return full


def _shorten(full: str) -> str:
    """Return a clock-friendly short version: word + definition only, no examples/etymology.
    Merriam-Webster separates the definition from the example sentence with ' //'.
    Expects full to already be formatted by _reformat_for_display.
    """
    idx = full.find(' //')
    if idx != -1:
        return full[:idx].strip()
    # Fallback: cut at the first sentence boundary after 60 chars
    m = re.search(r'\.\s', full[60:])
    if m:
        return full[:60 + m.start() + 1].strip()
    return full[:200]


def _fetch() -> str | None:
    try:
        resp = httpx.get(_RSS_URL, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        xml = resp.text

        item = re.search(r'<item>(.*?)</item>', xml, re.DOTALL)
        if not item:
            logger.warning("[wordofday] no <item> found in RSS")
            return None

        content = item.group(1)

        title = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', content)
        word = title.group(1).strip() if title else "?"

        desc = re.search(
            r'<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>',
            content, re.DOTALL
        )
        defn = ""
        if desc:
            defn = _clean_text(_strip_html(desc.group(1)))

        word = _clean_text(word)
        raw = f"{word.upper()} — {defn}" if defn else word.upper()
        text = _reformat_for_display(raw)
        logger.info(f"[wordofday] fetched: {word}")
        return text
    except Exception as e:
        logger.error(f"[wordofday] fetch failed: {e}")
        return None


def _push(awtrix, short: str, full: str) -> None:
    scroll_spd, dur = state.scroll_params_for_text(short)
    payload = {
        "text": short,
        "color": state.get_app_color(APP_NAME),
        "scrollSpeed": scroll_spd,
        "lifetime": _POLL_INTERVAL,
        "duration": dur,
        "repeat": 1,
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        state.active_apps[APP_NAME] = {
            "text":      short,
            "full_text": None,
            "color":     state.get_app_color(APP_NAME),
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
        logger.info(f"[wordofday] pushed → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[wordofday] push failed: {e}")


def tick(awtrix, is_live: bool) -> None:
    global _last_fetch, _cached_text, _cached_full_text, _last_date

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    due = (today != _last_date) or (now - _last_fetch).total_seconds() >= _POLL_INTERVAL

    if due:
        result = _fetch()
        if result:
            _cached_full_text = result
            _cached_text = _shorten(result)
        _last_fetch = now
        _last_date = today
        if _cached_text:
            state.active_apps[APP_NAME] = {
                "text":      _cached_text,
                "full_text": None,
                "color":     state.get_app_color(APP_NAME),
                "last_updated": now.strftime("%H:%M:%S"),
            }

    if is_live:
        return

    if _cached_text and state.modules.get(APP_NAME, True) and due:
        _push(awtrix, _cached_text, _cached_full_text or _cached_text)


def force_refresh() -> None:
    global _last_fetch, _last_date
    _last_fetch = datetime.min
    _last_date = ""


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[wordofday] cleared app")
    except Exception as e:
        logger.error(f"[wordofday] clear failed: {e}")


def restore(awtrix) -> None:
    if _cached_text and state.modules.get(APP_NAME, True):
        _push(awtrix, _cached_text, _cached_full_text or _cached_text)
        logger.info("[wordofday] restored from cache")
