"""The shipped config.example.json rules, driven with realistic HA events."""
import json
import pathlib

import ha_events
import state

RULES = json.loads((pathlib.Path(__file__).parent.parent / "config.example.json").read_text())["ha_events"]


class FakeAwtrix:
    def __init__(self):
        self.sent = []

    def notify(self, payload):
        self.sent.append(payload)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def ev(entity, old, new, old_attrs=None, new_attrs=None):
    return {"event_type": "state_changed", "data": {
        "entity_id": entity,
        "old_state": {"state": old, "attributes": old_attrs or {}},
        "new_state": {"state": new, "attributes": new_attrs or {}}}}


def texts(events, cfg):
    cfg["ha_events"] = RULES
    awtrix, clock = FakeAwtrix(), Clock()
    engine = ha_events.EventEngine(awtrix, clock=clock)
    for e in events:
        engine.handle(e)
    for _ in range(10):
        clock.t += 4
        engine.flush()
    return [p["text"] for p in awtrix.sent]


def test_downlights_use_their_own_name(cfg):
    n = {"friendly_name": "Surya Bedroom Downlights"}
    assert texts([ev("light.surya_bedroom_downlights", "off", "on", {}, n)], cfg) == ["Surya Bedroom Downlights ON"]
    assert texts([ev("light.surya_bedroom_downlights", "on", "off", n, n)], cfg) == ["Surya Bedroom Downlights OFF"]


def test_led_strip_uses_its_own_name(cfg):
    n = {"friendly_name": "Surya Bedroom LED Strip 01"}
    assert texts([ev("light.surya_bedroom_led_strip_01", "off", "on", {}, n)], cfg) == ["Surya Bedroom LED Strip 01 ON"]


def test_one_downlight_flip_is_one_popup_not_eight(cfg):
    """The real burst HA sent when the downlights were switched on (group, bulbs, room group)."""
    burst = [ev(f"light.surya_bedroom_downlight_0{i}", "off", "on", {}, {"friendly_name": f"Downlight {i}"})
             for i in range(1, 6)]
    burst += [ev("light.surya_bedroom_lights", "off", "on", {}, {"friendly_name": "Surya Bedroom Lights"}),
              ev("light.surya_bedroom_downlights", "off", "on", {}, {"friendly_name": "Surya Bedroom Downlights"})]
    assert texts(burst, cfg) == ["Surya Bedroom Downlights ON"]


def test_brightness_change_shows_name_and_percent(cfg):
    n = {"friendly_name": "Surya Bedroom Downlights"}
    e = ev("light.surya_bedroom_downlights", "on", "on", {**n, "brightness": 255}, {**n, "brightness": 128})
    assert texts([e], cfg) == ["Surya Bedroom Downlights 50%"]


def test_aircon_turning_on_shows_mode_temp_and_fan(cfg):
    e = ev("climate.surya_bedroom_aircon", "off", "cool", {}, {"temperature": 24, "fan_mode": "High"})
    assert texts([e], cfg) == ["AC cool 24 High"]
    off = ev("climate.surya_bedroom_aircon", "cool", "off", {}, {})
    assert texts([off], cfg) == ["AC off"]


def test_aircon_fan_and_temp_changes_announce(cfg):
    a, b = {"temperature": 24, "fan_mode": "High"}, {"temperature": 24, "fan_mode": "Low"}
    assert texts([ev("climate.surya_bedroom_aircon", "cool", "cool", a, b)], cfg) == ["AC fan Low"]
    c = {"temperature": 25.0, "fan_mode": "High"}
    assert texts([ev("climate.surya_bedroom_aircon", "cool", "cool", a, c)], cfg) == ["AC temp 25"]


def test_study_fan_on_speed_off(cfg):
    n = {"friendly_name": "Study Fan"}
    on = ev("fan.study_fan", "off", "on", {**n, "percentage": 0.0}, {**n, "percentage": 60.0})
    assert texts([on], cfg) == ["Study Fan ON 60%"]
    speed = ev("fan.study_fan", "on", "on", {**n, "percentage": 60.0}, {**n, "percentage": 100.0})
    assert texts([speed], cfg) == ["Study Fan 100%"]
    off = ev("fan.study_fan", "on", "off", {**n, "percentage": 100.0}, {**n, "percentage": 0.0})
    assert texts([off], cfg) == ["Study Fan OFF"]


def test_front_door_person_and_doorbell(cfg):
    person = ev("binary_sensor.front_door_person_occupancy", "off", "on")
    assert texts([person], cfg) == ["Someone at the door"]
    bell = ev("binary_sensor.front_door_visitor", "off", "on")
    assert texts([bell], cfg) == ["Doorbell"]
    cleared = ev("binary_sensor.front_door_person_occupancy", "on", "off")
    assert texts([cleared], cfg) == []


def test_door_person_flapping_is_rate_limited(cfg):
    cfg["ha_events"] = RULES
    awtrix, clock = FakeAwtrix(), Clock()
    engine = ha_events.EventEngine(awtrix, clock=clock)
    for _ in range(3):
        engine.handle(ev("binary_sensor.front_door_person_occupancy", "off", "on"))
        engine.handle(ev("binary_sensor.front_door_person_occupancy", "on", "off"))
        clock.t += 5
        engine.flush()
    assert len(awtrix.sent) == 1


def test_whole_room_group_alone_does_not_pop_up(cfg):
    n = {"friendly_name": "Surya Bedroom Lights"}
    assert texts([ev("light.surya_bedroom_lights", "off", "on", {}, n)], cfg) == []
