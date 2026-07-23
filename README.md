# Nature Remo integration for Home Assistant

A Home Assistant integration for the [Nature Remo](https://nature.global/) smart
remote family, built on the [Nature Remo Cloud API](https://developer.nature.global/)
and aimed at inclusion in Home Assistant core (this repository develops it as a
custom component; see [docs/CORE_SUBMISSION.md](docs/CORE_SUBMISSION.md)).

## Features

| Nature Remo | Home Assistant |
| --- | --- |
| Air conditioner | `climate` — modes, target temperature, fan, vertical & horizontal swing; fixed buttons (e.g. swing/tilt) as `button`; remote-side extras (e.g. Daikin mold proof) as `switch` |
| TV | every API-enumerated button as a `button` entity (power / input / channel / volume shortcuts enabled by default; the rest one click away). Power is a toggle signal — the TV has no discrete on/off codes |
| Light | `light` (on/off) + `button` for night / full / brightness buttons |
| Custom IR appliance | one `button` per learned signal |
| Built-in sensors | `sensor` — temperature, humidity, brightness, last motion |
| Sensor calibration | `number` — temperature / humidity offsets |
| Remo E / E lite smart meter | `sensor` — instantaneous power, purchased & sold energy (Energy dashboard ready) |

## Installation (manual, pre-release)

1. Install the client library into your Home Assistant Python environment:
   `pip install aionatureremo`.
2. Copy `custom_components/nature_remo/` into `<config>/custom_components/`.
3. Restart Home Assistant.

## Configuration

1. Issue a personal access token at <https://home.nature.global/>.
2. In Home Assistant: **Settings → Devices & services → Add integration → Nature Remo**.
3. Paste the token. Reauthentication is prompted automatically if the token is revoked.

## Known limitations

- The Cloud API has no push channel; state is polled every 60 seconds
  (API budget: 30 requests / 5 minutes).
- Motion is exposed as a "last motion" timestamp — the API only reports the
  most recent detection, so a realtime motion binary sensor is not possible.
- Some ACs report relative temperatures (`-2`…`+2`) in auto mode; they are
  shown as numbers as-is.
- State changes made with the appliance's own physical remote are invisible
  to Nature and therefore to this integration.

## Development

```bash
uv sync          # set up the workspace
uv run pytest    # library + integration tests
uv run ruff check . && uv run mypy
```

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Nature Inc.
