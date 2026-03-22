"""
Weather module — Open-Meteo, configurable coordinates (default: Boon Lay, Singapore).
Poll interval and location read from state.cfg at call time.
Suppressed during live Valorant matches.
"""

import httpx
import logging
from datetime import datetime

import state

logger = logging.getLogger(__name__)

APP_NAME = "weather"

# ── WMO weather code → (label, hex colour) ───────────────────────────────────

_WMO: dict[int, tuple[str, str]] = {
    0:  ("Clear",         "#FFD700"),
    1:  ("Clear",         "#FFD700"),
    2:  ("Partly cloudy", "#87CEEB"),
    3:  ("Overcast",      "#9E9E9E"),
    45: ("Foggy",         "#B0BEC5"),
    48: ("Icy fog",       "#B0BEC5"),
    51: ("Drizzle",       "#4FC3F7"),
    53: ("Drizzle",       "#4FC3F7"),
    55: ("Drizzle",       "#0288D1"),
    61: ("Light rain",    "#4FC3F7"),
    63: ("Rain",          "#0288D1"),
    65: ("Heavy rain",    "#01579B"),
    71: ("Light snow",    "#E0E0E0"),
    73: ("Snow",          "#E0E0E0"),
    75: ("Heavy snow",    "#E0E0E0"),
    77: ("Snow grains",   "#E0E0E0"),
    80: ("Showers",       "#4FC3F7"),
    81: ("Showers",       "#0288D1"),
    82: ("Heavy showers", "#01579B"),
    95: ("Thunderstorm",  "#FF6F00"),
    96: ("Thunderstorm",  "#FF6F00"),
    99: ("Thunderstorm",  "#FF6F00"),
}

# ── Module state ──────────────────────────────────────────────────────────────

_last_fetch: datetime = datetime.min
_cached: dict | None = None


# ── Config helpers ────────────────────────────────────────────────────────────

def _wcfg() -> dict:
    return state.cfg.get("weather", {})

def _poll_interval() -> int:
    return int(_wcfg().get("poll_interval_seconds", 1800))

def _api_url() -> str:
    lat = _wcfg().get("latitude", 1.3404)
    lon = _wcfg().get("longitude", 103.7054)
    return (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,weather_code"
        "&timezone=Asia/Singapore"
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch() -> dict | None:
    try:
        resp = httpx.get(_api_url(), timeout=10)
        resp.raise_for_status()
        current = resp.json()["current"]
        temp  = round(float(current["temperature_2m"]), 1)
        code  = int(current["weather_code"])
        label, color = _WMO.get(code, ("Unknown", "#FFFFFF"))
        logger.info(f"[weather] {temp}°C  {label}  (WMO {code})")
        return {"temp": temp, "label": label, "color": color}
    except Exception as e:
        logger.error(f"[weather] fetch failed: {e}")
        return None


def _room_suffix() -> str:
    """Build the '  |  ⌂ 24.5°C 61%' suffix from device sensor data, if available."""
    stats = state.device_stats
    temp = stats.get("temp")
    hum  = stats.get("hum")
    if temp is None or hum is None:
        return ""
    offset = float(state.cfg.get("display", {}).get("sensor_temp_offset", 0))
    room_temp = round(float(temp) + offset, 1)
    room_hum  = round(float(hum))
    return f"  |  \u2302 {room_temp}\u00b0C {room_hum}%"


def _push(awtrix, data: dict) -> None:
    text = f"{data['temp']}°C {data['label']}" + _room_suffix()
    color = state.get_app_color(APP_NAME, fallback=data["color"])
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text": text,
        "color": color,
        "scrollSpeed": scroll_spd,
        "lifetime": _poll_interval(),
        "duration": dur,
        "repeat": 1,
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        state.active_apps[APP_NAME] = {
            "text": text,
            "color": color,
            "last_updated": datetime.now().strftime("%H:%M:%S"),
        }
        logger.info(f"[weather] pushed '{text}' → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[weather] push failed: {e}")


# ── Public interface ──────────────────────────────────────────────────────────

def tick(awtrix, is_live: bool) -> None:
    global _last_fetch, _cached

    now = datetime.now()
    due = (now - _last_fetch).total_seconds() >= _poll_interval()

    if due:
        result = _fetch()
        if result:
            _cached = result
        _last_fetch = now   # update even on failure to avoid hammering
        if _cached:
            text = f"{_cached['temp']}°C {_cached['label']}" + _room_suffix()
            color = state.get_app_color(APP_NAME, fallback=_cached["color"])
            state.active_apps[APP_NAME] = {
                "text":         text,
                "color":        color,
                "last_updated": datetime.now().strftime("%H:%M:%S"),
            }

    if is_live:
        return  # suppressed — data cached for when match ends

    if _cached and state.modules.get(APP_NAME, True) and due:
        _push(awtrix, _cached)


def force_refresh() -> None:
    global _last_fetch
    _last_fetch = datetime.min


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
        state.active_apps.pop(APP_NAME, None)
        logger.info("[weather] cleared app")
    except Exception as e:
        logger.error(f"[weather] clear failed: {e}")


def restore(awtrix) -> None:
    if _cached and state.modules.get(APP_NAME, True):
        _push(awtrix, _cached)
        logger.info("[weather] restored from cache")
