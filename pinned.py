"""
Pinned Message module — user-defined text that persists in the app rotation.
Managed via the dashboard. Stored in config.json.
Separate from the ephemeral notify (one-shot overlay).
"""

import logging
from datetime import datetime

import state

logger = logging.getLogger(__name__)

APP_NAME = "pinned"
def _pcfg() -> dict:
    return state.cfg.get("pinned", {})


def _push(awtrix) -> None:
    cfg = _pcfg()
    text = cfg.get("text", "").strip()
    if not text:
        return
    color = state.get_app_color(APP_NAME)
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text": text,
        "color": color,
        "scrollSpeed": scroll_spd,
        "lifetime": 86400,
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
        logger.info(f"[pinned] pushed '{text[:60]}' → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[pinned] push failed: {e}")


def tick(awtrix, is_live: bool) -> None:
    """Re-push periodically to keep lifetime alive. No external fetch needed."""
    text = _pcfg().get("text", "").strip()
    if not text:
        state.active_apps.pop(APP_NAME, None)
        return

    color = state.get_app_color(APP_NAME)
    state.active_apps[APP_NAME] = {
        "text": text[:120] + ("…" if len(text) > 120 else ""),
        "color": color,
        "last_updated": datetime.now().strftime("%H:%M:%S"),
    }

    if is_live:
        return

    if state.modules.get(APP_NAME, True):
        _push(awtrix)


def force_refresh() -> None:
    pass  # no fetch timer — reads config directly


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[pinned] cleared app")
    except Exception as e:
        logger.error(f"[pinned] clear failed: {e}")


def restore(awtrix) -> None:
    if _pcfg().get("text", "").strip() and state.modules.get(APP_NAME, True):
        _push(awtrix)
        logger.info("[pinned] restored")
