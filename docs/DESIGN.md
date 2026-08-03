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
- **A push that lands mid-poll wins over that poll.** `async_set_updated_data`
  cancels the scheduled refresh but not one already running, and
  `_async_refresh` assigns `self.data` from the in-flight fetch
  unconditionally — so a write completing during the two API calls would be
  overwritten by the pre-write snapshot and, since the push had rescheduled
  the next poll, stay reverted for a full interval. `_merge_pushes_since`
  tags every push with a generation counter and overlays the ones newer than
  the fetch's start back on top of its result. Ids the fetch stopped
  reporting are not resurrected, so removal grace still works. Without this,
  the write lock below would be bypassed: the next writer would rebuild its
  payload from rolled-back extras and clear the earlier write server-side.
- Devices, appliances and entities are added dynamically when they appear and
  removed from the registries when they disappear — every platform drives the
  same `entity.async_manage_platform_entities` helper, whose `build_entities`
  callback maps unique_id → factory for everything the current data warrants.
  Removal candidates come from the entity registry (so orphans from earlier
  runs are swept too) and only go after `STALE_POLLS_BEFORE_REMOVAL`
  consecutive *real* polls without the id: one truncated response must not
  destroy user customizations, and optimistic pushes (which fire the same
  listeners) are excluded via `coordinator.poll_count`. Every removal — of an
  entity registry entry or of a device — is logged at INFO with the id and
  the streak length, because HA core logs entity creation but not removal and
  a wrongful eviction would otherwise be indistinguishable from an entity
  that never existed. Platforms whose membership is **value-gated** rather
  than presence-gated — `sensor` (a device event, or a smart-meter ECHONET
  property, showing up in that poll) and `number` (same events) — pass a
  `retain` predicate that keeps ids whose parent hub/appliance is still
  reported, so an EPC or event dropout can never delete a registry entry;
  only the parent itself vanishing does. Remo hubs and
  appliances are registered in `async_setup_entry` and re-registered on every
  poll, so `via_device` links never dangle (an energy-only Remo E has no
  entities of its own) and a nickname edited in the Nature app propagates.
- `PARALLEL_UPDATES = 0` in `sensor.py` (read-only); `= 1` in every command
  platform (serializes writes; protects the rate budget and IR emission).
- **Device and appliance availability.** `NatureRemoDeviceEntity.available`
  is `False` once the hub's `online` field is explicitly `False`; `None`
  (older firmware that never reports the field at all — everything except
  Nature-2W3, Remo 2.x, and Remo-E-lite) keeps the entity available, since
  the absence of a signal is not itself a signal. `NatureRemoApplianceEntity`/
  `NatureRemoDeviceEntity` fall back to
  the last snapshot seen when their id briefly drops out of a poll (a
  truncated response, or the grace window before registry removal above),
  so an in-flight service call or state read never raises a bare `KeyError`
  — `available` is what reports the id as gone, not an exception.

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
- **A settings write preserves the current power state by default.** Every
  send goes through `_async_send(button=...)`, and `button` defaults to
  `None` → the appliance's own `settings.button`; only an explicit mode
  selection (`set_hvac_mode`, or `set_temperature` with a mode) or
  `turn_on`/`turn_off` passes the power button explicitly. Before this, any
  temperature/fan/swing change implicitly powered a powered-off unit back
  on. Preserving the button on a write that omits it is probe-verified for
  extras writes (`set_aircon_settings`/`set_floor_heater_settings` called
  from `entity.py`) and was verified for the climate entity's **full**
  settings write against real hardware on 2026-07-28 — see "Live
  verification record" below.
