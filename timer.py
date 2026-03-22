"""
Timer module — countdown timers with chime on expiry.
Uses a background task (Option A) for second-level display updates.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import state

logger = logging.getLogger(__name__)

APP_NAME = "timer"

# Active timers: id -> { end_at, name, chime_sound, chime_enabled }
_active_timers: dict[str, dict] = {}
_timer_counter = 0
_awtrix_ref: object = None  # Set by run_timer_loop
_loop_task: asyncio.Task | None = None


def _format_remaining(seconds: int) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    if seconds < 0:
        return "0:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _build_display_text() -> str:
    """Build text for the timer app (e.g. 'Pomodoro 24:32' or '5:00')."""
    if not _active_timers:
        return ""
    parts = []
    now = datetime.now()
    for tid, t in list(_active_timers.items()):
        end_at = t.get("end_at")
        if not end_at:
            continue
        if isinstance(end_at, str):
            try:
                end_at = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            except Exception:
                continue
        remaining = max(0, int((end_at - now).total_seconds()))
        name = t.get("name", "Timer")
        if remaining == 0:
            parts.append(f"{name} done!")
        else:
            parts.append(f"{name} {_format_remaining(remaining)}")
    return "   |   ".join(parts) if parts else ""


def _push(awtrix, text: str) -> None:
    """Push timer text to the device."""
    color = state.get_app_color(APP_NAME)
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text": text,
        "color": color,
        "scrollSpeed": scroll_spd,
        "lifetime": 120,
        "duration": dur,
        "repeat": -1,  # Loop while timer is active
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        state.active_apps[APP_NAME] = {
            "text": text[:120] + ("…" if len(text) > 120 else ""),
            "color": color,
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
        logger.debug(f"[timer] pushed → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[timer] push failed: {e}")


def _fire_chime(awtrix, timer: dict) -> None:
    """Play chime and show notification when timer expires."""
    chime_enabled = timer.get("chime_enabled", True)
    if not chime_enabled:
        return
    sound = timer.get("chime_sound") or state.cfg.get("timer", {}).get("default_chime", "alarm1")
    name = timer.get("name", "Timer")
    try:
        awtrix.notify({
            "text": f"⏰ {name} done!",
            "duration": 5,
            "sound": sound,
        })
        logger.info(f"[timer] chime played for '{name}'")
    except Exception as e:
        logger.error(f"[timer] chime failed: {e}")


def _check_expired(awtrix) -> None:
    """Remove expired timers and fire chimes."""
    global _active_timers
    now = datetime.now()
    expired = []
    for tid, t in list(_active_timers.items()):
        end_at = t.get("end_at")
        if not end_at:
            continue
        if isinstance(end_at, str):
            try:
                end_at = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            except Exception:
                continue
        if now >= end_at:
            expired.append((tid, t))
    for tid, t in expired:
        _active_timers.pop(tid, None)
        _fire_chime(awtrix, t)
    if expired:
        logger.info(f"[timer] {len(expired)} timer(s) expired")


async def run_timer_loop(awtrix) -> None:
    """Background task: update display every second when timers are active."""
    global _awtrix_ref
    _awtrix_ref = awtrix
    logger.info("[timer] background loop started")
    _last_deleted_when_empty = False  # Only delete once when transitioning to empty
    while True:
        try:
            if _active_timers and state.modules.get(APP_NAME, True) and state.scheduler_state != "LIVE":
                _check_expired(awtrix)
                text = _build_display_text()
                if text:
                    _push(awtrix, text)
                    _last_deleted_when_empty = False
                else:
                    # All timers expired and removed
                    try:
                        awtrix.delete_app(APP_NAME)
                        state.active_apps.pop(APP_NAME, None)
                    except Exception:
                        pass
                    _last_deleted_when_empty = True
            elif not _active_timers:
                if not _last_deleted_when_empty:
                    try:
                        awtrix.delete_app(APP_NAME)
                        state.active_apps.pop(APP_NAME, None)
                        _last_deleted_when_empty = True
                    except Exception:
                        pass
        except Exception as e:
            logger.exception(f"[timer] loop error: {e}")
        await asyncio.sleep(1)


def start_timer(
    seconds: int,
    name: str = "Timer",
    chime_sound: str | None = None,
    chime_enabled: bool | None = None,
) -> str:
    """Start a new timer. Returns timer id."""
    global _timer_counter
    _timer_counter += 1
    tid = f"t{_timer_counter}"
    tcfg = state.cfg.get("timer", {})
    _active_timers[tid] = {
        "end_at": datetime.now() + timedelta(seconds=seconds),
        "name": name or "Timer",
        "chime_sound": chime_sound or tcfg.get("default_chime", "alarm1"),
        "chime_enabled": chime_enabled if chime_enabled is not None else tcfg.get("chime_enabled", True),
    }
    logger.info(f"[timer] started '{name}' for {seconds}s (id={tid})")
    return tid


def stop_timer(timer_id: str) -> bool:
    """Stop a timer. Returns True if it existed."""
    if timer_id in _active_timers:
        _active_timers.pop(timer_id)
        logger.info(f"[timer] stopped {timer_id}")
        return True
    return False


def get_active_timers() -> list[dict]:
    """Return list of active timers for API."""
    now = datetime.now()
    result = []
    for tid, t in _active_timers.items():
        end_at = t.get("end_at")
        if not end_at:
            continue
        if isinstance(end_at, str):
            try:
                end_at = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            except Exception:
                continue
        remaining = max(0, int((end_at - now).total_seconds()))
        result.append({
            "id": tid,
            "name": t.get("name", "Timer"),
            "remaining_seconds": remaining,
            "end_at": end_at.isoformat(),
        })
    return result


def get_presets() -> list[dict]:
    """Return timer presets from config."""
    return state.cfg.get("timer", {}).get("presets", [
        {"name": "5 min", "seconds": 300},
        {"name": "15 min", "seconds": 900},
        {"name": "25 min", "seconds": 1500},
        {"name": "1 hour", "seconds": 3600},
    ])


def tick(awtrix, is_live: bool) -> None:
    """Called by scheduler. When LIVE, we rely on clear(). Otherwise display is handled by background loop."""
    if is_live:
        return
    # Background loop handles display; tick just ensures we're in sync
    if _active_timers and state.modules.get(APP_NAME, True):
        text = _build_display_text()
        if text:
            _push(awtrix, text)


def force_refresh() -> None:
    """No cache to invalidate; timers are real-time."""
    pass


def clear(awtrix) -> None:
    """Remove timer app from device (e.g. when entering LIVE mode)."""
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[timer] cleared app")
    except Exception as e:
        logger.error(f"[timer] clear failed: {e}")


def restore(awtrix) -> None:
    """Restore timer display when leaving LIVE mode."""
    if _active_timers and state.modules.get(APP_NAME, True):
        text = _build_display_text()
        if text:
            _push(awtrix, text)
            logger.info("[timer] restored from active timers")
