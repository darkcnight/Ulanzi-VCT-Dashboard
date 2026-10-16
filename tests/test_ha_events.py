import pytest

import ha_events
import state


class FakeAwtrix:
    def __init__(self):
        self.sent = []

    def notify(self, payload):
        self.sent.append(payload)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def sc(entity, old, new, old_attrs=None, new_attrs=None):
    """A HA state_changed event."""
    return {
        "event_type": "state_changed",
        "data": {
            "entity_id": entity,
            "old_state": None if old is None else {"state": old, "attributes": old_attrs or {}},
            "new_state": {"state": new, "attributes": new_attrs or {}},
        },
    }


LIGHTS = {
    "name": "lights", "type": "state", "entity": "light.l",
    "states": {"on": {"text": "Lights ON", "color": "#FFD700"},
               "off": {"text": "Lights OFF", "color": "#888888"}},
}


@pytest.fixture
def env(cfg):
    cfg["ha_events"] = {"min_gap_seconds": 3, "during_live_match": True, "rules": [dict(LIGHTS)]}
    monkey_state = state.scheduler_state
    state.scheduler_state = "IDLE"
    clock = Clock()
    awtrix = FakeAwtrix()
    yield ha_events.EventEngine(awtrix, clock=clock), awtrix, clock, cfg["ha_events"]
    state.scheduler_state = monkey_state


def test_state_rule_fires_and_sends_payload(env):
    engine, awtrix, _, _ = env
    engine.handle(sc("light.l", "off", "on"))
    assert engine.has_work()
    engine.flush()
    assert awtrix.sent == [{"text": "Lights ON", "color": "#FFD700", "duration": 5}]
    assert not engine.has_work()


def test_unlisted_state_and_unrelated_entity_do_nothing(env):
    engine, awtrix, _, _ = env
    engine.handle(sc("light.l", "on", "weird"))
    engine.handle(sc("light.other", "off", "on"))
    assert not engine.has_work()


def test_same_state_attribute_change_does_not_fire_state_rule(env):
    engine, _, _, _ = env
    engine.handle(sc("light.l", "on", "on", {"brightness": 10}, {"brightness": 20}))
    assert not engine.has_work()


@pytest.mark.parametrize("old", [None, "unavailable", "unknown"])
def test_changes_from_missing_or_unusable_are_ignored(env, old):
    engine, _, _, _ = env
    engine.handle(sc("light.l", old, "on"))
    assert not engine.has_work()


def test_change_to_unavailable_is_ignored(env):
    engine, _, _, _ = env
    engine.handle(sc("light.l", "on", "unavailable"))
    assert not engine.has_work()


def test_fire_from_unknown_flag(env):
    engine, awtrix, _, conf = env
    conf["rules"][0]["fire_from_unknown"] = True
    engine.handle(sc("light.l", "unknown", "on"))
    engine.flush()
    assert awtrix.sent[0]["text"] == "Lights ON"


def test_min_gap_between_popups(env):
    engine, awtrix, clock, _ = env
    engine.handle(sc("light.l", "off", "on"))
    engine.handle(sc("light.l", "on", "off"))
    engine.flush()
    assert [p["text"] for p in awtrix.sent] == ["Lights ON"]
    clock.t += 2.9
    engine.flush()
    assert len(awtrix.sent) == 1
    clock.t += 0.2
    engine.flush()
    assert [p["text"] for p in awtrix.sent] == ["Lights ON", "Lights OFF"]


def test_queue_keeps_only_three_newest(env):
    engine, awtrix, clock, conf = env
    conf["min_gap_seconds"] = 0
    conf["rules"][0]["states"] = {s: {"text": s, "color": "#FFFFFF"} for s in "abcde"}
    prev = "z"
    for s in "abcde":
        engine.handle(sc("light.l", prev, s))
        prev = s
    while engine.has_work():
        engine.flush()
    assert [p["text"] for p in awtrix.sent] == ["c", "d", "e"]


def test_any_spec_icon_hold_and_duration(env):
    engine, awtrix, _, conf = env
    conf["rules"] = [{
        "name": "bell", "type": "state", "entity": "event.bell", "fire_from_unknown": True,
        "any": {"text": "Doorbell", "color": "#FF0000", "icon": "bell", "hold": True, "duration": 9},
    }]
    engine.handle(sc("event.bell", "unknown", "2026-10-16T10:00:00+00:00"))
    engine.flush()
    assert awtrix.sent == [{"text": "Doorbell", "color": "#FF0000", "duration": 9, "icon": "bell", "hold": True}]


def test_text_placeholders(env):
    engine, awtrix, _, conf = env
    conf["rules"] = [{
        "name": "ac", "type": "state", "entity": "climate.ac",
        "states": {"cool": {"text": "AC {state} {attr.temperature} {attr.missing}", "color": "#4FC3F7"}},
    }]
    engine.handle(sc("climate.ac", "off", "cool", new_attrs={"temperature": 24}))
    engine.flush()
    assert awtrix.sent[0]["text"] == "AC cool 24"


def test_cooldown(env):
    engine, awtrix, clock, conf = env
    conf["min_gap_seconds"] = 0
    conf["rules"][0]["cooldown_seconds"] = 10
    engine.handle(sc("light.l", "off", "on"))
    clock.t += 1
    engine.handle(sc("light.l", "on", "off"))
    clock.t += 11
    engine.handle(sc("light.l", "off", "on"))
    while engine.has_work():
        engine.flush()
    assert [p["text"] for p in awtrix.sent] == ["Lights ON", "Lights ON"]


def test_dropped_during_live_match_when_configured(env):
    engine, awtrix, _, conf = env
    conf["during_live_match"] = False
    state.scheduler_state = "LIVE"
    engine.handle(sc("light.l", "off", "on"))
    assert not engine.has_work()
    state.scheduler_state = "IDLE"
    engine.handle(sc("light.l", "on", "off"))
    assert engine.has_work()


def test_disabled_rules_are_skipped_and_enabled_reflects_rules(env):
    engine, _, _, conf = env
    conf["rules"][0]["enabled"] = False
    engine.handle(sc("light.l", "off", "on"))
    assert not engine.has_work()
    assert not engine.enabled()
    conf["rules"][0]["enabled"] = True
    assert engine.enabled()


def test_notify_failure_is_swallowed(env):
    engine, awtrix, _, _ = env

    def boom(payload):
        raise RuntimeError("clock offline")

    awtrix.notify = boom
    engine.handle(sc("light.l", "off", "on"))
    engine.flush()
    assert not engine.has_work()
