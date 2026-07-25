# Nature Remo integration for Home Assistant

A Home Assistant integration for the [Nature Remo](https://nature.global/) smart
remote family, built on the [Nature Remo Cloud API](https://developer.nature.global/)
and aimed at inclusion in Home Assistant core (this repository develops it as a
custom component; see [docs/CORE_SUBMISSION.md](docs/CORE_SUBMISSION.md)).

## Features

| Nature Remo | Home Assistant |
| --- | --- |
| Air conditioner | `climate` — modes, target temperature, fan, vertical & horizontal swing; fixed buttons (e.g. swing/tilt) as `button`; remote-side extras (e.g. Daikin mold proof) as `switch` |
| Floor heater | `climate` — auto / warm modes, target temperature; remote-side extras (e.g. Corona save energy) as `switch` |
| TV | every API-enumerated button as a `button` entity (power / input / channel / volume shortcuts enabled by default; the rest one click away). Power is a toggle signal — the TV has no discrete on/off codes |
| Light | `light` (on/off) + `button` for night / full / brightness buttons |
| Projector | one `button` per key of the remote layout (power enabled by default; the rest one click away) |
| Custom IR appliance | one `button` per learned signal |
| Built-in sensors | `sensor` — temperature, humidity, brightness, last motion |
| Sensor calibration | `number` — temperature / humidity offsets |
| Remo E / E lite smart meter | `sensor` — instantaneous power, purchased & sold energy (Energy dashboard ready) |

## Installation

### HACS (recommended)

Until this integration is listed in the HACS default store, add it as a
custom repository:

1. HACS → three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/tnj/home-assistant-nature-remo-integration`,
   type: **Integration** → Add.
3. Install **Nature Remo** from the HACS list and restart Home Assistant.

Updates arrive through HACS as new releases are tagged. The
[aionatureremo](https://pypi.org/project/aionatureremo/) client library is
installed automatically from the manifest.

### Manual

1. Copy `custom_components/nature_remo/` into `<config>/custom_components/`.
2. Restart Home Assistant (`aionatureremo` is installed automatically).

## Configuration

1. Issue a personal access token at <https://home.nature.global/>.
2. In Home Assistant: **Settings → Devices & services → Add integration → Nature Remo**.
3. Paste the token. Reauthentication is prompted automatically if the token is revoked.

## Known limitations

- The Cloud API has no push channel; state is polled every 60 seconds
  (API budget: 30 requests / 5 minutes).
- Motion is exposed as a "last motion" timestamp — the API only reports the
  most recent detection, so a realtime motion binary sensor is not possible.
- Some ACs and floor heaters report relative temperatures (`-2`…`+2`) in auto
  mode; they are shown as numbers as-is.
- Remote-side extras (mold proof, save energy, …) are only usable in some
  operation modes; the matching `switch` reports unavailable while the
  appliance's current mode hides it, because such a write is accepted and
  then ignored by the cloud.
- State changes made with the appliance's own physical remote are invisible
  to Nature and therefore to this integration.
- The 30 req / 5 min budget is **per Nature account**: running this
  integration alongside another Nature Remo integration (or heavy app use)
  on the same account causes intermittent rate-limit unavailability. Use
  one integration per account.

## Development

```bash
uv sync          # set up the workspace
uv run pytest    # library + integration tests
uv run ruff check . && uv run mypy
```

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Nature Inc.
