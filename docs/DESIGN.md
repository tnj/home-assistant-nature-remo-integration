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
   (`aircon_settings`, `floor_heater_settings`), the integration always sends
   the current settings plus the change, so nothing is silently reset.

## Architecture

- **Single coordinator** (`DataUpdateCoordinator`, 60 s interval) fetching
  `GET /1/devices` + `GET /1/appliances` sequentially — 2 requests/cycle
  against the account-wide budget of 30 requests / 5 min (shared with the
  Nature app and any other integration on the same account).
- Client (`aionatureremo`) is session-injected, fully typed, and raises
  typed exceptions; 401 → reauth flow, 429/network → `UpdateFailed` with
  the rate-limit reset time in the message.
- Coordinator data lives in `entry.runtime_data`. Command responses
  (aircon/floor-heater/tv/light/offset) update coordinator data
  optimistically via `async_set_updated_data`; the next poll reconciles with
  reality. Floor-heater responses carry the whole Appliance (fresh extras
  catalog included); an AC mode change additionally triggers one coordinator
  refresh, because `aircon_settings` returns bare settings while extras
  availability is per-mode.
- Devices, appliances and entities are added dynamically when they appear and
  removed from the registries when they disappear — every platform drives the
  same `entity.async_manage_platform_entities` helper, whose `build_entities`
  callback maps unique_id → factory for everything the current data warrants.
  Removal candidates come from the entity registry (so orphans from earlier
  runs are swept too) and only go after `STALE_POLLS_BEFORE_REMOVAL`
  consecutive *real* polls without the id: one truncated response must not
  destroy user customizations, and optimistic pushes (which fire the same
  listeners) are excluded via `coordinator.poll_count`. Remo hubs and
  appliances are registered in `async_setup_entry` and re-registered on every
  poll, so `via_device` links never dangle (an energy-only Remo E has no
  entities of its own) and a nickname edited in the Nature app propagates.
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
| Floor heater | `climate` | `{appliance_id}` |
| Floor-heater binary extras (e.g. Corona save_energy) | `switch` (CONFIG) | `{appliance_id}_extra_{id}` |
| AC / floor-heater multi-option extras (e.g. Daikin humid) | `select` (CONFIG) | `{appliance_id}_extra_{id}` |
| AC / floor-heater time extras (e.g. Daikin new_sleep) | `time` (CONFIG) | `{appliance_id}_extra_{id}` |
| TV preset buttons | `button` | `{appliance_id}_button_{name}` |
| Light | `light` + extra `button`s | `{appliance_id}` / `{appliance_id}_button_{name}` |
| Light-projector remote keys | `button` | `{appliance_id}_button_{name}` |
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
- **Relative-offset modes advertise no target temperature**: the feature
  flag is dropped and the attribute is `None` while the current mode's list
  is relative, because HA validates `set_temperature` against the absolute
  union bounds — every valid offset would be rejected and every accepted
  absolute value mangled into the nearest offset. Sends in relative modes
  omit the `temperature` field entirely; the cloud restores its remembered
  per-mode value (probe-verified).
- Fan / swing / horizontal-swing options are the API's raw vocabulary,
  untranslated.
- `settings.extra` is **remote-side state** baked into every IR frame the
  cloud remote transmits (e.g. Daikin `autoclean`). The climate entity
  passes the stored `extra` back on every settings send — dropping it would
  silently clear the state on the physical remote. Binary catalog entries
  (`range.extras` with on/off choices) are exposed as CONFIG-category
  switches; writes send only `button=<current power state>` plus the new
  extra so nothing else changes.
