import json
import logging
import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import state
import teams
import weather
import reddit
import news
import valorant_recent
import countdowns
import timer
import wordofday
import twitch_live
import pinned
from valorant_live import fetch_live, push_live
from awtrix import AwtrixClient
from scheduler import run_scheduler, reset_brightness_cache, apply_display_brightness

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Attach error log handler for dashboard
from error_log import ErrorLogHandler, ERROR_LOG
_err_handler = ErrorLogHandler()
_err_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
_err_handler.setLevel(logging.WARNING)
logging.getLogger().addHandler(_err_handler)

CONFIG_PATH = "config.json"

# ── Config & shared client ────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)

def _save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

raw_config = _load_config()
state.cfg.update(raw_config)

if "module_order" in raw_config:
    state.module_order = raw_config["module_order"]

if "modules" in raw_config:
    state.modules.update(raw_config["modules"])

awtrix = AwtrixClient(raw_config["awtrix_ip"])

# ── Module registry ───────────────────────────────────────────────────────────

_module_map = {
    "weather":         weather,
    "reddit_valorant": reddit,
    "vlr_news":        news,
    "valorant_recent": valorant_recent,
    "countdown":       countdowns,
    "timer":           timer,
    "wordofday":       wordofday,
    "twitch_live":     twitch_live,
    "pinned":          pinned,
}
# Only valorant_live shows during LIVE; all other modules are suppressed
LIVE_EXEMPT = {"valorant_live"}

# ── Lifespan: start scheduler on boot ────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply built-in app toggles to device on startup if configured
    built_in = state.cfg.get("built_in_apps", {})
    if built_in:
        payload = {k: bool(v) for k, v in built_in.items() if k in ("TIM", "DAT", "TEMP", "HUM", "BAT")}
        if payload and awtrix.update_settings(payload):
            logger.info(f"[startup] device settings applied: {payload}")

    # Apply brightness from config on startup
    apply_display_brightness(awtrix)

    logger.info("Starting scheduler…")
    sched_task = asyncio.create_task(run_scheduler(awtrix, _module_map, LIVE_EXEMPT))
    timer_task = asyncio.create_task(timer.run_timer_loop(awtrix))
    yield
    timer_task.cancel()
    sched_task.cancel()
    try:
        await timer_task
    except asyncio.CancelledError:
        pass
    try:
        await sched_task
    except asyncio.CancelledError:
        pass
    logger.info("Scheduler stopped.")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Ulanzi Clock Controller", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/")
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    # Expire any timed-out app rows (e.g. twitch_live alert window) before serving
    from datetime import datetime as _dt
    _now = _dt.now()
    for _name in [k for k, v in state.active_apps.items()
                  if _now >= v.get("_expires_at", _dt.max)]:
        state.active_apps.pop(_name, None)

    active_apps = state.active_apps
    if state.scheduler_state == "LIVE" and getattr(state, "live_suppressed", False):
        active_apps = {k: v for k, v in active_apps.items() if k in LIVE_EXEMPT}

    return {
        "scheduler_state":    state.scheduler_state,
        "last_poll_at":       state.last_poll_at,
        "next_poll_in":       round(state.next_poll_in),
        "device_status":      state.device_status,
        "device_last_checked": state.device_last_checked,
        "modules":            state.modules,
        "module_order":       state.module_order,
        "active_apps":        active_apps,
        "countdowns":         state.cfg.get("countdowns", {}).get("events", []),
        "timer_active":       timer.get_active_timers(),
        "timer_presets":      timer.get_presets(),
        "twitch_channels":    state.cfg.get("twitch", {}).get("channels", []),
        "pinned":             state.cfg.get("pinned", {}),
        "app_colors":         state.cfg.get("app_colors", {}),
        "app_default_colors": state.APP_DEFAULT_COLORS,
    }


@app.get("/api/errors")
def api_errors():
    """Return rolling error/warning log for dashboard display."""
    return {"entries": list(ERROR_LOG)}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    return state.cfg


