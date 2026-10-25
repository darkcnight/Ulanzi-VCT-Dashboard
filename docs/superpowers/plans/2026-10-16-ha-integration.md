# Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show HA weather on the clock instead of Open-Meteo, and show live pop-ups on the clock for events in Surya's bedroom (lights, automations, aircon) plus welcome home.

**Architecture:** A small REST client (`ha.py`) feeds the rewritten `weather.py`. A separate module (`ha_events.py`) holds a pure, clock-injectable rules engine (`EventEngine`) and an asyncio WebSocket loop that feeds it HA events; the engine sends AWTRIX `/api/notify` pop-ups. The loop is started in `main.py`'s lifespan next to the scheduler.

**Tech Stack:** Python 3.14 (venv), FastAPI, httpx (sync, like the other modules), `websockets` 15, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-ha-pull-module-design.md` (where the spec and this plan differ, this plan wins: it records decisions made after reading the code; see "Deviations from the spec").

## Global Constraints

- HA address and token come from `.env` as `HA_URL` (default `http://192.168.18.186:8123`) and `HA_TOKEN`. Never put the token in `config.json`, logs, tests or commits. `.env` is gitignored; never `git add` it.
- No quiet hours. Pop-ups show at any time of day.
- No fallback to Open-Meteo. Remove its code.
- Only Surya's bedroom events plus house-wide ones (welcome home; doorbell later).
- Group light entity only (`light.surya_bedroom_lights`), never the individual bulbs.
- Minimum gap between pop-ups: `min_gap_seconds` (default 3); at most 3 queued pop-ups, oldest dropped.
- HA entity IDs used (verified on live HA 2026.10.1 on 2026-10-16): `weather.singapore_weather` (state is an HA condition string such as `cloudy`; attribute `temperature` in °C), `sensor.singapore_weather_rainfall_s228`, `light.surya_bedroom_lights` (attributes `brightness` 0-255, `color_temp_kelvin`), `climate.surya_bedroom_aircon` (states `cool`, `dry`, `fan_only`, `off`; attribute `temperature`), `automation.surya_bedroom_sunrise_wake_up`, `automation.surya_bedroom_aircon_sleep_timer`, `person.surya`, `input_boolean.surya_sunrise_running`.
- Match the existing code style: module docstring, `logger = logging.getLogger(__name__)`, `[tag]` prefix in log messages, `state.cfg` read at call time.
- The working tree has an unrelated uncommitted change in `scheduler.py` (the user's). Never `git add -A` or `git commit -a`; always add the exact files named in each task.
- Commit messages end with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Run Python and tests with `venv/bin/python` from the repo root `/mnt/Speed/Projects/Ulanzi Clock`.

## Deviations from the spec

1. Weather entity names live under a new `ha` config key (`ha.weather_entity`, `ha.rain_entity`), not under `weather`. Reason: the settings page's save builds the whole `weather` block from its form fields, which would delete extra keys.
2. "Ignore the first event after connect" is replaced by: ignore any change whose old state is missing, `unavailable` or `unknown` (this is what an HA restart or device re-join looks like), unless the rule sets `"fire_from_unknown": true`.
3. The doorbell rules are not shipped (not even disabled): their entity IDs do not exist yet. The engine supports what they need (`"any"` spec, `"hold"`, `"fire_from_unknown"`), tested in Task 4.
4. During the aircon dry-out the pop-up says "AC fan" like any fan-only change; there is no separate "AC drying" text.
5. Added `suppress_while` on value rules, so the 30-minute sunrise ramp does not produce a "Lights N%" pop-up every minute.
6. `docker-compose.yml` gets an optional `env_file`. The TrueNAS compose already mounts `.env`.

## File Structure

- Create `ha.py`: REST client (`base_url`, `token`, `get_state`, `usable`, `numeric`). One responsibility: talk to HA.
- Create `ha_events.py`: `EventEngine` (rules, debounce, queue) and `run_event_stream` (WebSocket loop).
- Modify `weather.py`: read from HA; remove Open-Meteo.
- Modify `main.py`: start/stop the event stream task.
- Modify `templates/index.html`, `static/app.js`: remove latitude, longitude, location fields.
- Modify `config.example.json`, `.env.example`, `requirements.txt`, `docker/requirements-combined.txt`, `docker-compose.yml`, `README.md`, `INSTALLATION.md`.
- Create `requirements-dev.txt`, `tests/conftest.py`, `tests/test_ha.py`, `tests/test_weather.py`, `tests/test_ha_events.py`.
- Local only, not committed (gitignored): `config.json`, `.env`.

---

### Task 1: Test setup and the HA REST client

**Files:**
- Create: `requirements-dev.txt`, `tests/conftest.py`, `tests/test_ha.py`, `ha.py`
- Modify: `requirements.txt`, `docker/requirements-combined.txt`, `.env.example`

**Interfaces:**
- Produces (used by Tasks 2, 3, 5):
  - `ha.base_url() -> str` (no trailing slash)
  - `ha.token() -> str`
  - `ha.get_state(entity_id: str) -> dict | None` (HA state object `{"state": str, "attributes": dict, ...}`; `None` on any failure)
  - `ha.usable(obj: dict | None) -> bool` (True when obj exists and its state is not `unavailable`/`unknown`)
  - `ha.numeric(obj: dict | None) -> float | None`
  - `ha.UNUSABLE: frozenset[str]` = `{"unavailable", "unknown"}`
  - fixture `cfg` in `tests/conftest.py`: `cfg(dict)` replaces `state.cfg` contents for a test and restores them afterwards.

- [ ] **Step 1: Add dependencies and install them**

Append to `requirements.txt`:

```
websockets==15.0.1
```

Append to `docker/requirements-combined.txt`:

```
websockets==15.0.1
```

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest==8.3.4
```

Append to `.env.example`:

```

# Home Assistant (weather + live event pop-ups). Create a long-lived access token on your HA profile page.
HA_URL=http://192.168.18.186:8123
HA_TOKEN=
```

Run: `venv/bin/pip install -r requirements-dev.txt`
Expected: ends with "Successfully installed ... websockets-15.0.1 ... pytest-8.3.4" (or "already satisfied").

- [ ] **Step 2: Create the test scaffolding**

Create `tests/conftest.py`:

```python
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import state  # noqa: E402


@pytest.fixture
def cfg():
    """Replace state.cfg for one test; restore it afterwards."""
    saved = dict(state.cfg)
    state.cfg.clear()
    yield state.cfg
    state.cfg.clear()
    state.cfg.update(saved)
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_ha.py`:

```python
import ha


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_get_state_ok(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", "tok")
    monkeypatch.setenv("HA_URL", "http://ha.test:8123/")
    seen = {}

    def fake_get(url, headers, timeout):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        return FakeResp(200, {"state": "on", "attributes": {}})

    monkeypatch.setattr(ha.httpx, "get", fake_get)
    assert ha.get_state("light.x") == {"state": "on", "attributes": {}}
    assert seen == {"url": "http://ha.test:8123/api/states/light.x", "auth": "Bearer tok"}


def test_get_state_without_token_does_not_call_ha(monkeypatch):
    monkeypatch.delenv("HA_TOKEN", raising=False)

    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(ha.httpx, "get", boom)
    assert ha.get_state("light.x") is None


def test_get_state_401_404_500_and_exception_return_none(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", "tok")
    for status in (401, 404, 500):
        monkeypatch.setattr(ha.httpx, "get", lambda *a, _s=status, **k: FakeResp(_s))
        assert ha.get_state("light.x") is None

    def raises(*a, **k):
        raise ha.httpx.ConnectError("down")

    monkeypatch.setattr(ha.httpx, "get", raises)
    assert ha.get_state("light.x") is None


def test_usable_and_numeric():
    assert ha.usable({"state": "on", "attributes": {}})
    assert not ha.usable({"state": "unavailable", "attributes": {}})
    assert not ha.usable({"state": "unknown", "attributes": {}})
    assert not ha.usable(None)
    assert ha.numeric({"state": "0.4", "attributes": {}}) == 0.4
    assert ha.numeric({"state": "unavailable", "attributes": {}}) is None
    assert ha.numeric({"state": "abc", "attributes": {}}) is None
    assert ha.numeric(None) is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_ha.py -v`
Expected: collection ERROR `ModuleNotFoundError: No module named 'ha'`.

- [ ] **Step 5: Write the implementation**

Create `ha.py`:

```python
"""
Home Assistant REST client. URL and long-lived token come from .env
(HA_URL, HA_TOKEN), read at call time. All failures return None and are logged;
callers keep their cached values.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://192.168.18.186:8123"
UNUSABLE = frozenset({"unavailable", "unknown"})


def base_url() -> str:
    return os.environ.get("HA_URL", DEFAULT_URL).strip().rstrip("/")


def token() -> str:
    return os.environ.get("HA_TOKEN", "").strip()


def get_state(entity_id: str) -> dict | None:
    """Return HA's state object for entity_id, or None on any failure."""
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_ha.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git switch -c ha-integration
git add requirements.txt requirements-dev.txt docker/requirements-combined.txt .env.example tests/conftest.py tests/test_ha.py ha.py
git commit -m "feat: add Home Assistant REST client and test scaffolding" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Weather from Home Assistant

**Files:**
- Modify: `weather.py`, `templates/index.html:241-261`, `static/app.js:660-664` and `static/app.js:793-798`, `config.example.json`
- Test: `tests/test_weather.py`

**Interfaces:**
- Consumes: `ha.get_state`, `ha.usable`, `ha.numeric` (Task 1); `cfg` fixture.
- Produces: `weather._fetch() -> dict | None` returning `{"temp": float, "label": str, "color": str, "rain": float | None}`; `weather._build_text(data: dict) -> str`. Public `tick/force_refresh/clear/restore` and `APP_NAME` unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_weather.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_weather.py -v`
Expected: FAIL (`AttributeError: module 'weather' has no attribute 'ha'` or `_build_text`).

- [ ] **Step 3: Rewrite the top and fetch section of `weather.py`**

Replace the module docstring, imports, the `_WMO` table, the module-state/config helpers (`_wcfg`, `_poll_interval`, `_api_url`) and `_fetch` (everything from the first line of the file down to, but not including, `_room_suffix`) with:

```python
"""
Weather module — reads Home Assistant (NEA Singapore integration): condition and
temperature from a weather entity, plus rainfall from the nearest station sensor.
Entity IDs are config (ha.weather_entity, ha.rain_entity). Poll interval is read
from state.cfg at call time. Suppressed during live Valorant matches.
"""

import logging
from datetime import datetime

import ha
import state

logger = logging.getLogger(__name__)

APP_NAME = "weather"

# ── HA weather condition → (label, hex colour) ───────────────────────────────

_CONDITIONS: dict[str, tuple[str, str]] = {
    "sunny":           ("Sunny",         "#FFD700"),
    "clear-night":     ("Clear",         "#FFD700"),
    "partlycloudy":    ("Partly cloudy", "#87CEEB"),
    "cloudy":          ("Cloudy",        "#9E9E9E"),
    "fog":             ("Foggy",         "#B0BEC5"),
    "hail":            ("Hail",          "#E0E0E0"),
    "lightning":       ("Thunderstorm",  "#FF6F00"),
    "lightning-rainy": ("Thunderstorm",  "#FF6F00"),
    "pouring":         ("Heavy rain",    "#01579B"),
    "rainy":           ("Rain",          "#0288D1"),
    "snowy":           ("Snow",          "#E0E0E0"),
    "snowy-rainy":     ("Sleet",         "#E0E0E0"),
    "windy":           ("Windy",         "#B0BEC5"),
    "windy-variant":   ("Windy",         "#B0BEC5"),
    "exceptional":     ("Alert",         "#FF6F00"),
}

# ── Module state ──────────────────────────────────────────────────────────────

_last_fetch: datetime = datetime.min
_cached: dict | None = None


# ── Config helpers ────────────────────────────────────────────────────────────

def _wcfg() -> dict:
    return state.cfg.get("weather", {})

def _hcfg() -> dict:
    return state.cfg.get("ha", {})

def _poll_interval() -> int:
    return int(_wcfg().get("poll_interval_seconds", 300))

def _weather_entity() -> str:
    return _hcfg().get("weather_entity", "weather.singapore_weather")

def _rain_entity() -> str:
    return _hcfg().get("rain_entity", "sensor.singapore_weather_rainfall_s228")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch() -> dict | None:
    obj = ha.get_state(_weather_entity())
    if not ha.usable(obj):
        return None
    temp = obj.get("attributes", {}).get("temperature")
    if temp is None:
        logger.warning(f"[weather] {_weather_entity()} has no temperature attribute")
        return None
    condition = obj["state"]
    label, color = _CONDITIONS.get(condition, (condition.replace("-", " ").title(), "#FFFFFF"))
    rain = ha.numeric(ha.get_state(_rain_entity()))
    logger.info(f"[weather] {temp}°C  {label}  rain={rain}")
    return {"temp": round(float(temp), 1), "label": label, "color": color, "rain": rain}
```

- [ ] **Step 4: Add `_build_text` and use it in `_push` and `tick`**

In `weather.py`, directly below `_room_suffix()` add:

```python
def _build_text(data: dict) -> str:
    text = f"{data['temp']}°C {data['label']}"
    if data.get("rain"):
        text += f"  |  Rain {data['rain']:g}mm"
    return text + _room_suffix()
```

In `_push`, replace the line `text = f"{data['temp']}°C {data['label']}" + _room_suffix()` with `text = _build_text(data)`.

In `tick`, replace the line `text = f"{_cached['temp']}°C {_cached['label']}" + _room_suffix()` with `text = _build_text(_cached)`.

- [ ] **Step 5: Run weather tests**

Run: `venv/bin/python -m pytest tests/test_weather.py -v`
Expected: 8 passed.

- [ ] **Step 6: Remove the latitude / longitude / location fields from the settings page**

In `templates/index.html`, delete these three blocks (lines 244-255), leaving the "Poll Interval" block:

```html
        <div class="form-group">
          <label>Location Name <span class="hint">(display only)</span></label>
          <input type="text" id="cfg-weather-location">
        </div>
        <div class="form-group">
          <label>Latitude</label>
          <input type="number" step="0.0001" id="cfg-weather-lat">
        </div>
        <div class="form-group">
          <label>Longitude</label>
          <input type="number" step="0.0001" id="cfg-weather-lon">
        </div>
```

In `static/app.js`, replace

```js
    const w = cfg.weather ?? {};
    set('cfg-weather-location',   w.location_name ?? '');
    set('cfg-weather-lat',        w.latitude ?? 1.3404);
    set('cfg-weather-lon',        w.longitude ?? 103.7054);
    set('cfg-weather-poll',       w.poll_interval_seconds ?? 1800);
```

with

```js
    const w = cfg.weather ?? {};
    set('cfg-weather-poll',       w.poll_interval_seconds ?? 300);
```

and replace

```js
    weather: {
      location_name:        get('cfg-weather-location').trim(),
      latitude:             parseFloat(get('cfg-weather-lat')),
      longitude:            parseFloat(get('cfg-weather-lon')),
      poll_interval_seconds: parseInt(get('cfg-weather-poll')),
    },
```

with

```js
    weather: {
      poll_interval_seconds: parseInt(get('cfg-weather-poll')),
    },
```

- [ ] **Step 7: Update `config.example.json`**

Replace the `weather` block

```json
  "weather": {
    "location_name": "Your City, Country",
    "latitude": 0.0,
    "longitude": 0.0,
    "poll_interval_seconds": 1800
  },
```

with

```json
  "weather": {
    "poll_interval_seconds": 300
  },
  "ha": {
    "weather_entity": "weather.singapore_weather",
    "rain_entity": "sensor.singapore_weather_rainfall_s228"
  },
```

- [ ] **Step 8: Verify nothing else still references Open-Meteo or the removed config**

Run: `grep -rn -i "open-meteo\|open_meteo\|latitude\|longitude\|location_name\|_WMO" --include=*.py --include=*.js --include=*.html --include=*.json --include=*.md . --exclude-dir=venv --exclude-dir=docs --exclude=config.json`
Expected: only `README.md` / `INSTALLATION.md` lines (fixed in Task 6). The local `config.json` is excluded here and updated in Task 6. If any `.py`, `.js`, `.html` or `.json` line appears, fix it before continuing.

- [ ] **Step 9: Commit**

```bash
git add weather.py templates/index.html static/app.js config.example.json tests/test_weather.py
git commit -m "feat: weather from Home Assistant (NEA) instead of Open-Meteo" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Event engine core (state rules, queue, rate limit)

**Files:**
- Create: `ha_events.py`
- Test: `tests/test_ha_events.py`

**Interfaces:**
- Consumes: `ha.UNUSABLE` (Task 1), `state.cfg`, `state.scheduler_state`.
- Produces (used by Tasks 4 and 5):
  - `class EventEngine(awtrix, clock=time.monotonic)` with
    - `handle(event: dict) -> None`: `event` is HA's event object `{"event_type": str, "data": {...}}`
    - `flush() -> None`: sends at most one due pop-up through `awtrix.notify(payload)`; releases due debounced values
    - `has_work() -> bool`
    - `enabled() -> bool` (True when at least one enabled rule exists)
    - attribute `connected: bool`
  - payload sent to `awtrix.notify`: `{"text": str, "color": str, "duration": int}` plus optional `"icon": str` and `"hold": True`.
  - Rule config shape under `state.cfg["ha_events"]`: `{"min_gap_seconds": 3, "during_live_match": true, "rules": [...]}`; a `state` rule is `{"name", "type": "state", "entity", "states": {<state>: spec}, "any": spec (optional), "fire_from_unknown": bool (optional), "cooldown_seconds": number (optional), "enabled": bool (optional)}` where `spec` is `{"text", "color", "icon" (optional), "duration" (optional, default 5), "hold" (optional)}`. Text may contain `{state}` and `{attr.NAME}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ha_events.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_ha_events.py -v`
Expected: collection ERROR `ModuleNotFoundError: No module named 'ha_events'`.

- [ ] **Step 3: Write the engine**

Create `ha_events.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_ha_events.py -v`
Expected: 16 passed (the parametrized test counts three).

- [ ] **Step 5: Commit**

```bash
git add ha_events.py tests/test_ha_events.py
git commit -m "feat: event engine core with state rules, queue and rate limit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Value rules (debounce, gate) and automation rules

**Files:**
- Modify: `ha_events.py`
- Test: `tests/test_ha_events.py` (append)

**Interfaces:**
- Consumes: Task 3's `EventEngine`, `_enqueue`, `_render`.
- Produces: `EventEngine.seed_gates() -> None` (reads each `suppress_while` entity once via `ha.get_state`; used by Task 5). `EventEngine.handle` additionally handles `automation_triggered` events: `{"event_type": "automation_triggered", "data": {"entity_id": "automation.x", "name": "..."}}`.
- Rule shapes: value rule `{"name", "type": "value", "entity", "attribute", "scale": "percent255" (optional), "text": "Lights {value}%", "color", "settle_seconds" (default 1.5), "suppress_while": "<entity_id>" (optional)}`; automation rule `{"name", "type": "automation", "entity": "automation.x", "text", "color", ...}` (the rule itself is the spec).

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_ha_events.py`:

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_ha_events.py -v`
Expected: the six new tests FAIL (`AttributeError: seed_gates` / nothing sent); the Task 3 tests still pass. (`ha_events.ha` does not exist yet, so `test_seed_gates_reads_current_gate_state` errors at monkeypatch time.)

- [ ] **Step 3: Implement value and automation rules**

In `ha_events.py`:

Change the imports block to:

```python
import logging
import re
import time
from collections import deque

import ha
import state
from ha import UNUSABLE
```

In `EventEngine.__init__`, add after `self._last_fired`:

```python
        self._pending: dict[str, tuple] = {}   # rule name -> (due, rule, new_state, value)
        self._gates: dict[str, str] = {}       # suppress_while entity -> last known state
```

Replace `handle` and `_on_state_changed` with:

```python
    def handle(self, event: dict) -> None:
        etype, data = event.get("event_type"), event.get("data", {})
        if etype == "state_changed":
            self._on_state_changed(data)
        elif etype == "automation_triggered":
            self._on_automation(data)

    def _gate_entities(self) -> set[str]:
        return {r["suppress_while"] for r in self._rules() if r.get("suppress_while")}

    def seed_gates(self) -> None:
        """Read each suppress_while entity once (call after connecting)."""
        for entity in self._gate_entities():
            obj = ha.get_state(entity)
            if obj:
                self._gates[entity] = obj["state"]

    def _on_state_changed(self, data: dict) -> None:
        entity = data.get("entity_id")
        old, new = data.get("old_state"), data.get("new_state")
        if not new:
            return
        if entity in self._gate_entities():
            self._gates[entity] = new["state"]
        for rule in self._rules():
            if rule.get("entity") != entity:
                continue
            if rule.get("type") == "state":
                self._on_state_rule(rule, old, new)
            elif rule.get("type") == "value":
                self._on_value_rule(rule, old, new)

    def _on_automation(self, data: dict) -> None:
        entity = data.get("entity_id")
        for rule in self._rules():
            if rule.get("type") == "automation" and rule.get("entity") == entity:
                self._enqueue(rule, rule, {"state": "triggered", "attributes": {}})

    def _on_value_rule(self, rule: dict, old: dict | None, new: dict) -> None:
        if old is None or new["state"] in UNUSABLE or old["state"] in UNUSABLE:
            return
        if old["state"] != new["state"]:
            return          # on/off is announced by the state rule
        gate = rule.get("suppress_while")
        if gate and self._gates.get(gate) == "on":
            return
        attr = rule["attribute"]
        before, after = old["attributes"].get(attr), new["attributes"].get(attr)
        if after is None or after == before:
            return
        if rule.get("scale") == "percent255":
            after = round(float(after) / 255 * 100)
        due = self.clock() + float(rule.get("settle_seconds", 1.5))
        self._pending[rule["name"]] = (due, rule, new, after)
```

Replace `has_work` and `flush` with:

```python
    def has_work(self) -> bool:
        return bool(self._queue or self._pending)

    def flush(self) -> None:
        now = self.clock()
        for name, (due, rule, new, value) in list(self._pending.items()):
            if now >= due:
                del self._pending[name]
                self._enqueue(rule, rule, new, value)
        gap = float(self._cfg().get("min_gap_seconds", 3))
        if self._queue and now - self._last_emit >= gap:
            payload = self._queue.popleft()
            self._last_emit = now
            try:
                self.awtrix.notify(payload)
                logger.info(f"[ha_events] pop-up: {payload['text']}")
            except Exception as e:
                logger.warning(f"[ha_events] notify failed: {e}")
```

- [ ] **Step 4: Run all engine tests**

Run: `venv/bin/python -m pytest tests/test_ha_events.py -v`
Expected: 22 passed. If `test_value_rule_debounces...` fails on the 50% value, note `round(128 / 255 * 100)` is 50; a different number means the scale code is wrong.

- [ ] **Step 5: Commit**

```bash
git add ha_events.py tests/test_ha_events.py
git commit -m "feat: debounced value rules, sunrise gate and automation rules" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: WebSocket stream and app wiring

**Files:**
- Modify: `ha_events.py` (append), `main.py` (imports and lifespan)
- Test: `tests/test_ha_events.py` (append)

**Interfaces:**
- Consumes: `EventEngine` (Tasks 3-4), `ha.base_url`, `ha.token`.
- Produces: `ha_events.ws_url() -> str`; `async ha_events.run_event_stream(awtrix) -> None` (runs forever; cancel it to stop).

- [ ] **Step 1: Append the failing test**

Append to `tests/test_ha_events.py`:

```python
def test_ws_url(monkeypatch):
    monkeypatch.setenv("HA_URL", "http://192.168.18.186:8123/")
    assert ha_events.ws_url() == "ws://192.168.18.186:8123/api/websocket"
    monkeypatch.setenv("HA_URL", "https://ha.example.com")
    assert ha_events.ws_url() == "wss://ha.example.com/api/websocket"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/bin/python -m pytest tests/test_ha_events.py::test_ws_url -v`
Expected: FAIL (`AttributeError: module 'ha_events' has no attribute 'ws_url'`).

- [ ] **Step 3: Append the stream code to `ha_events.py`**

Add `import asyncio`, `import json` and `import websockets` to the imports block (keep it alphabetical within each group: `asyncio`, `json`, `logging`, `re`, `time`; then `websockets` before `import ha`). Append at the end of the file:

```python

# ── WebSocket stream ──────────────────────────────────────────────────────────

def ws_url() -> str:
    # http://… → ws://…, https://… → wss://…
    return "ws" + ha.base_url()[4:] + "/api/websocket"


async def _session(engine: EventEngine) -> None:
    async with websockets.connect(ws_url(), open_timeout=10) as ws:
        await ws.recv()                                   # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": ha.token()}))
        reply = json.loads(await ws.recv())
        if reply.get("type") != "auth_ok":
            raise PermissionError(f"Home Assistant rejected the token: {reply.get('message', reply)}")
        await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
        await ws.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "automation_triggered"}))
        engine.seed_gates()
        engine.connected = True
        logger.info("[ha_events] connected to Home Assistant")
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                raw = None
            if raw is not None:
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    engine.handle(msg["event"])
            if engine.has_work():
                engine.flush()


async def run_event_stream(awtrix) -> None:
    """Keep the HA event feed running; reconnect with backoff (2 s doubling to 60 s)."""
    engine = EventEngine(awtrix)
    backoff = 2
    was_up = False
    while True:
        if not ha.token():
            logger.error("[ha_events] HA_TOKEN is not set in .env — event feed disabled")
            return
        if not engine.enabled():
            await asyncio.sleep(30)          # no rules configured; check again later
            continue
        try:
            await _session(engine)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if engine.connected:
                backoff, was_up, engine.connected = 2, True, False
            if was_up:
                logger.warning(f"[ha_events] connection lost: {e!r}; retrying")
                was_up = False
            else:
                logger.debug(f"[ha_events] still disconnected: {e!r}")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
```

Note for the implementer: `engine.flush()` and `engine.seed_gates()` make blocking httpx calls directly inside the coroutine. This matches the rest of the codebase (the scheduler does the same) and keeps `handle`/`flush` on one thread, so the engine needs no locking. Do not move them to worker threads.

- [ ] **Step 4: Run all tests**

Run: `venv/bin/python -m pytest tests -v`
Expected: 35 passed (ha: 4, weather: 8, events: 23).

- [ ] **Step 5: Start the stream in `main.py`**

In the import block of `main.py`, after `import pinned`, add `import ha_events`.

In `lifespan`, replace

```python
    timer_task = asyncio.create_task(timer.run_timer_loop(awtrix))
    yield
    timer_task.cancel()
    sched_task.cancel()
    try:
        await timer_task
    except asyncio.CancelledError:
        pass
```

with

```python
    timer_task = asyncio.create_task(timer.run_timer_loop(awtrix))
    events_task = asyncio.create_task(ha_events.run_event_stream(awtrix))
    yield
    events_task.cancel()
    timer_task.cancel()
    sched_task.cancel()
    try:
        await events_task
    except asyncio.CancelledError:
        pass
    try:
        await timer_task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 6: Check the app still imports**

Run: `venv/bin/python -c "import main; print('ok')"`
Expected: prints `ok` (it reads `config.json`, which exists locally).

- [ ] **Step 7: Commit**

```bash
git add ha_events.py main.py tests/test_ha_events.py
git commit -m "feat: HA WebSocket event stream wired into app lifespan" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Default rules, docs, and live verification

**Files:**
- Modify: `config.example.json`, `docker-compose.yml`, `README.md`, `INSTALLATION.md`
- Local only (not committed): `config.json`, `.env`

**Interfaces:**
- Consumes: everything above. Produces the shipped default `ha_events` rules.

- [ ] **Step 1: Add the default rules to `config.example.json`**

Add this key to the top level of `config.example.json`, directly after the `ha` block:

```json
  "ha_events": {
    "min_gap_seconds": 3,
    "during_live_match": true,
    "rules": [
      {
        "name": "bedroom lights",
        "type": "state",
        "entity": "light.surya_bedroom_lights",
        "states": {
          "on":  {"text": "Lights ON",  "color": "#FFD700"},
          "off": {"text": "Lights OFF", "color": "#888888"}
        }
      },
      {
        "name": "bedroom light level",
        "type": "value",
        "entity": "light.surya_bedroom_lights",
        "attribute": "brightness",
        "scale": "percent255",
        "text": "Lights {value}%",
        "color": "#FFD700",
        "settle_seconds": 1.5,
        "suppress_while": "input_boolean.surya_sunrise_running"
      },
      {
        "name": "sunrise",
        "type": "automation",
        "entity": "automation.surya_bedroom_sunrise_wake_up",
        "text": "Sunrise",
        "color": "#FF8C00"
      },
      {
        "name": "aircon",
        "type": "state",
        "entity": "climate.surya_bedroom_aircon",
        "states": {
          "cool":     {"text": "AC cool {attr.temperature}", "color": "#4FC3F7"},
          "dry":      {"text": "AC dry",                     "color": "#4FC3F7"},
          "fan_only": {"text": "AC fan",                     "color": "#B0BEC5"},
          "off":      {"text": "AC off",                     "color": "#888888"}
        }
      },
      {
        "name": "aircon sleep timer",
        "type": "automation",
        "entity": "automation.surya_bedroom_aircon_sleep_timer",
        "text": "Sleep timer",
        "color": "#9C27B0"
      },
      {
        "name": "welcome home",
        "type": "state",
        "entity": "person.surya",
        "states": {
          "home": {"text": "Welcome home Surya", "color": "#32FF24", "duration": 8}
        }
      }
    ]
  },
```

Validate: `venv/bin/python -c "import json; json.load(open('config.example.json')); print('valid')"`
Expected: `valid`.

- [ ] **Step 2: Optional env_file for the local compose file**

In `docker-compose.yml`, add under the `ulanzi-clock` service (same indent as `restart`):

```yaml
    env_file:
      - path: .env
        required: false
```

- [ ] **Step 3: Update the docs**

In `README.md`: replace every mention of Open-Meteo (the intro list, the prerequisites line, and the `weather` config bullet that mentions `latitude`/`longitude`) with a mention of Home Assistant, and add a short "Home Assistant" section containing: that `HA_URL` and `HA_TOKEN` go in `.env`; that weather comes from `ha.weather_entity` and `ha.rain_entity`; that `ha_events.rules` in `config.json` define the pop-ups (rule types `state`, `value`, `automation`; flags `any`, `hold`, `fire_from_unknown`, `cooldown_seconds`, `suppress_while`); and that doorbell rules are added when the doorbell is wired.

In `INSTALLATION.md`: change the `.env` table row to say it supplies Twitch API variables **and** `HA_URL` / `HA_TOKEN`, and remove "optional" for the `.env` file now that weather needs it.

- [ ] **Step 4: Local config (not committed)**

Update the local, gitignored `config.json` to match: remove `latitude`, `longitude`, `location_name` from `weather`; set `weather.poll_interval_seconds` to `300`; add the `ha` and `ha_events` blocks from `config.example.json`. Use:

```bash
venv/bin/python - <<'EOF'
import json
live = json.load(open("config.json"))
example = json.load(open("config.example.json"))
w = live.setdefault("weather", {})
for k in ("latitude", "longitude", "location_name"):
    w.pop(k, None)
w["poll_interval_seconds"] = 300
live["ha"] = example["ha"]
live["ha_events"] = example["ha_events"]
json.dump(live, open("config.json", "w"), indent=2)
print("config.json updated")
EOF
```

Add `HA_URL=http://192.168.18.186:8123` to the local `.env` (the user already added `HA_TOKEN`). Do not print the token.

- [ ] **Step 5: Run the full test suite**

Run: `venv/bin/python -m pytest tests -v`
Expected: all pass.

- [ ] **Step 6: Live check: weather**

Start the dashboard: `venv/bin/uvicorn main:app --port 8000` (stop any other instance first). In the log, expect `[weather] 28.6°C Cloudy rain=0.0` (values will differ) and `[weather] pushed '…' → HTTP 200`. Compare the text on the clock with the HA dashboard's weather card.

- [ ] **Step 7: Live check: events**

With the dashboard running, expect `[ha_events] connected to Home Assistant` in the log. Then, one at a time, and confirm each pop-up appears on the clock:
1. Press the top rocker on the bedroom switch (lights toggle): "Lights ON" or "Lights OFF".
2. Swipe the slider: one "Lights NN%" about 1.5 s after the swipe ends.
3. Toggle the aircon from the HA dashboard: "AC cool 22" / "AC off".
4. Automation rules (sunrise, sleep timer) are covered by unit tests only; do not trigger those automations just to test (they change lights and timers). Record them as "verified live the next time they run".
5. Welcome home: when Surya next arrives (`person.surya` goes `not_home` → `home`), "Welcome home Surya" appears. Until then record it as not live-tested.

Optional reconnect check: ask the user to restart Home Assistant themselves (never do it for them), then confirm the dashboard log shows one `connection lost` warning and then `connected`, with no pop-up replay.

- [ ] **Step 8: Commit**

```bash
git add config.example.json docker-compose.yml README.md INSTALLATION.md
git commit -m "feat: default bedroom event rules and HA docs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Report**

Report to the user: what was verified live, what was not (item 4 and welcome home if not yet exercised), and that doorbell rules are still to be added once the doorbell exists.
