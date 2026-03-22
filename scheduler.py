"""
Adaptive polling scheduler for Valorant match data.

State machine:
  IDLE       — no live match, nothing imminent → configurable idle interval
  PRE_MATCH  — upcoming match within N min     → configurable pre-match interval
  LIVE       — live match detected             → configurable live interval
  COOLDOWN   — match just ended               → configurable cooldown, then IDLE

Scheduler always wakes at the next :00 or :30 minute boundary if it is sooner
than the current state interval, so polls happen on the hour and half-hour.

All interval/threshold values are read from state.cfg at runtime so that
config changes via the API take effect without a restart.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

import state
import weather
import reddit
import news
import countdowns
import timer
import wordofday
import twitch_live
import pinned
import teams as teams_mod
from valorant_live import fetch_live, push_live
import valorant_recent
from valorant_recent import fetch_upcoming

logger = logging.getLogger(__name__)

MIN_SLEEP = 5   # never sleep less than 5s to avoid busy loops

_last_bri: int | None = None  # last brightness value pushed to device


def reset_brightness_cache() -> None:
    """Reset cached brightness so next _apply_auto_dim will re-send to device."""
    global _last_bri
    _last_bri = None


def apply_display_brightness(awtrix) -> None:
    """Apply brightness from config to device. Call after config save for immediate effect."""
    _apply_auto_dim(awtrix)


def _apply_auto_dim(awtrix) -> None:
    """Set brightness: auto-dim from lux when enabled, else fixed normal_brightness."""
    global _last_bri
    dcfg = state.cfg.get("display", {})
    if dcfg.get("auto_dim_enabled", False):
        lux = state.device_stats.get("lux")
        if lux is None:
            return
        threshold = int(dcfg.get("lux_threshold", 50))
        target = int(dcfg.get("dim_brightness", 20) if lux < threshold
                     else dcfg.get("normal_brightness", 180))
    else:
        target = int(dcfg.get("normal_brightness", 180))
    if target != _last_bri:
        awtrix.set_brightness(target)
        _last_bri = target
        logger.info(f"[display] brightness → {target}")


# ── Config helpers ────────────────────────────────────────────────────────────

def _vcfg() -> dict:
    return state.cfg.get("valorant", {})

def _interval(mode: str) -> int:
    v = _vcfg()
    mapping = {
        "IDLE":      v.get("poll_interval_idle_seconds", 300),
        "PRE_MATCH": v.get("poll_interval_pre_match_seconds", 60),
        "LIVE":      v.get("poll_interval_live_seconds", 20),
        "COOLDOWN":  v.get("poll_interval_idle_seconds", 300),
    }
    return int(mapping.get(mode, 300))

def _cooldown_duration() -> int:
    return int(_vcfg().get("cooldown_seconds", 180))

def _pre_match_window() -> int:
    return int(_vcfg().get("pre_match_window_minutes", 15))

def _should_suppress(live_matches: list[dict]) -> bool:
    """Return True if the current live matches warrant full suppression of other modules.

    Rules:
    - If live_priority is False → never suppress.
    - If favourite_teams is empty → always suppress (original behaviour).
    - Otherwise → suppress only when at least one team in any live match
      matches a tag in favourite_teams (case-insensitive).
    """
    v = _vcfg()
    if not v.get("live_priority", True):
        return False

    favourites = {t.strip().upper() for t in v.get("favourite_teams", []) if t.strip()}
    if not favourites:
        return True  # no filter set — suppress for all matches

    for match in live_matches:
        t1 = teams_mod.get_tag(match.get("team1") or "").upper()
        t2 = teams_mod.get_tag(match.get("team2") or "").upper()
        if t1 in favourites or t2 in favourites:
            return True

    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seconds_until_next_boundary() -> float:
    """Seconds until the next :00 or :30 minute mark."""
    now = datetime.now()
    elapsed = now.second + now.microsecond / 1_000_000
    if now.minute < 30:
        return (30 - now.minute) * 60 - elapsed
    else:
        return (60 - now.minute) * 60 - elapsed


def _parse_eta_minutes(eta_str: str) -> int | None:
    if not eta_str:
        return None
    s = eta_str.lower()
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*m", s)
    if not h and not m:
        return None
    total = 0
    if h:
        total += int(h.group(1)) * 60
    if m:
        total += int(m.group(1))
    return total


def _check_pre_match(upcoming: list[dict], current_mode: str) -> str:
    window = _pre_match_window()
    for match in upcoming:
        minutes = _parse_eta_minutes(match.get("time_until_match", ""))
        if minutes is not None and minutes <= window:
            if current_mode != "PRE_MATCH":
                logger.info(f"[scheduler] match starting in ~{minutes}m → PRE_MATCH")
            return "PRE_MATCH"
    if current_mode == "PRE_MATCH":
        logger.info("[scheduler] no imminent match → IDLE")
    return "IDLE"


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_scheduler(awtrix, module_map: dict, live_exempt: set) -> None:
    mode             = "IDLE"
    prev_mode        = "IDLE"
    cooldown_until: datetime | None = None
    live_fail_streak = 0
    MAX_LIVE_FAILS   = 3   # consecutive errors before we give up and exit LIVE
    current_live_matches: list[dict] = []  # last known live match list for suppression check
    suppressed = False                      # whether non-live modules were cleared this LIVE session

    logger.info("[scheduler] started")

    # Clear any stale valorant_live from device (e.g. after app restart)
    try:
        push_live(awtrix, [])
    except Exception:
        pass

    while True:
        try:
            now_str = datetime.now().strftime("%H:%M:%S")
            logger.info(f"[scheduler] mode={mode} — polling now ({now_str})")
            state.last_poll_at = now_str

            # ── Device stats + auto-dim ───────────────────────────────────────
            stats = awtrix.get_stats()
            state.device_stats        = stats or {}
            state.device_status       = "online" if stats is not None else "offline"
            state.device_last_checked = now_str
            if stats is None:
                logger.warning("[scheduler] AWTRIX device did not respond to ping")
            _apply_auto_dim(awtrix)

            # ── Valorant live ─────────────────────────────────────────────────
            live_result = await fetch_live()  # None=fetch error, []=no match, [...]= live

            if live_result is None:
                # Fetch error — don't use this to exit LIVE, but count failures
                if mode == "LIVE":
                    live_fail_streak += 1
                    logger.warning(
                        f"[scheduler] live fetch error ({live_fail_streak}/{MAX_LIVE_FAILS})"
                        f"{' — still holding LIVE' if live_fail_streak < MAX_LIVE_FAILS else ' — giving up, treating as no match'}"
                    )
                    if live_fail_streak < MAX_LIVE_FAILS:
                        # Hold in LIVE; skip the no-match exit logic this tick
                        live_result = live_result  # remains None; handled below
                    else:
                        # Too many consecutive failures — fall through as empty
                        live_result = []
                else:
                    live_result = []  # outside LIVE, treat error as no match

            if live_result is not None:
                # We have a definitive answer (success or forced-empty after streak)
                live_matches = live_result
                if live_matches:
                    live_fail_streak = 0
                    current_live_matches = live_matches
                    if _should_suppress(live_matches):
                        # Favourite team playing — enter LIVE
                        if mode != "LIVE":
                            logger.info("[scheduler] live match (favourite) detected → LIVE")
                        mode = "LIVE"
                        if state.modules.get("valorant_live", True):
                            push_live(awtrix, live_matches)
                    else:
                        # Non-favourite match — don't enter LIVE
                        if mode == "LIVE":
                            logger.info("[scheduler] live match is non-favourite → exiting LIVE")
                            mode = "COOLDOWN"
                            cooldown_until = datetime.now() + timedelta(seconds=_cooldown_duration())
                            push_live(awtrix, [])

                else:
                    live_fail_streak = 0
                    if mode == "LIVE":
                        logger.info("[scheduler] live match ended → COOLDOWN")
                        mode = "COOLDOWN"
                        cooldown_until = datetime.now() + timedelta(seconds=_cooldown_duration())
                        push_live(awtrix, [])   # clear live app regardless of flag

                    if mode == "COOLDOWN":
                        if datetime.now() >= cooldown_until:
                            logger.info("[scheduler] cooldown complete → IDLE")
                            mode = "IDLE"
                        else:
                            remaining = (cooldown_until - datetime.now()).seconds
                            logger.info(f"[scheduler] cooling down ({remaining}s left)")

                    if mode in ("IDLE", "PRE_MATCH"):
                        upcoming = fetch_upcoming()
                        mode = _check_pre_match(upcoming, mode)

            # ── LIVE suppression / restore ────────────────────────────────────
            # Only trigger enter/leave transitions when we had a definitive result
            entering_live = (live_result is not None) and (mode == "LIVE" and prev_mode != "LIVE")
            leaving_live  = (live_result is not None) and (prev_mode == "LIVE" and mode != "LIVE")

            if entering_live:
                logger.info("[scheduler] entering LIVE — suppressing non-live modules")
                for name, mod in module_map.items():
                    if name not in live_exempt and hasattr(mod, "clear"):
                        mod.clear(awtrix)
                suppressed = True

            if leaving_live:
                if suppressed:
                    logger.info("[scheduler] leaving LIVE — restoring modules")
                    for name, mod in module_map.items():
                        if name not in live_exempt and hasattr(mod, "restore"):
                            mod.restore(awtrix)
                suppressed = False

            state.live_suppressed = suppressed

            # ── Module ticks (self-rate-limited) ──────────────────────────────
            live = (mode == "LIVE")
            weather.tick(awtrix,           is_live=live)
            reddit.tick(awtrix,            is_live=live)
            news.tick(awtrix,              is_live=live)
            valorant_recent.tick(awtrix,   is_live=live)
            countdowns.tick(awtrix,        is_live=live)
            timer.tick(awtrix,             is_live=live)
            wordofday.tick(awtrix,         is_live=live)
            twitch_live.tick(awtrix,       is_live=live)
            pinned.tick(awtrix,            is_live=live)

        except Exception as exc:
            logger.exception(f"[scheduler] unhandled error in tick: {exc}")

        finally:
            # ── Update shared state & sleep ───────────────────────────────────
            prev_mode = mode
            state.scheduler_state = mode

            interval  = _interval(mode)
            boundary  = _seconds_until_next_boundary()
            sleep_for = max(MIN_SLEEP, min(interval, boundary))
            state.next_poll_in = sleep_for

            logger.info(
                f"[scheduler] next poll in {sleep_for:.0f}s "
                f"(mode_interval={interval}s, next_boundary={boundary:.0f}s)"
            )
            await asyncio.sleep(sleep_for)
