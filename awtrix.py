import logging
import httpx

import state

logger = logging.getLogger(__name__)


class AwtrixClient:
    def __init__(self, host: str):
        self.host = host

    @property
    def base_url(self) -> str:
        return f"http://{self.host}/api"

    def push_app(self, app_name: str, payload: dict) -> httpx.Response:
        if app_name in state.module_order:
            payload["pos"] = state.module_order.index(app_name)
        return httpx.post(f"{self.base_url}/custom?name={app_name}", json=payload, timeout=5)

    def delete_app(self, app_name: str) -> httpx.Response:
        return httpx.post(f"{self.base_url}/custom?name={app_name}", json={}, timeout=5)

    def notify(self, payload: dict) -> httpx.Response:
        return httpx.post(f"{self.base_url}/notify", json=payload, timeout=5)

    def get_stats(self) -> dict | None:
        """Fetch /api/stats; returns parsed dict or None on failure."""
        try:
            resp = httpx.get(f"{self.base_url}/stats", timeout=3)
            if resp.status_code < 500:
                return resp.json()
            return None
        except Exception:
            return None

    def set_brightness(self, level: int) -> bool:
        """Set display brightness (0–255) via /api/settings. Disables device ABRI so our value takes effect. Returns True on success."""
        try:
            resp = httpx.post(f"{self.base_url}/settings", json={"BRI": level, "ABRI": False}, timeout=3)
            if resp.status_code < 400:
                logger.info(f"[brightness] set to {level}")
                return True
            logger.warning(f"[brightness] request failed: HTTP {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"[brightness] request failed: {e}")
            return False

    def get_settings(self) -> dict | None:
        """Fetch device settings from /api/settings; returns parsed dict or None on failure."""
        try:
            resp = httpx.get(f"{self.base_url}/settings", timeout=5)
            if resp.status_code < 500:
                return resp.json()
            return None
        except Exception:
            return None

    def update_settings(self, payload: dict) -> bool:
        """POST payload to /api/settings. Returns True on success."""
        try:
            resp = httpx.post(f"{self.base_url}/settings", json=payload, timeout=5)
            return resp.status_code < 500
        except Exception:
            return False

    def reboot(self) -> bool:
        """POST to /api/reboot. Returns True on success."""
        try:
            resp = httpx.post(f"{self.base_url}/reboot", timeout=5)
            return resp.status_code < 500
        except Exception:
            return False

    def ping(self) -> bool:
        """Return True if the device responds to a stats request."""
        return self.get_stats() is not None