- **Extra availability is dynamic.** The catalog itself (ids, options,
  descriptions) is static; only each entry's `availability` changes
  (probe-verified on Daikin arc472a82). It is three-valued: `"available"`,
  `"hidden"` (not applicable to the current operation mode), and
  `"unavailable"` (temporarily locked by conflicting stored state — e.g.
  while `new_sleep` is armed, hotwind/humid/powerful report unavailable and
  return to available when it is cleared). Writing a non-available extra
  returns HTTP 200 and is **silently ignored** by the server — while still
  clearing every extra omitted from that write. So a
  switch is created for **every** binary extra regardless of its current
  availability, and each switch's HA availability tracks
  `availability == "available"` on every poll. Creating switches only for
  extras available at scan time (the pre-0.3 behavior) left switches that
  looked alive while every toggle was a server-side no-op. Two further
  guards close the polling gap: an AC mode change triggers a coordinator
  refresh (the bare-settings response leaves the catalog stale), and every
  extra write verifies the response echo — a success always echoes the
  extra back, so a missing echo raises instead of pretending the toggle
  worked. Entering a mode that hides a stored extra clears it server-side;
  that is the cloud remote's own semantics, mirrored as-is.
- Non-binary extras are entities too. Multi-option choice extras (Daikin
  `humid`/`dehumid`: off / 40% / 45% / 50% / continuous / beauty) are
  CONFIG-category `select` entities; options are the API's raw values,
  untranslated — the same policy as the fan/swing vocabulary — and the state
  is unknown until a write stores a value. `type: "time"` extras
  (`new_sleep`) are CONFIG-category `time` entities written as
  `extra.new_sleep=HH:MM`; the catalog's `defaultTime` is the remote's
  built-in default, not stored state, so it is never surfaced as state.
  Both follow the same availability-tracking / echo-verification / resend
  rules as the extra switches: switch, select, and time all subclass
  `NatureRemoExtraEntity` in `entity.py`.
- Fujitsu `airdir-swing`/`airdir-tilt` are one-shot commands with no
  readable state anywhere in the API (probe-verified) → press buttons.

## Floor heater

`FLOOR_HEATER` appliances carry a `floor_heater` capability object with
exactly the aircon catalog shape (`range.modes` / `range.fixedButtons` /
`range.extras`, `tempUnit`), so they reuse the climate machinery. Modes
observed are `auto` (relative temperatures, e.g. `["-2"…"2"]`) and `warm`
(absolute 17–30); min/max/step come from the same union of absolute lists,
and sends snap to the current mode's allowed list. Binary extras (e.g.
Corona `save_energy`) become CONFIG switches under the same rules as AC
extras, including the resend-every-time requirement — an extra omitted from
a write is cleared.

Writes go to `POST /1/appliances/{id}/floor_heater_settings`, **not**
`aircon_settings`, which answers HTTP 500 for a floor heater. The
parameters mirror aircon settings (`operation_mode`, `temperature`,
`button`, dotted `extra.$id`): power-off is `button=power-off`, power-on is
sending `operation_mode` (the server then reports `button: ""`). Two
differences from `aircon_settings`: the response is the **whole Appliance
object** rather than bare settings, and out-of-range temperatures are
**clamped server-side** to the ends of the current mode's list (16 → 17 in
warm, 5 → 2 in auto) instead of erroring. Client-side snapping stays as
defense in depth.

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

## Light projector

`LIGHT_PROJECTOR` appliances report no state at all (`settings: null`), so
they are stateless buttons. Their capability object is
`light_projector.layout`: a UI layout **tree** (root → template/composite
nodes → leaves with `type == "button"`), not the flat `buttons[]` array TV
and light appliances use. The client library flattens the tree in document
order (skipping leaves with an empty `name`) and the integration creates one
`button` per flattened leaf.
On a leaf, `name` is the send token and `text` is the display name —
`label` is empty here, unlike TV/light buttons. Only the power key
(`name == "io"`) is enabled by default; the rest ship
`entity_registry_enabled_default = False`, the same philosophy as TV
buttons. Sends are `POST /1/appliances/{id}/light_projector` with
`button=<leaf name>`, answered with 200 `{}`.

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
(QRIO/SESAME — a `BLE_SESAME5` appliance carries only static `ble` pairing
info, no lock state and no battery, so polling cannot back a `lock` entity),
BLE macros, multi-home API, whole-home energy timeseries, ECHONET
refresh/set, Local API, OAuth2 (business-only).

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
