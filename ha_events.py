"""
Live Home Assistant event feed → AWTRIX pop-ups (/api/notify).

EventEngine is pure and clock-injectable: handle() takes HA events and queues
pop-ups, flush() releases at most one due pop-up. The WebSocket loop that feeds
it (run_event_stream) is at the bottom of the file. Rules come from
state.cfg["ha_events"] at call time.
"""

import logging
import re
import time
from collections import deque

import state
from ha import UNUSABLE

logger = logging.getLogger(__name__)

MAX_QUEUE = 3
DEFAULT_DURATION = 5
DEFAULT_COLOR = "#FFFFFF"

_PLACEHOLDER = re.compile(r"\{(value|state|attr\.[A-Za-z0-9_]+)\}")


def _render(text: str, new_state: dict, value=None) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key == "value":
            return str(value)
        if key == "state":
            return str(new_state["state"])
        attr = new_state.get("attributes", {}).get(key[5:])
        return "" if attr is None else str(attr)

    return _PLACEHOLDER.sub(sub, text).strip()


class EventEngine:
    def __init__(self, awtrix, clock=time.monotonic):
        self.awtrix = awtrix
        self.clock = clock
        self.connected = False
        self._queue: deque[dict] = deque(maxlen=MAX_QUEUE)
        self._last_emit = float("-inf")
        self._last_fired: dict[str, float] = {}

    # ── Config ────────────────────────────────────────────────────────────────

    def _cfg(self) -> dict:
        return state.cfg.get("ha_events", {})

    def _rules(self) -> list[dict]:
        return [r for r in self._cfg().get("rules", []) if r.get("enabled", True)]

    def enabled(self) -> bool:
        return bool(self._rules())

    # ── Intake ────────────────────────────────────────────────────────────────

    def handle(self, event: dict) -> None:
        if event.get("event_type") == "state_changed":
            self._on_state_changed(event.get("data", {}))

    def _on_state_changed(self, data: dict) -> None:
        entity = data.get("entity_id")
        old, new = data.get("old_state"), data.get("new_state")
        if not new:
            return
        for rule in self._rules():
            if rule.get("entity") != entity:
                continue
            if rule.get("type") == "state":
                self._on_state_rule(rule, old, new)

    @staticmethod
    def _from_ok(rule: dict, old: dict | None) -> bool:
        if old is None:
            return False
        if old["state"] == "unknown" and rule.get("fire_from_unknown"):
            return True
        return old["state"] not in UNUSABLE

    def _on_state_rule(self, rule: dict, old: dict | None, new: dict) -> None:
        if new["state"] in UNUSABLE or not self._from_ok(rule, old):
            return
        if new["state"] == old["state"]:
            return
        spec = rule.get("states", {}).get(new["state"]) or rule.get("any")
        if spec:
            self._enqueue(rule, spec, new)

    # ── Queue ─────────────────────────────────────────────────────────────────

    def _allowed(self) -> bool:
        live = state.scheduler_state == "LIVE"
        return not (live and not self._cfg().get("during_live_match", True))

    def _enqueue(self, rule: dict, spec: dict, new_state: dict, value=None) -> None:
        if not self._allowed():
            return
        now = self.clock()
        cooldown = float(rule.get("cooldown_seconds", 0))
        if cooldown and now - self._last_fired.get(rule["name"], float("-inf")) < cooldown:
            return
        self._last_fired[rule["name"]] = now
        payload = {
            "text": _render(spec.get("text", ""), new_state, value),
            "color": spec.get("color", DEFAULT_COLOR),
            "duration": int(spec.get("duration", DEFAULT_DURATION)),
        }
        if spec.get("icon"):
            payload["icon"] = spec["icon"]
        if spec.get("hold"):
            payload["hold"] = True
        self._queue.append(payload)

    def has_work(self) -> bool:
        return bool(self._queue)

    def flush(self) -> None:
        now = self.clock()
        gap = float(self._cfg().get("min_gap_seconds", 3))
        if self._queue and now - self._last_emit >= gap:
            payload = self._queue.popleft()
            self._last_emit = now
            try:
                self.awtrix.notify(payload)
                logger.info(f"[ha_events] pop-up: {payload['text']}")
            except Exception as e:
                logger.warning(f"[ha_events] notify failed: {e}")