- `min_temp` / `max_temp` / `target_temperature_step` come from the **union
  of absolute per-mode temperature lists**, because HA validates
  `set_temperature` against entity-level bounds before mode switches.
  Per-mode enforcement happens at send time by snapping to that mode's
  allowed list; a stored value that cannot be snapped to anything in the
  list (unparseable, or a list with no numeric entries) omits the field
  entirely rather than inventing one — the cloud restores its own
  remembered per-mode value when a field is left out (probe-verified).
  Relative lists (auto, sometimes dry — values with `+`/`-` prefixes or
  ≤ 0) are excluded from the union.
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
  switches; an extras write sends the **full current extras dict merged
  with the new value** plus the current power button, since any extra
  omitted from a write is cleared server-side — never just the one changed
  key. Because both the climate entity and the extras entities can write the
  same appliance's settings, `coordinator.async_write_lock(appliance_id)`
  serializes all of them: a write reads the appliance only after acquiring
  the lock, so it always merges on top of whatever the previous writer just
  landed instead of racing it and silently reverting the change.
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
- **The extras vocabulary is per remote model, not per manufacturer**, so no
  platform code enumerates it: `entity.extra_platform()` classifies whatever
  the catalog reports, and an id with no entry in a platform's
  `KNOWN_EXTRA_TRANSLATION_KEYS` falls back to the API's own `text`. Live
  catalogs seen on 2026-08-03 (four ACs, one account):

  | Remote | Extras |
  | --- | --- |
  | Daikin `arc478a119` | `sleep` (choice on/off, text "Night Set Mode"), `autoclean` |
  | Mitsubishi `pg051` | `autoclean`, `dehumid` (choice 70%/60%/50%/40%) |
  | Panasonic `acxa75c11010` | `autoclean`, `eco` (choice on/off) |
  | Fujitsu `ar-rfa1j` | none |

  `autoclean` is the one id shared by all three manufacturers; everything
  else varies. Japanese names come from what the Nature app displays for
  the same setting, which is why `eco` stays "Eco" and `sleep` is
  「おやすみ運転」. `aroma`, `save_energy` and `off_timer` are still
  unmapped: nobody has read their app labels, and inventing a name that
  disagrees with the app is worse than showing the API's English.

  Three quirks the table records rather than resolves.

  1. Daikin `arc478a119` spells night set mode `sleep` as a binary choice
     where `arc472a82` spells it `new_sleep` as a `time` extra, so the same
     feature is a switch on one remote and a time entity on another. The
     app names them 「おやすみ運転」 and 「新おやすみ運転」, so the two keys
     differ in Japanese; the API calls both "Night Set Mode", so they stay
     identical in English.
  2. `autoclean` reads 「自動内部クリーン」 in the app for Daikin but
     「内部クリーン」 for Mitsubishi, while the API ships the same
     `text: "Mold Proof"` for both. One translation key cannot vary by
     model without teaching the platform code about manufacturers — exactly
     what this design avoids — so the shorter, shared 「内部クリーン」 wins.
  3. Mitsubishi's `dehumid` arrives with `text: "Humidify"` and the
     description "Set the desired humidity level", which contradicts the
     hardcoded `dehumid` → "Dehumidify" name. Daikin's own catalog does
     spell it `text: "Dehumidify"` (and ships a separate `humid`), so the
     translation is right for Daikin and wrong for Mitsubishi; it wins
     today only because it is the localized one.
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
  Their names ("風向スイング"/"風向切替") match neither reference we have:
  the Nature app shows 「スイング」/「固定」 for the same two buttons, while
  the physical remote is labelled 「上下風向」/「左右風向」. Which one is
  right depends on what each command actually does on the unit, which has
  not been observed — so they keep the current descriptive names until
  someone can watch the airflow while pressing them.

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

## Live verification record (2026-07-28)

Per the mandatory release order in `CLAUDE.md` (implement -> code review ->
live verification -> release), the two behaviors that were implemented and
unit-tested ahead of hardware confirmation were verified on 2026-07-28
against a dev HA instance with a real token:

- **Full climate settings write with `button="power-off"`: VERIFIED.**
  `climate.set_temperature` (25 -> 26, then 26 -> 25) on a powered-off AC
  (Mitsubishi-family unit "raibeya aircon", `settings.button == "power-off"`,
  mode cool) kept `button == "power-off"` in the server response and in a
  follow-up `GET /1/appliances` both times; `settings.updated_at` advanced to
  the command time, the temperature stored server-side, the HA entity stayed
  `off` with the new target, and the physical unit did not power on.
- **Entity removal grace against the real API: VERIFIED for the orphan
  sweep.** On the first run after the upgrade, the registry still held two
  v0.1-era orphaned `select` entities (`..._input` unique_ids no longer
  produced). Both were removed exactly 3 real polls after startup with the
  INFO log line naming entity_id, unique_id, and streak; ~100 valid
  disabled-by-default button entities and live entities were untouched
  across the session's polls. What remains an *observe-in-production* item
  (not force-testable on demand): whether any presence-gated catalog
  (signals, TV buttons, extras) flakes on real hardware for 3+ consecutive
  polls, and the retained-sensor `unknown` window during a value dropout.
  Every removal is logged at INFO (`custom_components.nature_remo`), so the
  ongoing check stays: grep the log for "Removing" and confirm each line
  names something genuinely deleted in the Nature app. Old `remote.*`
  registry remnants from v0.1 are outside every current platform's domain
  and are deliberately not swept (one-time manual cleanup if desired).
