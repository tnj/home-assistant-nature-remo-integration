# Home Assistant core submission playbook

Steps to move this integration from `custom_components/` into
`home-assistant/core`, in order.

## 1. Publish the library

- Ensure `aionatureremo` CI is green; tag `aionatureremo-v0.1.0` → the
  `publish-lib.yml` workflow builds and publishes to PyPI via trusted
  publishing (configure the PyPI project + environment `pypi` first).
- Requirements from the quality scale (`dependency-transparency`): source on
  GitHub, releases built by CI from tags, OSI license, issue tracker.

## 2. Brands PR

- Repo: `home-assistant/brands`, path `core_integrations/nature_remo/`.
- Files: `icon.png` (256×256) + `icon@2x.png` (512×512); optionally
  `logo.png` / `logo@2x.png` (landscape). PNG, trimmed, compressed.

## 3. Core PR #1 — config flow + sensor (Bronze)

- Copy `custom_components/nature_remo/` → `homeassistant/components/nature_remo/`.
- Copy `tests/` → `tests/components/nature_remo/`.
- Manifest diff: **remove `version`**, add `"quality_scale": "bronze"`.
- Keep only `PLATFORMS = [Platform.SENSOR]` and the sensor platform in PR #1
  (core requires starting with a single platform); leave the rest here.
- Test imports: replace `pytest_homeassistant_custom_component.common` with
  `tests.common`; drop the `enable_custom_integrations` fixture.
- Trim `quality_scale.yaml` statuses to match what PR #1 ships.
- Add yourself to `manifest.json` `codeowners`; run `python -m script.hassfest`.

## 4. Follow-up PRs

climate → light/remote/button/number → diagnostics & dynamic/stale
devices. One platform (or one coherent feature) per PR.

## 5. Documentation PRs

`home-assistant/home-assistant.io`: one page per integration
(`source/_integrations/nature_remo.markdown`), updated alongside each core PR.
The `docs-*` quality-scale rules map to sections of that page.

## Design rationale notes

Why the TV platform creates a `button` entity for every preset button the
Nature API enumerates, not just the four broadcast/input shortcuts:

- The Nature Cloud API uniquely enumerates every preset button per TV
  appliance (`tv.buttons[]`: `name` / `label` / `image`), and this list is
  device-specific — it is not a fixed protocol constant. Per-item entities
  are the natural mapping for cloud-enumerated, per-device items, the same
  way core's Hue integration exposes bridge-enumerated scenes as `scene`
  entities rather than requiring users to invoke them through a generic
  "activate scene" service call.
- Other IR-bridge integrations in core do not do this because they cannot:
  Broadcast's `remote` support has no per-device catalog of named buttons to
  enumerate, and SwitchBot's cloud API cannot even list a hub's learned
  custom IR buttons (see
  [OpenWonderLabs/SwitchBotAPI#251](https://github.com/OpenWonderLabs/SwitchBotAPI/issues/251)).
  Nature Remo's API is the outlier in offering a structured, per-appliance
  button catalog, which is what makes per-item entities viable here.
- Bulk buttons (everything except the four broadcast/input shortcuts) ship
  with `entity_registry_enabled_default = False`, per the
  `entity-disabled-by-default` quality-scale rule — they are present in the
  entity registry and one click away, but do not flood a fresh install's
  entity list.
- The `remote` entity remains the primary control surface: `send_command`
  reaches every button (including ones with an empty API-provided name,
  which get no button entity), so nothing is lost by leaving most buttons
  disabled by default.
