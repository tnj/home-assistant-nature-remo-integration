# Verify: Nature Remo integration (dev HA instance)

How to run this integration in a local Home Assistant and observe it live.

## Launch

```bash
uv sync                                   # needs sandbox disabled (uv cache in ~/.cache/uv)
mkdir -p config && ln -sfn ../custom_components config/custom_components
uv run hass -c config --log-file config/home-assistant.log   # background, sandbox disabled (port 8123 + network)
```

- First boot: onboarding at http://localhost:8123 creates a local dev user (config/ is gitignored, so each fresh clone onboards anew; pick any throwaway credentials).
- Add the integration: 設定 → デバイスとサービス → 統合を追加 → "Nature Remo" → paste a token from https://home.nature.global/.
- A real token can be kept (untracked) in `.superpowers/nature_token` — ALWAYS `printf '%s'` (no trailing newline; aiohttp rejects newline in headers) and pass via `$(cat ...)`.

## Observe

- States: http://localhost:8123/developer-tools/state (snapshot to file via Playwright `browser_snapshot filename=...`, then grep).
- Service probes with zero physical impact: `number.set_value` of an offset to its current value; `climate.turn_off` on an already-off AC.
- Definitive server-side write evidence: `GET /1/appliances` → the appliance's `settings.updated_at` matches the command time.
- Integration log lines: `grep -i nature config/home-assistant.log`.

## Gotchas

- **Rate budget is 30 req/5 min per ACCOUNT and shared with the user's production HA + phone app.** 429s during verification are environmental, not bugs; coordinator logs once with the reset epoch and recovers. Stop the dev instance when done — its 60s polling competes with production.
- Custom-component **code changes need a full `hass` restart** (module import is once per process).
- `config/` is gitignored; the config entry (incl. token) lives in `config/.storage/`.
- Real-API shapes that differ from old assumptions: TV input buttons are `input-terrestrial`/`input-bs`/`input-cs` (state values are `t`/`bs`/`cs`); relative temp lists have no `+` prefix; unsupported `dirh` ranges come as `[""]`.
