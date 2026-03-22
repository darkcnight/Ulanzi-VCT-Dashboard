import asyncio
import httpx
import logging
from datetime import datetime

import state
import teams

logger = logging.getLogger(__name__)

LIVE_URL    = "http://localhost:3001/match?q=live_score"
DETAILS_URL = "http://localhost:3001/match/details?match_id={}"
APP_NAME    = "valorant_live"

# ── Veto cache ────────────────────────────────────────────────────────────────

_cached_match_id:  str | None  = None
_cached_map_order: list[str]   = []   # e.g. ["Haven", "Breeze", "Abyss"]
_last_pushed_text: str | None  = None  # Skip push when unchanged so scroll continues


def _extract_match_id(match: dict) -> str | None:
    """Extract the numeric match ID from the match_page URL."""
    page  = match.get("match_page", "")
    parts = page.split("/")
    # https://www.vlr.gg/626546/furia-vs-...
    #  idx:  0       1  2       3
    return parts[3] if len(parts) > 3 and parts[3].isdigit() else None


def _fetch_map_order(match_id: str) -> list[str]:
    """Fetch veto data and return the ordered list of maps for the series."""
    try:
        resp = httpx.get(DETAILS_URL.format(match_id), timeout=10)
        resp.raise_for_status()
        segments = resp.json().get("data", {}).get("segments", [])
        if not segments:
            return []
        veto_str = segments[0].get("patch", "")
        maps = []
        for part in veto_str.split(";"):
            part = part.strip()
            if " pick " in part:
                maps.append(part.split(" pick ")[-1].strip())
            elif part.endswith(" remains"):
                maps.append(part.replace(" remains", "").strip())
        logger.info(f"[live] veto for match {match_id}: {maps}")
        return maps
    except Exception as e:
        logger.error(f"[live] veto fetch failed: {e}")
        return []


def _ensure_veto(match: dict) -> None:
    """Fetch and cache veto data when a new match is detected."""
    global _cached_match_id, _cached_map_order
    match_id = _extract_match_id(match)
    if match_id and match_id != _cached_match_id:
        _cached_map_order = _fetch_map_order(match_id)
        _cached_match_id  = match_id


# ── Live fetch ────────────────────────────────────────────────────────────────

async def fetch_live() -> list[dict] | None:
    """Fetch live match segments.
    Returns a list (possibly empty) on success, None on fetch error.
    On 429 rate limit, retries once after 30s before giving up.
    Callers must treat None as 'unknown' and not use it to exit LIVE mode.
    """
    for attempt in range(2):
        try:
            resp = httpx.get(LIVE_URL, timeout=10)
            resp.raise_for_status()
            segments = resp.json().get("data", {}).get("segments", [])
            logger.info(f"[live] fetch OK — {len(segments)} live match(es)")
            return segments
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt == 0:
                logger.warning("[live] 429 rate limited — retrying in 30s")
                await asyncio.sleep(30)
                continue
            logger.error(f"[live] fetch failed: {e}")
            return None
        except Exception as e:
            logger.error(f"[live] fetch failed: {e}")
            return None
    return None


# ── Formatting ────────────────────────────────────────────────────────────────

def _parse_round(val) -> int | None:
    """Parse a round value that may be an int, numeric string, or 'N/A'."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def format_live(match: dict) -> dict:
    """Format a live segment into an AWTRIX custom-app payload."""
    team1       = teams.get_tag(match.get("team1") or "???")
    team2       = teams.get_tag(match.get("team2") or "???")
    score1      = match.get("score1", "0")
    score2      = match.get("score2", "0")
    map_num     = match.get("map_number", "")
    current_map = match.get("current_map", "")

    t1_ct = _parse_round(match.get("team1_round_ct"))
    t1_t  = _parse_round(match.get("team1_round_t"))
    t2_ct = _parse_round(match.get("team2_round_ct"))
    t2_t  = _parse_round(match.get("team2_round_t"))

    has_rounds = any(v is not None for v in (t1_ct, t1_t, t2_ct, t2_t))

    if has_rounds:
        r1   = (t1_ct or 0) + (t1_t or 0)
        r2   = (t2_ct or 0) + (t2_t or 0)
        text = f"{team1} {r1}-{r2} {team2}  [{score1}-{score2}]"
        if current_map:
            text += f" {current_map}"
    else:
        # Between maps or pre-match: show series score + upcoming maps from veto
        text = f"{team1} {score1}-{score2} {team2}"
        if map_num and current_map:
            text += f"  M{map_num} {current_map}"
        elif current_map:
            text += f"  {current_map}"

        if _cached_map_order and current_map:
            try:
                idx       = _cached_map_order.index(current_map)
                remaining = _cached_map_order[idx + 1:]
                if remaining:
                    text += f"  | Next: {remaining[0]}"
                if len(remaining) > 1:
                    text += f"  Dec: {remaining[-1]}"
            except ValueError:
                pass

    scroll_spd, dur = state.scroll_params_for_text(text)
    return {
        "text":        text,
        "color":       state.get_app_color(APP_NAME),
        "scrollSpeed": scroll_spd,
        "lifetime":    0,  # No auto-removal; scroll continues until content changes
        "duration":   dur,
        "repeat":     -1,  # Loop so screen doesn't go blank when this is the only app
    }


# ── Push ──────────────────────────────────────────────────────────────────────

def push_live(awtrix, matches: list[dict]) -> None:
    global _last_pushed_text
    if not matches:
        _last_pushed_text = None
        try:
            awtrix.delete_app(APP_NAME)
            state.active_apps.pop(APP_NAME, None)
            logger.info("[live] cleared app (no live matches)")
        except Exception as e:
            logger.error(f"[live] failed to clear app: {e}")
        return

    match = matches[0]
    _ensure_veto(match)
    payload = format_live(match)
    base_text = payload["text"]
    if base_text == _last_pushed_text:
        return  # No change — let scroll continue uninterrupted
    _last_pushed_text = base_text

    # 8 copies for smoother scroll (fewer visible restarts)
    payload["text"] = "   |   ".join([base_text] * 8)

    state.active_apps[APP_NAME] = {
        "text":         base_text,
        "color":        payload["color"],
        "last_updated": datetime.now().strftime("%H:%M:%S"),
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        logger.info(f"[live] pushed '{base_text}' → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[live] failed to push app: {e}")
