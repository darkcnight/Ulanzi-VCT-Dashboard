"""
Weather module — reads Home Assistant (NEA Singapore integration): condition and
temperature from a weather entity, plus rainfall from the nearest station sensor.
Entity IDs are config (ha.weather_entity, ha.rain_entity). Poll interval is read
from state.cfg at call time. Suppressed during live Valorant matches.
"""

import logging
from datetime import datetime

import ha
import state

logger = logging.getLogger(__name__)

APP_NAME = "weather"

# ── HA weather condition → (label, hex colour) ───────────────────────────────

_CONDITIONS: dict[str, tuple[str, str]] = {
    "sunny":           ("Sunny",         "#FFD700"),
    "clear-night":     ("Clear",         "#FFD700"),
    "partlycloudy":    ("Partly cloudy", "#87CEEB"),
    "cloudy":          ("Cloudy",        "#9E9E9E"),
    "fog":             ("Foggy",         "#B0BEC5"),
    "hail":            ("Hail",          "#E0E0E0"),
    "lightning":       ("Thunderstorm",  "#FF6F00"),
    "lightning-rainy": ("Thunderstorm",  "#FF6F00"),
    "pouring":         ("Heavy rain",    "#01579B"),
    "rainy":           ("Rain",          "#0288D1"),
    "snowy":           ("Snow",          "#E0E0E0"),
    "snowy-rainy":     ("Sleet",         "#E0E0E0"),
    "windy":           ("Windy",         "#B0BEC5"),
    "windy-variant":   ("Windy",         "#B0BEC5"),
    "exceptional":     ("Alert",         "#FF6F00"),
}

# ── Module state ──────────────────────────────────────────────────────────────

_last_fetch: datetime = datetime.min
_cached: dict | None = None


# ── Config helpers ────────────────────────────────────────────────────────────

def _wcfg() -> dict:
    return state.cfg.get("weather", {})

def _hcfg() -> dict:
    return state.cfg.get("ha", {})

def _poll_interval() -> int:
    return int(_wcfg().get("poll_interval_seconds", 300))

def _weather_entity() -> str:
    return _hcfg().get("weather_entity", "weather.singapore_weather")

def _rain_entity() -> str:
    return _hcfg().get("rain_entity", "sensor.singapore_weather_rainfall_s228")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch() -> dict | None:
    obj = ha.get_state(_weather_entity())
    if not ha.usable(obj):
        return None
    temp = obj.get("attributes", {}).get("temperature")
    if temp is None:
        logger.warning(f"[weather] {_weather_entity()} has no temperature attribute")
        return None
    condition = obj["state"]
    label, color = _CONDITIONS.get(condition, (condition.replace("-", " ").title(), "#FFFFFF"))
    rain = ha.numeric(ha.get_state(_rain_entity()))
    logger.info(f"[weather] {temp}°C  {label}  rain={rain}")
    return {"temp": round(float(temp), 1), "label": label, "color": color, "rain": rain}


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


def _build_text(data: dict) -> str:
    text = f"{data['temp']}°C {data['label']}"
    if data.get("rain"):
        text += f"  |  Rain {data['rain']:g}mm"
    return text + _room_suffix()


def _push(awtrix, data: dict) -> None:
    text = _build_text(data)
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
            text = _build_text(_cached)
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
