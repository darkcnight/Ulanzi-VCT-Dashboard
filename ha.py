"""
Home Assistant REST client. URL and long-lived token come from .env
(HA_URL, HA_TOKEN), read at call time. All failures return None and are logged;
callers keep their cached values.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://192.168.18.186:8123"
UNUSABLE = frozenset({"unavailable", "unknown"})
_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def base_url() -> str:
    return os.environ.get("HA_URL", DEFAULT_URL).strip().rstrip("/")


def token() -> str:
    return os.environ.get("HA_TOKEN", "").strip()


def get_state(entity_id: str) -> dict | None:
    """Return HA's state object for entity_id, or None on any failure."""
    if not _ENTITY_RE.match(entity_id or ""):
        logger.warning(f"[ha] rejected malformed entity id {entity_id!r}")
        return None
    tok = token()
    if not tok:
        logger.warning("[ha] HA_TOKEN is not set in .env")
        return None
    try:
        resp = httpx.get(
            f"{base_url()}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"[ha] {entity_id}: request failed: {e}")
        return None
    if resp.status_code == 401:
        logger.error("[ha] token rejected (401) — check HA_TOKEN in .env")
        return None
    if resp.status_code == 404:
        logger.warning(f"[ha] unknown entity {entity_id}")
        return None
    if resp.status_code != 200:
        logger.warning(f"[ha] {entity_id}: HTTP {resp.status_code}")
        return None
    return resp.json()


def usable(obj: dict | None) -> bool:
    return obj is not None and obj.get("state") not in UNUSABLE


def numeric(obj: dict | None) -> float | None:
    if not usable(obj):
        return None
    try:
        return float(obj["state"])
    except (TypeError, ValueError):
        return None
