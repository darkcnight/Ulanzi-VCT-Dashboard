import state
import weather


def _fake_ha(monkeypatch, objs):
    monkeypatch.setattr(weather.ha, "get_state", lambda eid: objs.get(eid))


def test_fetch_builds_data_from_ha(monkeypatch, cfg):
    cfg["ha"] = {"weather_entity": "weather.w", "rain_entity": "sensor.r"}
    _fake_ha(monkeypatch, {
        "weather.w": {"state": "rainy", "attributes": {"temperature": 28.64}},
        "sensor.r": {"state": "0.4", "attributes": {}},
    })
    assert weather._fetch() == {"temp": 28.6, "label": "Rain", "color": "#0288D1", "rain": 0.4}


def test_fetch_uses_default_entities(monkeypatch, cfg):
    asked = []

    def fake(eid):
        asked.append(eid)
        return None

    monkeypatch.setattr(weather.ha, "get_state", fake)
    assert weather._fetch() is None
    assert asked == ["weather.singapore_weather"]


def test_fetch_returns_none_when_weather_unavailable(monkeypatch, cfg):
    _fake_ha(monkeypatch, {"weather.singapore_weather": {"state": "unavailable", "attributes": {}}})
    assert weather._fetch() is None


def test_fetch_returns_none_without_temperature(monkeypatch, cfg):
    _fake_ha(monkeypatch, {"weather.singapore_weather": {"state": "cloudy", "attributes": {}}})
    assert weather._fetch() is None


def test_fetch_survives_missing_rain_sensor(monkeypatch, cfg):
    _fake_ha(monkeypatch, {"weather.singapore_weather": {"state": "cloudy", "attributes": {"temperature": 30}}})
    data = weather._fetch()
    assert data["rain"] is None and data["label"] == "Cloudy"


def test_unknown_condition_gets_readable_label(monkeypatch, cfg):
    _fake_ha(monkeypatch, {"weather.singapore_weather": {"state": "hot-and-humid", "attributes": {"temperature": 33}}})
    assert weather._fetch()["label"] == "Hot And Humid"


def test_build_text_with_and_without_rain(monkeypatch):
    monkeypatch.setattr(state, "device_stats", {})
    base = {"temp": 31.0, "label": "Cloudy", "color": "#9E9E9E"}
    assert weather._build_text({**base, "rain": 0.4}) == "31.0°C Cloudy  |  Rain 0.4mm"
    assert weather._build_text({**base, "rain": 0}) == "31.0°C Cloudy"
    assert weather._build_text({**base, "rain": None}) == "31.0°C Cloudy"


def test_build_text_adds_room_suffix(monkeypatch, cfg):
    monkeypatch.setattr(state, "device_stats", {"temp": 24.0, "hum": 61})
    text = weather._build_text({"temp": 31.0, "label": "Cloudy", "color": "#9E9E9E", "rain": None})
    assert text == "31.0°C Cloudy  |  ⌂ 24.0°C 61%"
