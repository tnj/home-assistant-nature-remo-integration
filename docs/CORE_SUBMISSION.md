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
