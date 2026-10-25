"""End-to-end: a fake HA WebSocket server feeds _session; pop-ups must reach awtrix.notify."""
import asyncio
import json
import pathlib

import pytest
import websockets
from websockets.asyncio.server import serve

import ha
import ha_events

EXAMPLE = json.loads((pathlib.Path(__file__).parent.parent / "config.example.json").read_text())


class FakeAwtrix:
    def __init__(self):
        self.sent = []

    def notify(self, payload):
        self.sent.append(payload)


def _light(state, brightness=None):
    attrs = {"friendly_name": "Surya Bedroom Downlights"}
    if brightness is not None:
        attrs["brightness"] = brightness
    return {"entity_id": "light.surya_bedroom_downlights", "state": state, "attributes": attrs}


def _event(old, new):
    return {"id": 1, "type": "event", "event": {
        "event_type": "state_changed",
        "data": {"entity_id": new["entity_id"], "old_state": old, "new_state": new},
        "origin": "LOCAL", "time_fired": "2026-10-25T14:41:00+00:00"}}


async def _run(events, cfg, monkeypatch, wait=1.2):
    async def handler(ws):
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.10.0"}))
        assert json.loads(await ws.recv())["type"] == "auth"
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.10.0"}))
        for i in (1, 2):
            sub = json.loads(await ws.recv())
            await ws.send(json.dumps({"id": sub["id"], "type": "result", "success": True, "result": None}))
        for ev in events:
            await ws.send(json.dumps(ev))
        await asyncio.sleep(wait + 1)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("HA_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("HA_TOKEN", "tok")
        monkeypatch.setattr(ha, "get_state", lambda eid: {"state": "off", "attributes": {}})
        awtrix = FakeAwtrix()
        engine = ha_events.EventEngine(awtrix)
        task = asyncio.create_task(ha_events._session(engine))
        await asyncio.sleep(wait)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return awtrix.sent


def test_light_on_off_events_become_popups(monkeypatch, cfg):
    cfg["ha_events"] = EXAMPLE["ha_events"]
    events = [_event(_light("off"), _light("on", 255))]
    sent = asyncio.run(_run(events, cfg, monkeypatch))
    assert [p["text"] for p in sent] == ["Surya Bedroom Downlights ON"]
