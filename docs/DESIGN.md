# Design

Architecture and entity-design decisions for the Nature Remo integration.
This is the contributor-facing summary of decisions that were settled during
initial development (July 2026) and verified against real hardware; the
reviewer-facing rationale for Home Assistant core submission lives in
[CORE_SUBMISSION.md](CORE_SUBMISSION.md).

## Design philosophy

1. **State only where the API provides it.** Sensors, smart-meter readings,
   AC settings, and light power are state the Nature cloud actually tracks,
   so they become stateful entities. Everything that is a one-way IR blast
   (TV buttons, learned IR signals, light presets) is a stateless `button`.
   No entity ever claims a state the API cannot confirm.
2. **Per-item entities for API-enumerated presets.** The Nature API uniquely
   enumerates every preset button per appliance (`tv.buttons[]`, light
   buttons, learned signals). Each becomes its own entity — the same mapping
   Hue uses for bridge-enumerated scenes — instead of a generic
   send-command service.
3. **Commands resend full state.** Where the API expects complete settings
   (`aircon_settings`), the integration always sends the current settings
   plus the change, so nothing is silently reset.

## Architecture

- **Single coordinator** (`DataUpdateCoordinator`, 60 s interval) fetching
  `GET /1/devices` + `GET /1/appliances` sequentially — 2 requests/cycle
  against the account-wide budget of 30 requests / 5 min (shared with the
  Nature app and any other integration on the same account).
- Client (`aionatureremo`) is session-injected, fully typed, and raises
  typed exceptions; 401 → reauth flow, 429/network → `UpdateFailed` with
  the rate-limit reset time in the message.
- Coordinator data lives in `entry.runtime_data`. Command responses
  (aircon/tv/light/offset) update coordinator data optimistically via
  `async_set_updated_data`; the next poll reconciles with reality.
- Devices and appliances are added dynamically when they appear and removed
  from the device registry when they disappear. Remo hubs are eagerly
  registered in `async_setup_entry` so `via_device` links never dangle
  (an energy-only Remo E has no entities of its own).
- `PARALLEL_UPDATES = 0` in `sensor.py` (read-only); `= 1` in every command
  platform (serializes writes; protects the rate budget and IR emission).

## Entity map

| Source | Platform | unique_id |
| --- | --- | --- |
| Remo temperature/humidity/illuminance/motion | `sensor` | `{device_id}_{key}` |
| Remo temperature/humidity offset | `number` (CONFIG) | `{device_id}_{key}` |
| AC | `climate` | `{appliance_id}` |
| AC binary extras (e.g. Daikin autoclean) | `switch` (CONFIG) | `{appliance_id}_extra_{id}` |
| AC fixed buttons (e.g. Fujitsu airdir-swing) | `button` | `{appliance_id}_button_{name}` |
| TV preset buttons | `button` | `{appliance_id}_button_{name}` |
| Light | `light` + extra `button`s | `{appliance_id}` / `{appliance_id}_button_{name}` |
| Learned IR signals | `button` | `{appliance_id}_signal_{signal_id}` |
| Smart meter (power, energy bought/sold) | `sensor` | `{appliance_id}_{key}` |

## Climate

- Mode mapping: `cool/warm/dry/blow/auto` → `COOL/HEAT/DRY/FAN_ONLY/AUTO`.
  Power-off is **not a mode**: `settings.button == "power-off"` means OFF
  while `settings.mode` keeps the last active mode; turn-on sends
  `button=""`.
- `min_temp` / `max_temp` / `target_temperature_step` come from the **union
  of absolute per-mode temperature lists**, because HA validates
  `set_temperature` against entity-level bounds before mode switches.
  Per-mode enforcement happens at send time by snapping to that mode's
  allowed list. Relative lists (auto, sometimes dry — values with `+`/`-`
  prefixes or ≤ 0) are excluded from the union.
- Fan / swing / horizontal-swing options are the API's raw vocabulary,
  untranslated.
- `settings.extra` is **remote-side state** baked into every IR frame the
  cloud remote transmits (e.g. Daikin `autoclean`). The climate entity
  passes the stored `extra` back on every `aircon_settings` send — dropping
  it would silently clear the state on the physical remote. Binary catalog
  entries (`range.extras` with availability=available and on/off choices)
  are exposed as CONFIG-category switches; writes send only
  `button=<current power state>` plus the new extra so nothing else changes.
- Fujitsu `airdir-swing`/`airdir-tilt` are one-shot commands with no
  readable state anywhere in the API (probe-verified) → press buttons.

## TV

Buttons only — every button the API enumerates becomes a `button` entity.
Everyday shortcuts (`power`, `select-input-src`, `ch-up/down`,
`vol-up/down`) are enabled by default; the rest ship with
`entity_registry_enabled_default = False`. There is deliberately **no
`remote` entity** and **no input `select`**; the full argument (toggle-only
power, `state.input` being a cloud-side band mode that changes while the TV
is off) is in [CORE_SUBMISSION.md](CORE_SUBMISSION.md#design-rationale-notes).

## Light

`is_on` from `state.power`; `ColorMode.ONOFF`. Models exposing only an
`onoff` toggle get toggle sends with `assumed_state = True`. All other
buttons (`night`, `on-100`, brightness/colortemp steps, …) are individual
button entities.

## Smart meter

kWh = raw counter × coefficient (EPC 211, default 1) × unit multiplier
(EPC 225). The multiplier is a **lookup table** — codes 10–13 multiply
(10×…10000×); a `10^-n` formula is wrong for them. Instantaneous power
(EPC 231) is signed; negative means selling. Missing EPC 225 suppresses the
energy sensors; missing EPC 227 suppresses only the reverse-direction one.

## Motion

Motion (`mo`) is a **timestamp sensor** (last detected), not a
`binary_sensor` — with 60 s polling a momentary on/off would be fiction.

## Out of scope (v1)

Other ECHONET appliances (solar, battery, EV, water heater), lock devices
(QRIO/SESAME), FLOOR_HEATER (aircon-compatible API; easy future climate),
LIGHT_PROJECTOR, BLE macros, multi-home API, whole-home energy timeseries,
ECHONET refresh/set, Local API, OAuth2 (business-only).

## Known risks

- **Rate limit** (30 req / 5 min / account, shared): mitigated by 2 req/60 s
  polling, `PARALLEL_UPDATES = 1`, and surfacing the 429 reset time.
- **Undocumented API drift**: error bodies are not parsed (status-code
  branching only); model parsing is defensive except for identity fields
  (`id`, `epc`), which fail fast.
- **Relative AC temperature lists** have no `+` prefix on some models
  (e.g. `["-5",…,"5"]`); detection treats `+`/`-` prefixes or values ≤ 0 as
  relative. Unsupported `dirh` arrives as `[""]` and empty strings are
  stripped.
