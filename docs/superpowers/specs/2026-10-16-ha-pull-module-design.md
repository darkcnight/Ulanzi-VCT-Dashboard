# Home Assistant integration: weather from HA + live room events

Date: 2026-10-16. Status: draft, awaiting user review.
(Replaces the earlier weather-only draft of this file. Sub-project 3, the clock as an HA device over
MQTT, is still separate and later.)

## Context

The clock sits in Surya's bedroom. The dashboard pushes AWTRIX "apps" over HTTP. HA runs at
`http://192.168.18.186:8123`; `HA_TOKEN` is already in the dashboard's `.env` and verified working.
HA facts below come from the Notion wiki (verified 2026-10-07 to 2026-10-15) and must be re-checked
against live HA during implementation.

Two deliverables share one HA connection layer:

- **A. Weather from HA**: replaces Open-Meteo with the NEA Singapore data HA already has.
- **B. Live event feed**: pop-ups on the clock for things happening in Surya's room, plus
  house-wide events (welcome home, doorbell).

## Goals

- Weather on the clock comes from `weather.singapore_weather` (real station readings), and the
  Open-Meteo code is removed.
- The clock shows short pop-ups for: lights turning on/off, light value adjustments, bedroom
  automations starting, aircon changes, welcome home, and (once wired) doorbell events.
- Everything is rule-driven from `config.json`. Changes are made by asking Claude; no UI picker.

## Non-goals

- No web UI to edit rules or entities.
- No fallback to Open-Meteo. If HA is unreachable, weather keeps its last value then disappears. HA
  down almost certainly means the NAS, and so the dashboard, is down too.
- Events from other rooms (Living Room, bathrooms, Satya, Seeva) are not shown, but the rule format
  allows adding them later.
- Push from HA automations and MQTT device control are not part of this spec.

## Shared: `ha.py` (connection layer)

- Config: `HA_URL` (default `http://192.168.18.186:8123`) and `HA_TOKEN` from `.env`, never in
  `config.json`. `.env.example` gains both. `docker-compose.yml` gains `env_file: .env` so the NAS
  container sees them.
- `get_state(entity_id)`: `GET /api/states/<id>`, 10 s timeout, returns `None` and logs on failure.
- `EventStream`: a long-running asyncio task using the HA WebSocket API (`/api/websocket`). It
  authenticates with the token, subscribes to `state_changed` and `automation_triggered`, hands each
  event to the rules engine, and reconnects with backoff (2 s doubling to 60 s). Started and stopped
  with the app in `main.py` next to the scheduler. New dependency: `websockets`.
- 401 on auth is logged as a configuration error and stops retrying fast (backs off to 60 s).

## A. Weather from HA

`weather.py` keeps its public interface (`tick`, `force_refresh`, `clear`, `restore`), app name
`weather`, position in `module_order`, and the room-sensor suffix. Changes:

- `_fetch()` reads `weather.singapore_weather` (condition, temperature) and
  `sensor.singapore_weather_rainfall_s228` via `ha.get_state`.
- Text, e.g. `31°C Cloudy | Rain 0.4mm | ⌂ 24.5°C 61%`; the rain part appears only when rainfall > 0.
  Colour comes from the HA condition (map replaces the WMO table; rain blues, clear gold).
- Removed: `_api_url`, the WMO table, `latitude`/`longitude`/`location_name` from code,
  `config.example.json`, `config.json`. README and INSTALLATION weather lines updated.
- `weather.entity` and `weather.rain_entity` are config keys with the defaults above.
- HA failure: last cached value stays, then AWTRIX drops the app when its `lifetime` expires.

## B. Live event feed

### Flow

HA event → `EventStream` → rules engine (match, debounce, rate limit) → `AwtrixClient.notify`
→ pop-up over the rotating apps. The normal app rotation is untouched.

### Rules (in `config.json` under `ha_events`)

