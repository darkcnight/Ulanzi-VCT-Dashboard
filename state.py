"""
Shared in-process state. All fields are written by the scheduler task
and read by the API handlers. Safe for single-threaded asyncio use.
"""

# Scheduler
scheduler_state: str = "IDLE"    # IDLE | PRE_MATCH | LIVE | COOLDOWN
live_suppressed: bool = False    # True when non-live modules are cleared during LIVE
last_poll_at: str = ""
next_poll_in: float = 0.0

# Device connectivity
device_status: str = "unknown"   # "online" | "offline" | "unknown"
device_last_checked: str = ""

# Module enable flags — key must match the AWTRIX app name
modules: dict[str, bool] = {
    "valorant_live":   True,
    "valorant_recent": True,
    "weather":         True,
    "reddit_valorant": True,
    "vlr_news":        True,
    "countdown":       True,
    "timer":           True,
    "wordofday":       True,
    "twitch_live":     True,
    "pinned":          True,
}

# Display order — index maps to AWTRIX app position
module_order: list[str] = list(modules.keys())

# What's currently shown on the device
# { app_name: { "text": str, "color": str, "last_updated": str } }
active_apps: dict[str, dict] = {}

# Latest /api/stats payload from the device (temp, hum, lux, bri, …)
device_stats: dict = {}

# Runtime config — loaded from config.json on startup, kept in sync with saves
cfg: dict = {}

# Default colors per app (used when app_colors has no override)
APP_DEFAULT_COLORS: dict[str, str] = {
    "valorant_live":   "#FF4655",
    "valorant_recent": "#4FC3F7",
    "reddit_valorant": "#FF8C00",
    "vlr_news":        "#C89B3C",
    "countdown":       "#E040FB",
    "timer":           "#00E676",
    "wordofday":       "#26C6DA",
    "twitch_live":     "#9146FF",
    "pinned":          "#FFFFFF",
    "weather":         "#FFD700",  # fallback when no WMO override
}


def get_app_color(app_name: str, fallback: str | None = None) -> str:
    """Return color for app: from app_colors if set, else pinned.color for pinned, else fallback or default."""
    colors = cfg.get("app_colors", {})
    if app_name in colors and colors[app_name]:
        return str(colors[app_name]).strip()
    if app_name == "pinned":
        return str(cfg.get("pinned", {}).get("color", APP_DEFAULT_COLORS["pinned"])).strip()
    if fallback is not None:
        return fallback
    return APP_DEFAULT_COLORS.get(app_name, "#FFFFFF")


def scroll_speed() -> int:
    """Global scroll speed (percentage) used by all display modules."""
    return int(cfg.get("display", {}).get("scroll_speed", 55))


def duration_for_text(text: str) -> int:
    """Legacy: returns duration from scroll_params_for_text."""
    _, dur = scroll_params_for_text(text)
    return dur


def scroll_params_for_text(text: str) -> tuple[int, int]:
    """
    Return (scrollSpeed, duration) for the given text.
    - Long text: use global scroll speed, duration = high cap (120s). App ends via repeat:1 when scroll completes.
    - Short text (natural scroll < floor_dur): slow down to fill floor_dur seconds.
    """
    d = cfg.get("display", {})
    base_speed = float(d.get("base_scroll_speed_px_per_sec", 40))
    matrix_width = int(d.get("matrix_width", 32))
    avg_char_width = float(d.get("avg_char_width", 5))
    scroll_pct = scroll_speed()
    floor_dur = int(d.get("app_duration_floor", 10))
    duration_cap = int(d.get("app_duration_cap", 120))  # safety cap for long text; repeat:1 ends when scroll done

    text_width = max(0, len(text) * avg_char_width)
    scroll_distance = text_width + matrix_width
    effective_speed = base_speed * (scroll_pct / 100) if scroll_pct > 0 else base_speed * 0.5
    natural_duration = scroll_distance / effective_speed if effective_speed > 0 else floor_dur

    if natural_duration >= floor_dur:
        # Long text: use global speed, high duration cap (repeat:1 will end when scroll completes)
        return (scroll_pct, duration_cap)

    # Short text: slow down to fill floor_dur seconds
    target_speed = scroll_distance / floor_dur
    adjusted_pct = int(round(target_speed * 100 / base_speed))
    adjusted_pct = max(10, min(100, adjusted_pct))
    return (adjusted_pct, floor_dur)
