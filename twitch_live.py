"""
Twitch Live module — fires a "going live" alert when watched channels go live.
Shows an alert app for `alert_duration_minutes` (default 10) then auto-expires.
Only triggers once per live session — re-alerts when the streamer goes offline
and comes back live. A brief overlay notification is also fired at the moment
of detection.
"""

import os
import httpx
import logging
from datetime import datetime, timedelta

import state

logger = logging.getLogger(__name__)

APP_NAME = "twitch_live"
_POLL_INTERVAL = 120

DEFAULT_CHANNELS = [
    "valorant",
    "valorant_esports",
    "valorant_americas",
    "valorant_pacific",
    "valorant_emea",
    "valorant_cn",
]

_access_token: str | None = None
_token_expires_at: datetime = datetime.min
_last_fetch: datetime = datetime.min
_known_live: set[str] = set()   # channel logins currently known to be live


# ── Config helpers ────────────────────────────────────────────────────────────

def _tcfg() -> dict:
    return state.cfg.get("twitch", {})

def _channels() -> list[str]:
    ch = _tcfg().get("channels", DEFAULT_CHANNELS)
    return [c.strip().lower() for c in ch if c.strip()]

def _alert_lifetime() -> int:
    return int(_tcfg().get("alert_duration_minutes", 10)) * 60


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_token() -> str | None:
    global _access_token, _token_expires_at

    now = datetime.now()
    if _access_token and now < _token_expires_at:
        return _access_token

    client_id     = os.environ.get("TWITCH_CLIENT_ID", "")
    client_secret = os.environ.get("TWITCH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        logger.warning("[twitch] TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET not set in environment")
        return None

    try:
        resp = httpx.post("https://id.twitch.tv/oauth2/token", data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "client_credentials",
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _access_token     = data["access_token"]
        _token_expires_at = now + timedelta(seconds=data.get("expires_in", 3600) - 300)
        logger.info("[twitch] obtained access token")
        return _access_token
    except Exception as e:
        logger.error(f"[twitch] token fetch failed: {e}")
        return None


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_live() -> list[dict]:
    token = _get_token()
    if not token:
        return []

    channels = _channels()
    if not channels:
        return []

    client_id = os.environ.get("TWITCH_CLIENT_ID", "")
    params    = "&".join(f"user_login={ch}" for ch in channels)
    url       = f"https://api.twitch.tv/helix/streams?{params}"

    try:
        resp = httpx.get(url, headers={
            "Client-ID":     client_id,
            "Authorization": f"Bearer {token}",
        }, timeout=10)
        resp.raise_for_status()
        streams = resp.json().get("data", [])
        logger.info(f"[twitch] {len(streams)} live stream(s) from {len(channels)} channels")
        return streams
    except Exception as e:
        logger.error(f"[twitch] streams fetch failed: {e}")
        return []


# ── Formatting ────────────────────────────────────────────────────────────────

def _format_alert(stream: dict) -> str:
    name    = stream.get("user_name", "???")
    title   = stream.get("title", "").strip()
    viewers = stream.get("viewer_count", 0)
    if len(title) > 60:
        title = title[:57] + "..."
    return f"▶ {name} LIVE ({viewers:,}) — {title}" if title else f"▶ {name} LIVE ({viewers:,})"


# ── Alert push ────────────────────────────────────────────────────────────────

def _push_alert(awtrix, streams: list[dict], lifetime: int = None, notify: bool = True) -> None:
    if lifetime is None:
        lifetime = _alert_lifetime()
    text    = "   ||   ".join(_format_alert(s) for s in streams)
    scroll_spd, dur = state.scroll_params_for_text(text)
    payload = {
        "text":        text,
        "color":       state.get_app_color(APP_NAME),
        "scrollSpeed": scroll_spd,
        "lifetime":    lifetime,
        "duration":   dur,
        "repeat":     1,
    }
    try:
        resp = awtrix.push_app(APP_NAME, payload)
        preview  = text[:120] + ("…" if len(text) > 120 else "")
        existing = state.active_apps.get(APP_NAME, {})
        state.active_apps[APP_NAME] = {
            "text":         preview,
            "color":        state.get_app_color(APP_NAME),
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            # Preserve the original expiry so refreshes don't extend the window
            "_expires_at":  existing.get("_expires_at") or (datetime.now() + timedelta(seconds=lifetime)),
        }
        names = [s.get("user_name") for s in streams]
        logger.info(f"[twitch] alert pushed for {names} (lifetime {lifetime}s) → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[twitch] alert push failed: {e}")

    if notify:
        try:
            names_str = ", ".join(s.get("user_name", "?") for s in streams)
            awtrix.notify({"text": f"▶ {names_str} LIVE", "duration": 5})
        except Exception as e:
            logger.error(f"[twitch] notify failed: {e}")


# ── Public interface ──────────────────────────────────────────────────────────

def tick(awtrix, is_live: bool) -> None:
    global _last_fetch, _known_live

    # Expire dashboard row once the alert window has passed
    entry = state.active_apps.get(APP_NAME)
    if entry and datetime.now() >= entry.get("_expires_at", datetime.max):
        state.active_apps.pop(APP_NAME, None)

    now = datetime.now()
    if (now - _last_fetch).total_seconds() < _POLL_INTERVAL:
        return

    streams    = _fetch_live()
    _last_fetch = now

    current_live      = {s.get("user_login", "").lower() for s in streams if s.get("user_login")}
    newly_live_logins = current_live - _known_live
    went_offline      = _known_live - current_live

    # Keep known set in sync
    _known_live.update(newly_live_logins)
    _known_live.difference_update(went_offline)
    if went_offline:
        logger.info(f"[twitch] went offline: {went_offline}")

    if newly_live_logins:
        newly_live_streams = [s for s in streams if s.get("user_login", "").lower() in newly_live_logins]
        logger.info(f"[twitch] newly live: {newly_live_logins}")

        if not is_live:
            # Push alert app + overlay notification
            _push_alert(awtrix, newly_live_streams)
        else:
            # Valorant match is live — skip the persistent app but still fire overlay beep
            try:
                names_str = ", ".join(s.get("user_name", "?") for s in newly_live_streams)
                awtrix.notify({"text": f"▶ {names_str} LIVE", "duration": 5})
                logger.info(f"[twitch] notified during valorant live: {names_str}")
            except Exception as e:
                logger.error(f"[twitch] notify failed: {e}")
        return

    # Refresh viewer counts for already-live channels while the alert window is still open
    entry = state.active_apps.get(APP_NAME)
    if entry and not is_live:
        remaining = int((entry["_expires_at"] - datetime.now()).total_seconds())
        if remaining > 0:
            still_live = [s for s in streams if s.get("user_login", "").lower() in _known_live]
            if still_live:
                _push_alert(awtrix, still_live, lifetime=remaining, notify=False)
                logger.info(f"[twitch] refreshed viewer counts ({remaining}s remaining)")


def force_refresh() -> None:
    """Reset poll timer and clear known-live set so current streams re-alert."""
    global _last_fetch, _known_live
    _last_fetch = datetime.min
    _known_live.clear()


def clear(awtrix) -> None:
    try:
        awtrix.delete_app(APP_NAME)
    except Exception as e:
        logger.error(f"[twitch] clear delete_app failed: {e}")
    state.active_apps.pop(APP_NAME, None)


def restore(awtrix) -> None:
    # Alert app manages its own lifetime — nothing to restore
    pass
