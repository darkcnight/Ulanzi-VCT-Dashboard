"""
Display-freeze watchdog.

Samples /api/screen on a short interval; if the frame never changes for
`freeze_seconds` the display is considered hung and the device is rebooted.
The scheduler can't do this itself (it polls every 300 s when idle, and
/api/stats stays healthy while the display is frozen).
"""

import asyncio
import hashlib
import logging
import time
from collections import deque

import state

logger = logging.getLogger(__name__)


class Watchdog:
    def __init__(self, clock=time.monotonic, freeze_seconds=90,
                 cooldown_seconds=600, max_per_hour=3):
        self.clock = clock
        self.freeze_seconds = freeze_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_per_hour = max_per_hour
        self._hash: str | None = None
        self._changed_at = clock()
        self._reboots: deque = deque()

    def step(self, frame: str | None) -> str | None:
        """Feed one screen sample (None = device unreachable). Returns 'reboot' or None."""
        now = self.clock()
        if frame is None:
            self._hash = None            # offline: can't judge, and can't reboot it anyway
            return None
        digest = hashlib.md5(frame.encode()).hexdigest()
        if digest != self._hash:
            self._hash, self._changed_at = digest, now
            return None
        if now - self._changed_at < self.freeze_seconds:
            return None
        while self._reboots and now - self._reboots[0] >= 3600:
            self._reboots.popleft()
        if self._reboots and now - self._reboots[-1] < self.cooldown_seconds:
            return None
        if len(self._reboots) >= self.max_per_hour:
            return None
        self._reboots.append(now)
        self._changed_at = now           # give the device a full window after rebooting
        return "reboot"


def _num(cfg: dict, key: str, default: float, lo: float, hi: float) -> float:
    """Read a numeric setting, falling back to `default` and clamping to [lo, hi]."""
    try:
        val = float(cfg.get(key, default))
    except (TypeError, ValueError):
        val = default
    return max(lo, min(val, hi))


async def run_watchdog(awtrix) -> None:
    cfg = state.cfg.get("watchdog", {})
    if not cfg.get("enabled", True):
        logger.info("[watchdog] disabled")
        return
    interval = _num(cfg, "check_interval_seconds", 10, 5, 600)
    wd = Watchdog(
        freeze_seconds=_num(cfg, "freeze_seconds", 90, 30, 3600),
        cooldown_seconds=_num(cfg, "cooldown_minutes", 10, 1, 1440) * 60,
        max_per_hour=int(_num(cfg, "max_reboots_per_hour", 3, 1, 6)),
    )
    logger.info(f"[watchdog] started (freeze={wd.freeze_seconds}s, interval={interval}s)")
    while True:
        await asyncio.sleep(interval)
        try:
            frame = await asyncio.to_thread(awtrix.get_screen)
            if wd.step(frame) == "reboot":
                ok = await asyncio.to_thread(awtrix.reboot)
                logger.warning(f"[watchdog] display frozen for {wd.freeze_seconds}s — reboot "
                               f"{'sent' if ok else 'FAILED'}")
                state.last_auto_reboot = time.strftime("%H:%M:%S")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[watchdog] tick failed")