@app.get("/api/team-tags")
def api_team_tags():
    """Return sorted list of known team tags for favourite-teams autocomplete."""
    tags = set(teams.TEAM_TAGS.values())
    tags.update(state.cfg.get("team_tags", {}).values())
    return {"tags": sorted(tags)}


@app.post("/api/config")
async def save_config(request: Request):
    try:
        new_cfg = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not str(new_cfg.get("awtrix_ip", "")).strip():
        raise HTTPException(status_code=400, detail="awtrix_ip is required")

    awtrix.host = str(new_cfg["awtrix_ip"]).strip()
    state.cfg.clear()
    state.cfg.update(new_cfg)

    if "module_order" in new_cfg:
        state.module_order = new_cfg["module_order"]

    try:
        _save_config(new_cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    # Apply built-in app toggles to device if present (reboot required for changes; use Reboot Clock button)
    if "built_in_apps" in new_cfg:
        payload = {k: bool(v) for k, v in new_cfg["built_in_apps"].items()
                  if k in ("TIM", "DAT", "TEMP", "HUM", "BAT")}
        if payload:
            awtrix.update_settings(payload)

    # Apply brightness immediately when display config changes
    if "display" in new_cfg:
        reset_brightness_cache()
        apply_display_brightness(awtrix)

    # Force refresh all modules so new settings (scroll speed, etc.) apply immediately
    is_live = (state.scheduler_state == "LIVE")
    for name, mod in _module_map.items():
        if state.modules.get(name, True) and hasattr(mod, "force_refresh"):
            mod.force_refresh()
    for name, mod in _module_map.items():
        if state.modules.get(name, True) and hasattr(mod, "tick"):
            mod.tick(awtrix, is_live=is_live)

    logger.info(f"[config] saved — awtrix_ip={awtrix.host}")
    return {"status": "saved"}


@app.patch("/api/config")
async def patch_config(request: Request):
    """Merge partial config (e.g. app_colors) without full replace."""
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if "app_colors" in patch:
        merged = dict(state.cfg.get("app_colors", {}))
        merged.update(patch["app_colors"])
        state.cfg["app_colors"] = merged
    try:
        _save_config(state.cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save: {e}")
    return {"status": "saved"}


# ── Device ────────────────────────────────────────────────────────────────────

@app.post("/api/device/ping")
def api_ping():
    online = awtrix.ping()
    from datetime import datetime
    checked_at = datetime.now().strftime("%H:%M:%S")
    state.device_status       = "online" if online else "offline"
    state.device_last_checked = checked_at
    return {"status": state.device_status, "checked_at": checked_at}


@app.get("/api/device/settings")
def api_device_settings():
    """Return built-in app toggles from config."""
    built_in = state.cfg.get("built_in_apps", {})
    defaults = {"TIM": True, "DAT": True, "TEMP": True, "HUM": True, "BAT": True}
    return {k: built_in.get(k, v) for k, v in defaults.items()}


@app.post("/api/device/reboot")
def api_device_reboot():
    """Reboot the AWTRIX clock. Device may take ~30s to come back."""
    if awtrix.reboot():
        logger.info("[api] device reboot requested")
        return {"status": "rebooting", "ok": True}
    raise HTTPException(status_code=502, detail="Device did not respond to reboot")


@app.post("/api/soft-restart")
def api_soft_restart():
    """Reload config from disk and force refresh all modules."""
    global raw_config
    raw_config = _load_config()
    state.cfg.clear()
    state.cfg.update(raw_config)
    if "module_order" in raw_config:
        state.module_order = raw_config["module_order"]
    if "modules" in raw_config:
        state.modules.update(raw_config["modules"])
    if "awtrix_ip" in raw_config:
        awtrix.host = str(raw_config["awtrix_ip"]).strip()

    is_live = (state.scheduler_state == "LIVE")
    for name, mod in _module_map.items():
        if state.modules.get(name, True) and hasattr(mod, "force_refresh"):
            mod.force_refresh()
    for name, mod in _module_map.items():
        if state.modules.get(name, True) and hasattr(mod, "tick"):
            mod.tick(awtrix, is_live=is_live)

    logger.info("[api] soft restart — config reloaded, all modules refreshed")
    return {"status": "ok"}


@app.post("/api/device/settings")
async def api_device_settings_save(request: Request):
    """Apply built-in app toggles to device and save to config."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    keys = ("TIM", "DAT", "TEMP", "HUM", "BAT")
    payload = {k: bool(data.get(k, True)) for k in keys}
    state.cfg["built_in_apps"] = payload
    _save_config(state.cfg)
    if awtrix.update_settings(payload):
        awtrix.reboot()  # Built-in app changes require reboot
        logger.info(f"[api] device settings applied, reboot sent: {payload}")
        return {"status": "saved", "applied_to_device": True}
    logger.warning("[api] device settings saved to config but device update failed")
    return {"status": "saved", "applied_to_device": False}


# ── Pinned message ────────────────────────────────────────────────────────────

@app.post("/api/pinned")
async def save_pinned(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    text = str(data.get("text", "")).strip()
    color = str(data.get("color", "#FFFFFF")).strip()

    state.cfg["pinned"] = {"text": text, "color": color}
    app_colors = dict(state.cfg.get("app_colors", {}))
    app_colors["pinned"] = color
    state.cfg["app_colors"] = app_colors
    _save_config(state.cfg)

    if text and state.modules.get("pinned", True):
        pinned.tick(awtrix, is_live=(state.scheduler_state == "LIVE"))
    else:
        pinned.clear(awtrix)

    logger.info(f"[api] pinned message updated: '{text[:60]}'")
    return {"status": "saved"}


@app.delete("/api/pinned")
def clear_pinned():
    state.cfg["pinned"] = {"text": "", "color": "#FFFFFF"}
    _save_config(state.cfg)
    pinned.clear(awtrix)
    logger.info("[api] pinned message cleared")
    return {"status": "cleared"}


# ── Quick notify (ephemeral overlay) ──────────────────────────────────────────

class NotifyRequest(BaseModel):
    text: str
    duration: int = 5

@app.post("/api/notify")
def api_notify(req: NotifyRequest):
    secs = max(1, min(req.duration, 300))
    try:
        resp = awtrix.notify({"text": req.text.strip(), "duration": secs})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    logger.info(f"[api] quick notify ({secs}s): '{req.text}'")
    return {"status": "sent"}


# ── Module order ──────────────────────────────────────────────────────────────
# Defined before {name} routes so FastAPI matches "order" literally

@app.post("/api/modules/order")
async def save_module_order(request: Request):
    try:
        order = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(order, list):
        raise HTTPException(status_code=400, detail="Expected a list")

    state.module_order = order
    state.cfg["module_order"] = order
    try:
        _save_config(state.cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save: {e}")

    logger.info(f"[api] module order updated: {order}")
    return {"status": "saved"}


# ── Module toggles ────────────────────────────────────────────────────────────

@app.post("/api/modules/{name}/toggle")
def api_toggle_module(name: str):
    if name not in state.modules:
        raise HTTPException(status_code=404, detail=f"Module '{name}' not found")
    state.modules[name] = not state.modules[name]
    enabled = state.modules[name]
    if not enabled:
        try:
            awtrix.delete_app(name)
            state.active_apps.pop(name, None)
        except Exception:
            pass
    else:
        mod = _module_map.get(name)
        if mod and hasattr(mod, 'restore'):
            try:
                mod.restore(awtrix)
            except Exception:
                pass

    state.cfg["modules"] = dict(state.modules)
    try:
        _save_config(state.cfg)
    except Exception as e:
        logger.error(f"[api] failed to persist module toggle: {e}")

    logger.info(f"[api] module '{name}' → {'enabled' if enabled else 'disabled'}")
    return {"module": name, "enabled": enabled}


# ── Module refresh ────────────────────────────────────────────────────────────

@app.post("/api/modules/{name}/refresh")
async def api_refresh_module(name: str):
    if name not in state.modules:
        raise HTTPException(status_code=404, detail=f"Module '{name}' not found")
    if not state.modules[name]:
        raise HTTPException(status_code=400, detail=f"Module '{name}' is disabled")

    is_live = (state.scheduler_state == "LIVE")

    if name == "valorant_live":
        matches = await fetch_live()
        if state.modules.get(name, True):
            push_live(awtrix, matches)
    else:
        mod = _module_map.get(name)
        if mod:
            if hasattr(mod, 'force_refresh'):
                mod.force_refresh()
            if hasattr(mod, 'tick'):
                mod.tick(awtrix, is_live=is_live)

    logger.info(f"[api] module '{name}' manually refreshed")
    return {"status": "refreshed", "module": name}


# ── Countdown CRUD ────────────────────────────────────────────────────────

@app.post("/api/countdowns")
async def add_countdown(request: Request):
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not event.get("name") or not event.get("date"):
        raise HTTPException(status_code=400, detail="name and date required")

    events = state.cfg.setdefault("countdowns", {}).setdefault("events", [])
    events.append({"name": event["name"], "date": event["date"]})
    _save_config(state.cfg)
    countdowns.force_refresh()
    countdowns.tick(awtrix, is_live=(state.scheduler_state == "LIVE"))
    logger.info(f"[api] countdown added: {event['name']} → {event['date']}")
    return {"status": "added"}


@app.delete("/api/countdowns/{idx}")
def delete_countdown(idx: int):
    events = state.cfg.get("countdowns", {}).get("events", [])
    if idx < 0 or idx >= len(events):
        raise HTTPException(status_code=404, detail="Countdown not found")
    removed = events.pop(idx)
    _save_config(state.cfg)
    countdowns.force_refresh()
    countdowns.tick(awtrix, is_live=(state.scheduler_state == "LIVE"))
    logger.info(f"[api] countdown removed: {removed.get('name')}")
    return {"status": "removed"}


# ── Timer ───────────────────────────────────────────────────────────────────

@app.post("/api/timer/start")
async def api_timer_start(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    seconds = data.get("seconds")
    preset_id = data.get("preset_id")
    name = data.get("name", "Timer")
    chime_sound = data.get("chime_sound")
    chime_enabled = data.get("chime_enabled")

    if seconds is not None:
        seconds = int(seconds)
    elif preset_id is not None:
        presets = timer.get_presets()
        idx = int(preset_id) if isinstance(preset_id, (int, str)) and str(preset_id).isdigit() else -1
        if 0 <= idx < len(presets):
            p = presets[idx]
            seconds = p.get("seconds", 300)
            if not name or name == "Timer":
                name = p.get("name", "Timer")
        else:
            raise HTTPException(status_code=400, detail="Invalid preset_id")
    else:
        raise HTTPException(status_code=400, detail="Provide seconds or preset_id")

    if not seconds or seconds < 1:
        raise HTTPException(status_code=400, detail="Duration must be at least 1 second")

    tid = timer.start_timer(seconds=seconds, name=name, chime_sound=chime_sound, chime_enabled=chime_enabled)
    logger.info(f"[api] timer started: {name} {seconds}s (id={tid})")
    return {"status": "started", "timer_id": tid, "seconds": seconds, "name": name}


@app.post("/api/timer/stop")
async def api_timer_stop(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    timer_id = data.get("timer_id")
    if not timer_id:
        raise HTTPException(status_code=400, detail="timer_id required")
    if timer.stop_timer(timer_id):
        return {"status": "stopped", "timer_id": timer_id}
    raise HTTPException(status_code=404, detail="Timer not found")


# ── Twitch channels ───────────────────────────────────────────────────────

@app.post("/api/twitch/channels")
async def save_twitch_channels(request: Request):
    try:
        channels = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(channels, list):
        raise HTTPException(status_code=400, detail="Expected a list")

    state.cfg.setdefault("twitch", {})["channels"] = channels
    _save_config(state.cfg)
    twitch_live.force_refresh()
    twitch_live.tick(awtrix, is_live=(state.scheduler_state == "LIVE"))
    logger.info(f"[api] twitch channels updated: {channels}")
    return {"status": "saved"}


# ── Misc ──────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/test")
def test_connection():
    try:
        resp = awtrix.notify({"text": "Hello from NAS", "duration": 5})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "sent", "awtrix_response": resp.status_code}
