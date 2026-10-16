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


LEVEL = {
    "name": "level", "type": "value", "entity": "light.l", "attribute": "brightness",
    "scale": "percent255", "text": "Lights {value}%", "color": "#FFD700",
    "settle_seconds": 1.5, "suppress_while": "input_boolean.sunrise",
}


def adj(old_b, new_b, state_="on"):
    return sc("light.l", state_, state_, {"brightness": old_b}, {"brightness": new_b})


def test_value_rule_debounces_to_one_popup_with_final_value(env):
    engine, awtrix, clock, conf = env
    conf["rules"] = [dict(LEVEL)]
    engine.handle(adj(10, 51))
    clock.t += 1.0
    engine.handle(adj(51, 102))
    clock.t += 1.0
    engine.handle(adj(102, 128))
    clock.t += 1.4          # 1.4 s after the last change: not settled yet
    engine.flush()
    assert awtrix.sent == []
    clock.t += 0.2          # now 1.6 s after the last change
    engine.flush()
    assert awtrix.sent == [{"text": "Lights 50%", "color": "#FFD700", "duration": 5}]


def test_value_rule_ignores_unchanged_missing_and_state_changes(env):
    engine, awtrix, clock, conf = env
    conf["rules"] = [dict(LEVEL)]
    engine.handle(adj(10, 10))
    engine.handle(sc("light.l", "on", "on", {"brightness": 10}, {}))
    engine.handle(sc("light.l", "off", "on", {"brightness": None}, {"brightness": 26}))
    clock.t += 5
    engine.flush()
    assert awtrix.sent == []


def test_value_rule_raw_value_without_scale(env):
    engine, awtrix, clock, conf = env
    conf["rules"] = [{**LEVEL, "attribute": "color_temp_kelvin", "scale": None, "text": "{value}K", "suppress_while": None}]
    engine.handle(sc("light.l", "on", "on", {"color_temp_kelvin": 2000}, {"color_temp_kelvin": 2700}))
    clock.t += 2
    engine.flush()
    assert awtrix.sent[0]["text"] == "2700K"


def test_suppress_while_gate_blocks_value_popups(env):
    engine, awtrix, clock, conf = env
    conf["rules"] = [dict(LEVEL)]
    engine.handle(sc("input_boolean.sunrise", "off", "on"))
    engine.handle(adj(10, 51))
    clock.t += 2
    engine.flush()
    assert awtrix.sent == []
    engine.handle(sc("input_boolean.sunrise", "on", "off"))
    engine.handle(adj(51, 102))
    clock.t += 2
    engine.flush()
    assert [p["text"] for p in awtrix.sent] == ["Lights 40%"]


def test_seed_gates_reads_current_gate_state(env, monkeypatch):
    engine, awtrix, clock, conf = env
    conf["rules"] = [dict(LEVEL)]
    monkeypatch.setattr(ha_events.ha, "get_state", lambda eid: {"state": "on", "attributes": {}})
    engine.seed_gates()
    engine.handle(adj(10, 51))
    clock.t += 2
    engine.flush()
    assert awtrix.sent == []


def test_automation_rule_fires_on_automation_triggered(env):
    engine, awtrix, _, conf = env
    conf["rules"] = [{"name": "sunrise", "type": "automation",
                      "entity": "automation.sunrise", "text": "Sunrise", "color": "#FF8C00"}]
    engine.handle({"event_type": "automation_triggered",
                   "data": {"entity_id": "automation.other", "name": "other"}})
    assert not engine.has_work()
    engine.handle({"event_type": "automation_triggered",
                   "data": {"entity_id": "automation.sunrise", "name": "Sunrise"}})
    engine.flush()
    assert awtrix.sent == [{"text": "Sunrise", "color": "#FF8C00", "duration": 5}]