```json
"ha_events": {
  "min_gap_seconds": 3,
  "during_live_match": true,
  "rules": [
    {"name": "bedroom lights", "type": "state", "entity": "light.surya_bedroom_lights",
     "on_state": {"text": "Lights ON", "icon": "...", "color": "#FFD700"},
     "off_state": {"text": "Lights OFF", "icon": "...", "color": "#888888"}}
  ]
}
```

Rule types:

- `state`: fires when an entity changes to a listed state, with text/icon/colour per state.
  `unavailable`/`unknown` never fire.
- `value`: fires for an attribute or numeric state change (e.g. brightness), debounced: shows one
  pop-up with the final value after `settle_seconds` (default 1.5) of quiet, so a slider swipe gives
  "Lights 70%", not twenty pop-ups.
- `automation`: fires on `automation_triggered` for a named `automation.*` entity.
- Per-rule flags: `hold` (stays until dismissed on the clock, for the doorbell), `cooldown_seconds`.

### Default rules shipped (Surya's bedroom and house-wide)

| Event | Source | Pop-up |
|---|---|---|
| Bedroom lights on / off | group `light.surya_bedroom_lights` (the all-six group; not the individual bulbs, which report one by one) | "Lights ON/OFF" |
| Light adjustment | brightness/colour temp of the same group, debounced | "Lights 45%" |
| Sunrise starts | `automation.surya_bedroom_sunrise_wake_up` | sunrise icon |
| Aircon changes | `climate.surya_bedroom_aircon` mode (cool, dry, fan only, off) | "AC cool 24°" / "AC off". During the dry-out, "AC drying" |
| Aircon sleep timer starts | `automation.surya_bedroom_aircon_sleep_timer` | "Sleep timer" |
| Welcome home | `person.surya` → `home` | "Welcome home Surya" |
| Doorbell pressed | Reolink button event entity (house-wide) | held pop-up. Disabled until wired |
| Someone at the door | Frigate doorstep person alert | "Someone at the door". Disabled until wired |

The doorbell rules ship with `"enabled": false` and placeholder entity IDs; they are filled in when
the doorbell design is built. They must respect privacy mode: Frigate stops alerts when
`input_boolean.privacy_*` is on, so no extra handling is needed as long as the rules key off the
Frigate/Reolink entities and not the raw camera.

### Behaviour decisions

- **Noise control:** group entities only; debounce on values; global minimum gap
  (`min_gap_seconds`) with a queue of at most 3 pending pop-ups, oldest dropped.
- **No quiet hours:** pop-ups show at any time of day (decided by the user).
- **During a live Valorant match:** pop-ups still show (they are short and about your room);
  `during_live_match` can turn this off.
- **Icons:** AWTRIX icons by name or ID; chosen during implementation from what the clock has
  installed (`/api/icons` or the web UI), and uploaded if missing.
- **Missing entities:** a rule whose entity does not exist in HA is logged once and skipped, so a
  rename in HA never crashes the stream.

## Error handling

- WebSocket drops: reconnect with backoff, log state transitions only (not every retry).
- HA restarts: the stream reconnects on its own; no pop-ups are generated for the reconnect.
- The first `state_changed` for an entity after (re)connect is recorded but never announced, so
  startup does not replay "Lights ON".

## Testing

- Unit tests (pytest, `httpx` and the WebSocket mocked): rule matching, debounce,
  rate limit and queue, `unavailable` filtering, first-event suppression, text/colour mapping,
  weather text with and without rain, cache retention on HA failure, 401/404 handling.
- Live check against the real HA: press the bedroom switch rocker and watch the pop-up, adjust the
  slider, trigger the sunrise script, toggle `person.surya` with the Companion app, compare the
  weather text with the HA dashboard.

## Open items for implementation

- Confirm the entity IDs of the bedroom lights group, the aircon, the `person` entity, and the
  attribute names on `weather.singapore_weather` against live HA (the wiki may be stale).
- Add `HA_URL` to `.env` (the user has already added `HA_TOKEN`).
- Confirm the doorbell entities once the doorbell exists.
