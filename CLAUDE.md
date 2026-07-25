# CLAUDE.md — Nature Remo integration for Home Assistant

Home Assistant custom integration for the Nature Remo Cloud API, built to
core-submission quality. Client library lives in a separate repo:
[tnj/aionatureremo](https://github.com/tnj/aionatureremo) → PyPI
`aionatureremo` (pinned in `custom_components/nature_remo/manifest.json`).

Key docs: `docs/DESIGN.md` (architecture & entity design), `docs/MAINTENANCE.md`
(Dependabot / auto-merge / ruleset / dependency-floor policy, both repos),
`docs/CORE_SUBMISSION.md` (core submission playbook). Working specs/plans under
`docs/superpowers/` are local-only (gitignored) — never commit them.

## Commands

```bash
uv sync                                  # set up the venv
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

That four-command gate must be green before every commit. Python is pinned
via `.python-version` (currently 3.14; follow HA's `requires-python` when
bumping). Dev deps floor `homeassistant>=2026.2` (the hacs.json minimum) and
`pytest-homeassistant-custom-component>=0.13`: phcc pins its matching HA
exactly, so the locked HA follows the newest phcc — without the floors,
resolvers (including Dependabot) silently downgrade both to fossil releases.
This repo's tests mock the client; the aionatureremo repo tests against a
local aiohttp fake server — neither depends on aioresponses.

Live verification against real hardware: see `.claude/skills/verify/SKILL.md`
(dev HA launch, token handling, zero-impact write probes).

## Release process (mandatory order)

Implement → code review → live verification on a dev HA with a real token →
only then release. Release = bump `manifest.json` version + tag `vX.Y.Z` +
`gh release create` (HACS tracks GitHub releases). Library releases: bump
version in the aionatureremo repo, tag `vX.Y.Z` there → CI publishes to PyPI
via trusted publishing; then bump the pin here.

## Design principles (settled decisions — don't relitigate casually)

- **State only where the API provides it.** Sensors, smart meter, AC
  settings, and light power are Nature-tracked state. Everything one-way IR
  is a stateless `button`. This is why there is **no `remote` entity** (TVs
  have only a toggle power signal; the platform's mandatory turn_on/off
  could only lie or error) and **no `select` for TV input** (`tv.state.input`
  is the cloud-side virtual remote's band mode — it changes while the TV is
  off; probe-verified).
- **Per-item entities for API-enumerated presets.** Nature uniquely
  enumerates every TV button (`tv.buttons[]`), so each becomes a `button`
  entity (analogy: Hue scenes). Everyday shortcuts (power / select-input-src
  / ch±/ vol±) are enabled by default; the rest ship
  `entity_registry_enabled_default = False`.
- **`settings.extra` is remote-side state** (e.g. Daikin `autoclean`) baked
  into every transmitted IR frame. The climate entity passes it back on
  every settings send (dropping it silently clears the state); writes send
  only `button=<current>` + the new extra so nothing else changes. Every
  `range.extras` entry becomes a CONFIG-category entity — binary on/off →
  `switch`, multi-option choice → `select` (raw API option values), type
  `time` → `time` (HH:MM wire format) — **regardless of current
  availability**: availability flips per operation mode and hidden writes
  are silently ignored, so each entity tracks `availability == "available"`
  on every poll and verifies the write's response echo. All three share
  `NatureRemoExtraEntity` in `entity.py`.
- **Fujitsu `airdir-swing`/`airdir-tilt` are one-shot** (probe-verified: no
  trace anywhere in the API after sending) → they stay press buttons.
- Climate min/max/step come from the **union of absolute mode temperature
  lists** (HA validates set_temperature before mode switches); per-mode
  enforcement happens at send time by snapping to the allowed list.
- Remo hub devices are **eagerly registered** in `async_setup_entry` so
  `via_device` links never dangle (energy-only Remo E has no entities).

## Nature Cloud API facts (verified against real hardware)

- Base `https://api.nature.global`, `Authorization: Bearer <token>`,
  **POST bodies are form-urlencoded** (`data=`, never `json=`). Undocumented
  error body shape `{"code": 429001, "message": "..."}` — branch on HTTP
  status only.
- **Rate limit 30 req / 5 min per ACCOUNT** (`X-Rate-Limit-*` headers,
  tracked by the client). The budget is shared with the Nature app and any
  other integration on the account; the coordinator polls 2 req/60 s.
- TV input buttons are named `input-terrestrial` / `input-bs` / `input-cs` /
  `select-input-src`; `state.input` uses short codes (`t`/`bs`/`cs`).
  Some TVs return a button with an **empty name** — skip it.
- Relative AC temperature lists (auto, sometimes dry) have **no `+` prefix**
  (e.g. `["-5",…,"5"]`); detect via `+`/`-` prefix or value ≤ 0.
- Unsupported `dirh` ranges arrive as `[""]` (placeholder) — empty strings
  are stripped in `_str_list`.
- `extra` request fields are dotted form keys: `extra.$id=$value`; `type` is
  `choice` (binary or multi-option, e.g. `50%`) or `time` (`defaultTime`, sent
  as `21:00`). `availability` is three-valued over an otherwise static
  catalog: `"available"`, `"hidden"` (wrong operation mode), and
  `"unavailable"` (temporarily locked by conflicting stored state — e.g. an
  armed `new_sleep` locks hotwind/humid/powerful; probe-verified). Writes of
  non-available extras return 200 and are **silently ignored** — while still
  clearing the extras omitted from them.
- **FLOOR_HEATER** = aircon-shaped catalog under key `floor_heater`; write via
  `POST .../floor_heater_settings` (aircon_settings → HTTP 500), which answers
  with the **full Appliance** and **clamps** out-of-range temps to the current
  mode's list ends.
- **LIGHT_PROJECTOR** capability `light_projector.layout` is a UI **tree**, not
  `buttons[]`: leaves `type=="button"`, display name in `text` (`label` empty);
  send `POST .../light_projector` `button=<leaf name>` → `{}`. No state.
- Multi-home is **flattened** (one token, all homes, no home field anywhere).
  `BLE_SESAME5` exposes only static `ble` pairing info, no lock state.
  `device.online` exists only on newer firmware (Nature-2W3 / Remo 2.x /
  Remo-E-lite); elsewhere staleness is the only offline signal.
- Smart meter kWh = raw × coefficient(EPC 211, default 1) × unit
  multiplier(EPC 225, **lookup table** — codes 10–13 multiply; never use a
  `10^-n` formula).
- Firmware format `<ModelPrefix>/<version>[-g<hash>]`; prefixes seen:
  `Remo`, `Remo-mini`, `Remo-E-lite`, `Nature-2W3` (Lapis).

## Conventions

- Code, comments, and `strings.json` in English; Japanese only in
  `translations/ja.json` and `README.ja.md`. Keep `strings.json` and
  `translations/en.json` identical (CI hassfest checks translations; never
  put literal URLs in them — use `description_placeholders`).
- `PARALLEL_UPDATES = 0` in `sensor.py`; `= 1` in every command platform.
- unique_id patterns: `{device_id}_{key}` (device sensors/numbers),
  `{appliance_id}` (climate/light), `{appliance_id}_button_{name}`,
  `{appliance_id}_signal_{signal_id}`, `{appliance_id}_extra_{id}`
  (switch/select/time).
- Tests: `tests/fixtures/*.json` mirror **real API payload shapes** (update
  them when reality disagrees); mocked `NatureRemoClient` via conftest;
  explicit state assertions (no snapshot testing); `config_flow.py` must
  stay at 100% coverage.
- Commits/PRs follow conventional-commit style messages.

## Core submission

`docs/CORE_SUBMISSION.md` is the playbook (brands PR → split core PRs
starting with config flow + sensor). `quality_scale.yaml` is the honest rule
ledger. Manifest diff for core: remove `version`, add `quality_scale`.
Design-rationale notes for reviewers (why buttons, why no remote) are at the
bottom of CORE_SUBMISSION.md.
