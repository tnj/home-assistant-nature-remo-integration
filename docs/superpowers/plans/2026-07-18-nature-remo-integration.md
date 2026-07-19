# Nature Remo Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a core-quality Home Assistant integration for the Nature Remo Cloud API: a new async PyPI-ready client library (`aionatureremo`) plus `custom_components/nature_remo` covering climate, sensor, light, remote, select, button, and number platforms.

**Architecture:** Monorepo (uv workspace). `lib/aionatureremo` talks HTTP (aiohttp, injected session, form-encoded POSTs, typed frozen dataclasses). The integration has a single `DataUpdateCoordinator` (60 s, `GET /1/devices` + `GET /1/appliances`) stored in `entry.runtime_data`; commands update coordinator data optimistically from POST responses. Config flow keyed on the Nature account user id, with reauth and reconfigure.

**Tech Stack:** Python 3.13, uv, aiohttp, Home Assistant (latest stable), pytest + pytest-homeassistant-custom-component + aioresponses, ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-18-nature-remo-integration-design.md` — read it before starting a task if anything is unclear.

## Global Constraints

- Python `>=3.13` for the workspace; library `requires-python >=3.12`. Run every command through `uv run …` (the workspace venv).
- All code, comments, docstrings, and `strings.json` copy in **English**. Japanese only in `translations/ja.json` and `README.ja.md`.
- Library depends on **aiohttp only** (no pydantic). All models are `@dataclass(frozen=True, slots=True)` with tolerant `from_dict` classmethods (unknown fields ignored, missing **optional** fields default). Keys used for downstream indexing fail fast with KeyError by design — exactly: `User.id`, `Device.id`, `Appliance.id`, `Signal.id`, `EchonetLiteProperty.epc` (the API guarantees them; defaulting them would corrupt indexing silently). `ApplianceModel.id` is descriptive metadata only and is intentionally fail-soft.
- Nature API: base `https://api.nature.global`, header `Authorization: Bearer {token}`, **POST bodies are form-urlencoded** (`data=` in aiohttp, never `json=`), responses are JSON. Rate limit 30 req/5 min; headers `X-Rate-Limit-Limit/-Remaining/-Reset`.
- Integration domain: `nature_remo`. Poll interval: 60 s. No options flow, no user-configurable scan interval.
- Every entity: `_attr_has_entity_name = True`; unique_id patterns exactly as given per task (spec §6).
- `PARALLEL_UPDATES = 0` in `sensor.py`; `PARALLEL_UPDATES = 1` in `climate.py`, `light.py`, `remote.py`, `select.py`, `button.py`, `number.py`.
- TDD: write the failing test, run it and see it fail, implement, see it pass, commit. Never commit with failing tests, ruff errors, or mypy errors (`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q` must be green at every commit).
- Never hardcode a real token anywhere; tests use the literal `"test-token"`.
- Every `git commit` message ends with the trailer (blank line before it):
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## File Structure (target)

```
pyproject.toml                        # uv workspace root: dev deps, ruff/mypy/pytest config
uv.lock                               # committed lockfile
.gitignore  LICENSE                   # MIT
lib/aionatureremo/
  pyproject.toml                      # hatchling package, version 0.1.0
  README.md
  src/aionatureremo/__init__.py       # public exports
  src/aionatureremo/py.typed
  src/aionatureremo/exceptions.py     # error hierarchy
  src/aionatureremo/models.py         # all dataclasses + parsing + smart-meter math
  src/aionatureremo/client.py         # NatureRemoClient (transport + endpoints)
  tests/test_client.py                # transport, endpoints, errors, rate limit
  tests/test_models.py                # from_dict parsing, EPC/energy math
custom_components/nature_remo/
  __init__.py                         # setup/unload, stale-device cleanup
  manifest.json  const.py
  coordinator.py                      # NatureRemoCoordinator + NatureRemoData + typed entry
  entity.py                           # NatureRemoDeviceEntity / NatureRemoApplianceEntity bases
  config_flow.py                      # user + reauth + reconfigure steps
  climate.py sensor.py light.py remote.py select.py button.py number.py
  diagnostics.py
  strings.json  icons.json  quality_scale.yaml
  translations/en.json  translations/ja.json
tests/
  conftest.py                         # enable custom integrations, mock client, fixtures
  fixtures/devices.json  fixtures/appliances.json
  test_config_flow.py  test_init.py  test_coordinator.py
  test_sensor.py  test_climate.py  test_light.py  test_remote.py
  test_select.py  test_button.py  test_number.py  test_diagnostics.py
.github/workflows/ci.yml              # ruff / mypy / pytest / hassfest
.github/workflows/publish-lib.yml     # PyPI publish on tag (trusted publishing)
README.md  README.ja.md  docs/CORE_SUBMISSION.md
```

---

### Task 1: Workspace scaffolding

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `lib/aionatureremo/pyproject.toml`, `lib/aionatureremo/README.md`, `lib/aionatureremo/src/aionatureremo/__init__.py`, `lib/aionatureremo/src/aionatureremo/py.typed`

**Interfaces:**
- Produces: a working uv workspace where `uv run pytest` / `uv run ruff check .` / `uv run mypy` all succeed; package `aionatureremo` importable (version 0.1.0).

- [ ] **Step 1: Create root `pyproject.toml`**

```toml
[project]
name = "nature-remo-ha-workspace"
version = "0.0.0"
description = "Development workspace for the Nature Remo Home Assistant integration"
requires-python = ">=3.13"
dependencies = []

[tool.uv]
package = false
dev-dependencies = [
    "aionatureremo",
    "homeassistant",
    "pytest-homeassistant-custom-component",
    "aioresponses>=0.7.6",
    "ruff>=0.8.0",
    "mypy>=1.14.0",
]

[tool.uv.sources]
aionatureremo = { workspace = true }

[tool.uv.workspace]
members = ["lib/aionatureremo"]

[tool.pytest.ini_options]
testpaths = ["tests", "lib/aionatureremo/tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["B", "E", "F", "I", "RUF", "SIM", "UP", "W"]

[tool.mypy]
python_version = "3.13"
strict = true
files = ["lib/aionatureremo/src", "custom_components/nature_remo"]

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
config/
.superpowers/
```

- [ ] **Step 3: Create `LICENSE`** — full MIT text, `Copyright (c) 2026 Yuki Fujisaki`. Use the canonical MIT license body from https://opensource.org/license/mit (the standard 3-paragraph text) verbatim with that copyright line.

- [ ] **Step 4: Create the library package**

`lib/aionatureremo/pyproject.toml`:

```toml
[project]
name = "aionatureremo"
version = "0.1.0"
description = "Asynchronous Python client for the Nature Remo Cloud API"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
authors = [{ name = "Yuki Fujisaki" }]
keywords = ["nature-remo", "nature", "remo", "home-automation"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Home Automation",
]
dependencies = ["aiohttp>=3.10.0"]

[project.urls]
Repository = "https://github.com/<GITHUB_OWNER>/home-assistant-nature-remo-integration"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aionatureremo"]
```

Replace `<GITHUB_OWNER>` with the output of: `gh api user --jq .login` (run it; if `gh` is unavailable, use `git remote get-url origin` to infer, else leave `tnj`).

`lib/aionatureremo/README.md`:

````markdown
# aionatureremo

Asynchronous Python client for the [Nature Remo Cloud API](https://developer.nature.global/).

Built for Home Assistant: aiohttp session injection, fully typed, no dependencies beyond aiohttp.

## Usage

```python
import aiohttp
from aionatureremo import NatureRemoClient

async with aiohttp.ClientSession() as session:
    client = NatureRemoClient("YOUR_ACCESS_TOKEN", session)
    devices = await client.get_devices()
```

Get an access token at https://home.nature.global/.
````

`lib/aionatureremo/src/aionatureremo/__init__.py`:

```python
"""Asynchronous Python client for the Nature Remo Cloud API."""

__version__ = "0.1.0"
```

`lib/aionatureremo/src/aionatureremo/py.typed`: empty file.

- [ ] **Step 5: Sync and verify**

Run: `uv sync`
Expected: resolves and installs (homeassistant, pytest-homeassistant-custom-component, aionatureremo editable). Note the resolved homeassistant version in the task report.

Run: `uv run python -c "import aionatureremo; print(aionatureremo.__version__)"`
Expected: `0.1.0`

Run: `uv run ruff check . && uv run ruff format .`
Expected: no errors (format rewrites nothing or normalizes whitespace).

Run: `uv run pytest -q`
Expected: `no tests ran` (exit code 5 is acceptable at this step only).

Run: `uv run mypy`
Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold uv workspace and aionatureremo package

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Library — exceptions, transport, rate-limit tracking, `get_user`

**Files:**
- Create: `lib/aionatureremo/src/aionatureremo/exceptions.py`, `lib/aionatureremo/src/aionatureremo/models.py`, `lib/aionatureremo/src/aionatureremo/client.py`
- Modify: `lib/aionatureremo/src/aionatureremo/__init__.py`
- Test: `lib/aionatureremo/tests/test_client.py`, `lib/aionatureremo/tests/__init__.py` (empty)

**Interfaces:**
- Produces:
  - `NatureRemoClient(access_token: str, session: aiohttp.ClientSession, *, base_url: str = "https://api.nature.global")`
  - `await client.get_user() -> User`; `client.rate_limit: RateLimit`
  - `client._request(method: str, path: str, data: dict[str, str] | None = None) -> Any` (internal, used by later tasks)
  - `RateLimit(limit, remaining, reset)`, `User(id, nickname)`, exceptions `NatureRemoError / NatureRemoConnectionError / NatureRemoApiError(status, message) / NatureRemoAuthError / NatureRemoRateLimitError(..., reset)`

- [ ] **Step 1: Write the failing tests** — `lib/aionatureremo/tests/test_client.py`:

```python
"""Tests for the NatureRemoClient transport layer."""

from collections.abc import AsyncGenerator, Generator

import aiohttp
import pytest
from aioresponses import aioresponses

from aionatureremo import (
    NatureRemoApiError,
    NatureRemoAuthError,
    NatureRemoClient,
    NatureRemoConnectionError,
    NatureRemoRateLimitError,
    User,
)

API = "https://api.nature.global"


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    """Provide a real aiohttp session (intercepted by aioresponses)."""
    session = aiohttp.ClientSession()
    yield session
    await session.close()


@pytest.fixture
def client(session: aiohttp.ClientSession) -> NatureRemoClient:
    """Provide a client under test."""
    return NatureRemoClient("test-token", session)


@pytest.fixture
def mock_api() -> Generator[aioresponses]:
    """Intercept aiohttp requests."""
    with aioresponses() as mocked:
        yield mocked


async def test_get_user(client: NatureRemoClient, mock_api: aioresponses) -> None:
    """A successful GET parses the user and sends the bearer token."""
    mock_api.get(f"{API}/1/users/me", payload={"id": "user-1", "nickname": "Alice"})

    user = await client.get_user()

    assert user == User(id="user-1", nickname="Alice")
    calls = list(mock_api.requests.values())[0]
    assert calls[0].kwargs["headers"]["Authorization"] == "Bearer test-token"


async def test_rate_limit_headers_tracked(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """X-Rate-Limit headers update client.rate_limit."""
    mock_api.get(
        f"{API}/1/users/me",
        payload={"id": "user-1", "nickname": "Alice"},
        headers={
            "X-Rate-Limit-Limit": "30",
            "X-Rate-Limit-Remaining": "29",
            "X-Rate-Limit-Reset": "1752825600",
        },
    )

    await client.get_user()

    assert client.rate_limit.limit == 30
    assert client.rate_limit.remaining == 29
    assert client.rate_limit.reset == 1752825600


async def test_unauthorized_raises_auth_error(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """HTTP 401 raises NatureRemoAuthError."""
    mock_api.get(f"{API}/1/users/me", status=401)

    with pytest.raises(NatureRemoAuthError) as err:
        await client.get_user()
    assert err.value.status == 401


async def test_rate_limited_raises_with_reset(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """HTTP 429 raises NatureRemoRateLimitError carrying the reset epoch."""
    mock_api.get(
        f"{API}/1/users/me",
        status=429,
        headers={"X-Rate-Limit-Reset": "1752825600"},
    )

    with pytest.raises(NatureRemoRateLimitError) as err:
        await client.get_user()
    assert err.value.reset == 1752825600


async def test_server_error_raises_api_error(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """HTTP 5xx raises NatureRemoApiError with the status."""
    mock_api.get(f"{API}/1/users/me", status=500, body="boom")

    with pytest.raises(NatureRemoApiError) as err:
        await client.get_user()
    assert err.value.status == 500
    assert isinstance(err.value, NatureRemoApiError)
    assert not isinstance(err.value, NatureRemoAuthError)


async def test_network_failure_raises_connection_error(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """aiohttp errors surface as NatureRemoConnectionError."""
    mock_api.get(
        f"{API}/1/users/me", exception=aiohttp.ClientConnectionError("refused")
    )

    with pytest.raises(NatureRemoConnectionError):
        await client.get_user()
```

Also create empty `lib/aionatureremo/tests/__init__.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest lib/aionatureremo/tests/test_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'NatureRemoClient'`

- [ ] **Step 3: Implement**

`lib/aionatureremo/src/aionatureremo/exceptions.py`:

```python
"""Exceptions raised by aionatureremo."""

from __future__ import annotations


class NatureRemoError(Exception):
    """Base exception for all aionatureremo errors."""


class NatureRemoConnectionError(NatureRemoError):
    """Raised when the API cannot be reached."""


class NatureRemoApiError(NatureRemoError):
    """Raised when the API returns an error status."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize with the HTTP status and a short message."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class NatureRemoAuthError(NatureRemoApiError):
    """Raised when the access token is invalid or revoked (HTTP 401)."""


class NatureRemoRateLimitError(NatureRemoApiError):
    """Raised when the API rate limit is exceeded (HTTP 429)."""

    def __init__(self, status: int, message: str, *, reset: int | None = None) -> None:
        """Initialize with the epoch second at which the limit resets."""
        super().__init__(status, message)
        self.reset = reset
```

`lib/aionatureremo/src/aionatureremo/models.py` (initial content; later tasks extend it):

```python
"""Data models for the Nature Remo Cloud API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp, returning None when absent or invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Rate limit state reported by the API response headers."""

    limit: int | None
    remaining: int | None
    reset: int | None


@dataclass(frozen=True, slots=True)
class User:
    """A Nature account."""

    id: str
    nickname: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        """Build from an API payload."""
        return cls(id=str(data["id"]), nickname=str(data.get("nickname") or ""))
```

`lib/aionatureremo/src/aionatureremo/client.py`:

```python
"""Asynchronous client for the Nature Remo Cloud API."""

from __future__ import annotations

import json
from typing import Any

import aiohttp
from multidict import CIMultiDictProxy

from .exceptions import (
    NatureRemoApiError,
    NatureRemoAuthError,
    NatureRemoConnectionError,
    NatureRemoRateLimitError,
)
from .models import RateLimit, User

API_BASE_URL = "https://api.nature.global"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class NatureRemoClient:
    """Client for api.nature.global using an injected aiohttp session."""

    def __init__(
        self,
        access_token: str,
        session: aiohttp.ClientSession,
        *,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize the client with a personal access token."""
        self._access_token = access_token
        self._session = session
        self._base_url = base_url.rstrip("/")
        self.rate_limit = RateLimit(limit=None, remaining=None, reset=None)

    async def _request(
        self, method: str, path: str, data: dict[str, str] | None = None
    ) -> Any:
        """Perform a request; POST bodies are form-urlencoded per the API."""
        try:
            response = await self._session.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
                data=data,
                timeout=_TIMEOUT,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NatureRemoConnectionError(
                f"Error connecting to the Nature API: {err}"
            ) from err

        self._track_rate_limit(response.headers)

        if response.status == 401:
            raise NatureRemoAuthError(response.status, "Invalid access token")
        if response.status == 429:
            raise NatureRemoRateLimitError(
                response.status,
                "API rate limit exceeded",
                reset=self.rate_limit.reset,
            )
        if response.status >= 400:
            body = await response.text()
            raise NatureRemoApiError(response.status, body[:200])

        text = await response.text()
        return json.loads(text) if text else None

    def _track_rate_limit(self, headers: CIMultiDictProxy[str]) -> None:
        """Update rate limit state from response headers, if present."""

        def _int_header(name: str) -> int | None:
            try:
                return int(headers[name])
            except (KeyError, ValueError):
                return None

        limit = _int_header("X-Rate-Limit-Limit")
        remaining = _int_header("X-Rate-Limit-Remaining")
        reset = _int_header("X-Rate-Limit-Reset")
        if limit is not None or remaining is not None or reset is not None:
            self.rate_limit = RateLimit(limit=limit, remaining=remaining, reset=reset)

    async def get_user(self) -> User:
        """Return the account that owns the access token."""
        return User.from_dict(await self._request("GET", "/1/users/me"))
```

Update `lib/aionatureremo/src/aionatureremo/__init__.py`:

```python
"""Asynchronous Python client for the Nature Remo Cloud API."""

from .client import API_BASE_URL, NatureRemoClient
from .exceptions import (
    NatureRemoApiError,
    NatureRemoAuthError,
    NatureRemoConnectionError,
    NatureRemoError,
    NatureRemoRateLimitError,
)
from .models import RateLimit, User

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "NatureRemoApiError",
    "NatureRemoAuthError",
    "NatureRemoClient",
    "NatureRemoConnectionError",
    "NatureRemoError",
    "NatureRemoRateLimitError",
    "RateLimit",
    "User",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest lib/aionatureremo/tests/test_client.py -v`
Expected: 6 passed.

Note: if `multidict` import in `client.py` trips mypy or ruff, type the parameter as `CIMultiDictProxy[str]` exactly as shown (multidict is an aiohttp dependency and ships types). If aioresponses' request introspection API differs (`calls[0].kwargs`), inspect `mock_api.requests` in a debugger and adapt the assertion — the goal is asserting the Authorization header value.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`
Expected: all green.

```bash
git add -A
git commit -m "feat(lib): add client transport, error hierarchy, rate-limit tracking

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Library — Device model, `get_devices`, sensor offsets

**Files:**
- Modify: `lib/aionatureremo/src/aionatureremo/models.py`, `lib/aionatureremo/src/aionatureremo/client.py`, `lib/aionatureremo/src/aionatureremo/__init__.py`
- Test: `lib/aionatureremo/tests/test_models.py` (create), `lib/aionatureremo/tests/test_client.py` (extend)

**Interfaces:**
- Produces:
  - `SensorValue(value: float, created_at: datetime | None)`
  - `Device(id, name, temperature_offset: float, humidity_offset: float, firmware_version: str, mac_address: str | None, bt_mac_address: str | None, serial_number: str | None, events: dict[str, SensorValue])` with `Device.from_dict`
  - Event keys are the raw API keys: `"te"` `"hu"` `"il"` `"mo"`
  - `await client.get_devices() -> list[Device]`
  - `await client.set_temperature_offset(device_id: str, offset: int) -> Device`
  - `await client.set_humidity_offset(device_id: str, offset: int) -> Device`

- [ ] **Step 1: Write the failing tests**

Create `lib/aionatureremo/tests/test_models.py`:

```python
"""Tests for model parsing."""

from datetime import UTC, datetime

from aionatureremo import Device

DEVICE_PAYLOAD = {
    "id": "device-1",
    "name": "Living Remo",
    "temperature_offset": 1,
    "humidity_offset": -2,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2026-07-01T00:00:00Z",
    "mac_address": "ab:cd:ef:12:34:56",
    "bt_mac_address": "ab:cd:ef:12:34:57",
    "serial_number": "1W123456789012",
    "firmware_version": "Remo/1.14.8",
    "newest_events": {
        "te": {"val": 26.4, "created_at": "2026-07-18T07:59:00Z"},
        "hu": {"val": 52, "created_at": "2026-07-18T07:59:00Z"},
        "il": {"val": 123.4, "created_at": "2026-07-18T07:58:00Z"},
        "mo": {"val": 1, "created_at": "2026-07-18T07:50:00Z"},
    },
}


def test_device_from_dict_full() -> None:
    """All fields and events parse."""
    device = Device.from_dict(DEVICE_PAYLOAD)

    assert device.id == "device-1"
    assert device.name == "Living Remo"
    assert device.temperature_offset == 1.0
    assert device.humidity_offset == -2.0
    assert device.firmware_version == "Remo/1.14.8"
    assert device.mac_address == "ab:cd:ef:12:34:56"
    assert device.serial_number == "1W123456789012"
    assert device.events["te"].value == 26.4
    assert device.events["mo"].created_at == datetime(2026, 7, 18, 7, 50, tzinfo=UTC)


def test_device_from_dict_minimal() -> None:
    """A device without events (e.g. Remo E lite) parses with defaults."""
    device = Device.from_dict({"id": "device-2", "name": "Remo E lite"})

    assert device.events == {}
    assert device.temperature_offset == 0.0
    assert device.mac_address is None
```

Append to `lib/aionatureremo/tests/test_client.py`:

```python
async def test_get_devices(client: NatureRemoClient, mock_api: aioresponses) -> None:
    """Devices endpoint parses into a list of Device."""
    mock_api.get(
        f"{API}/1/devices",
        payload=[
            {
                "id": "device-1",
                "name": "Living Remo",
                "firmware_version": "Remo/1.14.8",
                "newest_events": {"te": {"val": 26.4, "created_at": "2026-07-18T07:59:00Z"}},
            }
        ],
    )

    devices = await client.get_devices()

    assert len(devices) == 1
    assert devices[0].id == "device-1"
    assert devices[0].events["te"].value == 26.4


async def test_set_temperature_offset(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """Offset update POSTs a form body and returns the updated device."""
    mock_api.post(
        f"{API}/1/devices/device-1/temperature_offset",
        payload={"id": "device-1", "name": "Living Remo", "temperature_offset": 2},
    )

    device = await client.set_temperature_offset("device-1", 2)

    assert device.temperature_offset == 2.0
    calls = list(mock_api.requests.values())[0]
    assert calls[0].kwargs["data"] == {"offset": "2"}


async def test_set_humidity_offset(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """Humidity offset hits its own endpoint."""
    mock_api.post(
        f"{API}/1/devices/device-1/humidity_offset",
        payload={"id": "device-1", "name": "Living Remo", "humidity_offset": -3},
    )

    device = await client.set_humidity_offset("device-1", -3)

    assert device.humidity_offset == -3.0
```

Add the needed import at the top of `test_models.py` only (shown above); `test_client.py` already imports what it needs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest lib/aionatureremo/tests -v`
Expected: FAIL — `ImportError: cannot import name 'Device'`

- [ ] **Step 3: Implement**

Append to `lib/aionatureremo/src/aionatureremo/models.py`:

```python
EVENT_TEMPERATURE = "te"
EVENT_HUMIDITY = "hu"
EVENT_ILLUMINATION = "il"
EVENT_MOVEMENT = "mo"


@dataclass(frozen=True, slots=True)
class SensorValue:
    """A single sensor reading from newest_events."""

    value: float
    created_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorValue:
        """Build from an API payload."""
        return cls(
            value=float(data["val"]),
            created_at=_parse_datetime(data.get("created_at")),
        )


@dataclass(frozen=True, slots=True)
class Device:
    """A Nature Remo hardware device."""

    id: str
    name: str
    temperature_offset: float
    humidity_offset: float
    firmware_version: str
    mac_address: str | None
    bt_mac_address: str | None
    serial_number: str | None
    events: dict[str, SensorValue]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Device:
        """Build from an API payload; unknown event keys are kept as-is."""
        raw_events = data.get("newest_events") or {}
        events = {
            key: SensorValue.from_dict(value)
            for key, value in raw_events.items()
            if isinstance(value, dict) and "val" in value
        }
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or ""),
            temperature_offset=float(data.get("temperature_offset") or 0),
            humidity_offset=float(data.get("humidity_offset") or 0),
            firmware_version=str(data.get("firmware_version") or ""),
            mac_address=data.get("mac_address"),
            bt_mac_address=data.get("bt_mac_address"),
            serial_number=data.get("serial_number"),
            events=events,
        )
```

Append to `NatureRemoClient` in `client.py` (and add `Device` to the `.models` import):

```python
    async def get_devices(self) -> list[Device]:
        """Return all Nature Remo devices on the account."""
        data = await self._request("GET", "/1/devices")
        return [Device.from_dict(item) for item in data]

    async def set_temperature_offset(self, device_id: str, offset: int) -> Device:
        """Set the temperature offset (device-specific integer steps)."""
        data = await self._request(
            "POST",
            f"/1/devices/{device_id}/temperature_offset",
            data={"offset": str(offset)},
        )
        return Device.from_dict(data)

    async def set_humidity_offset(self, device_id: str, offset: int) -> Device:
        """Set the humidity offset (device-specific integer steps)."""
        data = await self._request(
            "POST",
            f"/1/devices/{device_id}/humidity_offset",
            data={"offset": str(offset)},
        )
        return Device.from_dict(data)
```

Add to `__init__.py` imports/`__all__`: `Device`, `SensorValue`, and the event key constants `EVENT_TEMPERATURE`, `EVENT_HUMIDITY`, `EVENT_ILLUMINATION`, `EVENT_MOVEMENT`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest lib/aionatureremo/tests -v`
Expected: all pass (9 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat(lib): add Device model, get_devices, sensor offsets

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Library — appliance sub-models (AC / TV / LIGHT / signals)

**Files:**
- Modify: `lib/aionatureremo/src/aionatureremo/models.py`, `lib/aionatureremo/src/aionatureremo/__init__.py`
- Test: `lib/aionatureremo/tests/test_models.py`

**Interfaces:**
- Produces (all frozen slots dataclasses with `from_dict`):
  - `ApplianceModel(id, manufacturer, remote_name, series, name, image)` (all `str | None` except `id: str`)
  - `AirconModeRange(temperatures: list[str], volumes: list[str], directions: list[str], directions_h: list[str])`
  - `Aircon(modes: dict[str, AirconModeRange], fixed_buttons: list[str], temp_unit: str)`
  - `AirconSettings(temperature: str, temperature_unit: str, mode: str, volume: str, direction: str, direction_h: str, button: str, updated_at: datetime | None)`
  - `ApplianceButton(name: str, label: str, image: str)`
  - `TVState(input: str | None)`, `TV(buttons: list[ApplianceButton], state: TVState)`
  - `LightState(brightness: str | None, power: str | None, last_button: str | None)`, `Light(buttons: list[ApplianceButton], state: LightState)`
  - `Signal(id: str, name: str, image: str)`

- [ ] **Step 1: Write the failing tests** — append to `lib/aionatureremo/tests/test_models.py`:

```python
from aionatureremo import (  # noqa: E402  (merge into the existing import block)
    Aircon,
    AirconSettings,
    Light,
    Signal,
    TV,
)

AIRCON_PAYLOAD = {
    "range": {
        "modes": {
            "cool": {
                "temp": ["24", "25", "26", "27", "28"],
                "vol": ["1", "2", "3", "auto"],
                "dir": ["1", "2", "swing", "auto"],
                "dirh": ["1", "2", "3", "swing"],
            },
            "dry": {"temp": [], "vol": ["auto"], "dir": [], "dirh": []},
            "auto": {"temp": ["-2", "-1", "0", "+1", "+2"], "vol": ["auto"], "dir": [], "dirh": []},
        },
        "fixedButtons": ["power-off"],
    },
    "tempUnit": "c",
}


def test_aircon_from_dict() -> None:
    """Mode ranges, fixed buttons and temp unit parse."""
    aircon = Aircon.from_dict(AIRCON_PAYLOAD)

    assert set(aircon.modes) == {"cool", "dry", "auto"}
    assert aircon.modes["cool"].temperatures == ["24", "25", "26", "27", "28"]
    assert aircon.modes["cool"].directions_h == ["1", "2", "3", "swing"]
    assert aircon.modes["dry"].temperatures == []
    assert aircon.fixed_buttons == ["power-off"]
    assert aircon.temp_unit == "c"


def test_aircon_settings_from_dict() -> None:
    """Settings parse, treating null-ish values as empty strings."""
    settings = AirconSettings.from_dict(
        {
            "temp": "26",
            "temp_unit": "c",
            "mode": "cool",
            "vol": "auto",
            "dir": "swing",
            "dirh": "",
            "button": None,
            "updated_at": "2026-07-18T06:00:00Z",
        }
    )

    assert settings.temperature == "26"
    assert settings.mode == "cool"
    assert settings.volume == "auto"
    assert settings.direction == "swing"
    assert settings.direction_h == ""
    assert settings.button == ""
    assert settings.updated_at is not None


def test_tv_from_dict() -> None:
    """TV buttons and input state parse."""
    tv = TV.from_dict(
        {
            "state": {"input": "t"},
            "buttons": [
                {"name": "power", "image": "ico_io", "label": "Power"},
                {"name": "vol-up", "image": "ico_vol_up", "label": "Volume up"},
            ],
        }
    )

    assert tv.state.input == "t"
    assert [b.name for b in tv.buttons] == ["power", "vol-up"]


def test_light_from_dict() -> None:
    """Light buttons and state parse; missing state fields become None."""
    light = Light.from_dict(
        {
            "state": {"brightness": "100", "power": "on", "last_button": "on"},
            "buttons": [{"name": "on", "image": "ico_on", "label": "On"}],
        }
    )

    assert light.state.power == "on"
    assert light.buttons[0].label == "On"

    empty = Light.from_dict({})
    assert empty.state.power is None
    assert empty.buttons == []


def test_signal_from_dict() -> None:
    """IR signals parse."""
    signal = Signal.from_dict({"id": "signal-1", "name": "Power", "image": "ico_io"})

    assert signal.id == "signal-1"
    assert signal.name == "Power"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest lib/aionatureremo/tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Aircon'`

- [ ] **Step 3: Implement** — append to `models.py`:

```python
@dataclass(frozen=True, slots=True)
class ApplianceModel:
    """Metadata about the appliance's remote/model."""

    id: str
    manufacturer: str | None
    remote_name: str | None
    series: str | None
    name: str | None
    image: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplianceModel:
        """Build from an API payload."""
        return cls(
            id=str(data.get("id") or ""),
            manufacturer=data.get("manufacturer"),
            remote_name=data.get("remote_name"),
            series=data.get("series"),
            name=data.get("name"),
            image=data.get("image"),
        )


def _str_list(value: Any) -> list[str]:
    """Coerce an optional list of values into a list of strings."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


@dataclass(frozen=True, slots=True)
class AirconModeRange:
    """Allowed setting values for one AC operation mode."""

    temperatures: list[str]
    volumes: list[str]
    directions: list[str]
    directions_h: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AirconModeRange:
        """Build from an API payload."""
        return cls(
            temperatures=_str_list(data.get("temp")),
            volumes=_str_list(data.get("vol")),
            directions=_str_list(data.get("dir")),
            directions_h=_str_list(data.get("dirh")),
        )


@dataclass(frozen=True, slots=True)
class Aircon:
    """AC capabilities."""

    modes: dict[str, AirconModeRange]
    fixed_buttons: list[str]
    temp_unit: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Aircon:
        """Build from an API payload."""
        range_data = data.get("range") or {}
        modes_data = range_data.get("modes") or {}
        return cls(
            modes={
                str(mode): AirconModeRange.from_dict(mode_range or {})
                for mode, mode_range in modes_data.items()
            },
            fixed_buttons=_str_list(range_data.get("fixedButtons")),
            temp_unit=str(data.get("tempUnit") or ""),
        )


@dataclass(frozen=True, slots=True)
class AirconSettings:
    """Current AC settings; button == "power-off" means the AC is off."""

    temperature: str
    temperature_unit: str
    mode: str
    volume: str
    direction: str
    direction_h: str
    button: str
    updated_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AirconSettings:
        """Build from an API payload."""
        return cls(
            temperature=str(data.get("temp") or ""),
            temperature_unit=str(data.get("temp_unit") or ""),
            mode=str(data.get("mode") or ""),
            volume=str(data.get("vol") or ""),
            direction=str(data.get("dir") or ""),
            direction_h=str(data.get("dirh") or ""),
            button=str(data.get("button") or ""),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass(frozen=True, slots=True)
class ApplianceButton:
    """A named IR button on a TV or LIGHT appliance."""

    name: str
    label: str
    image: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplianceButton:
        """Build from an API payload."""
        return cls(
            name=str(data.get("name") or ""),
            label=str(data.get("label") or ""),
            image=str(data.get("image") or ""),
        )


@dataclass(frozen=True, slots=True)
class TVState:
    """Current TV state."""

    input: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TVState:
        """Build from an API payload."""
        return cls(input=data.get("input"))


@dataclass(frozen=True, slots=True)
class TV:
    """A TV appliance."""

    buttons: list[ApplianceButton]
    state: TVState

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TV:
        """Build from an API payload."""
        return cls(
            buttons=[
                ApplianceButton.from_dict(button)
                for button in data.get("buttons") or []
            ],
            state=TVState.from_dict(data.get("state") or {}),
        )


@dataclass(frozen=True, slots=True)
class LightState:
    """Current light state."""

    brightness: str | None
    power: str | None
    last_button: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightState:
        """Build from an API payload."""
        return cls(
            brightness=data.get("brightness"),
            power=data.get("power"),
            last_button=data.get("last_button"),
        )


@dataclass(frozen=True, slots=True)
class Light:
    """A LIGHT appliance."""

    buttons: list[ApplianceButton]
    state: LightState

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Light:
        """Build from an API payload."""
        return cls(
            buttons=[
                ApplianceButton.from_dict(button)
                for button in data.get("buttons") or []
            ],
            state=LightState.from_dict(data.get("state") or {}),
        )


@dataclass(frozen=True, slots=True)
class Signal:
    """A learned IR signal."""

    id: str
    name: str
    image: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """Build from an API payload."""
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or ""),
            image=str(data.get("image") or ""),
        )
```

Add all new names to `__init__.py` imports and `__all__`: `Aircon`, `AirconModeRange`, `AirconSettings`, `ApplianceButton`, `ApplianceModel`, `Light`, `LightState`, `Signal`, `TV`, `TVState`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest lib/aionatureremo/tests -v`
Expected: all pass.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat(lib): add AC/TV/light/signal appliance models

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Library — smart meter model and energy math

**Files:**
- Modify: `lib/aionatureremo/src/aionatureremo/models.py`, `lib/aionatureremo/src/aionatureremo/__init__.py`
- Test: `lib/aionatureremo/tests/test_models.py`

**Interfaces:**
- Produces:
  - `EchonetLiteProperty(name: str, epc: int, value: str, updated_at: datetime | None)`
  - `SmartMeter(properties: list[EchonetLiteProperty])` with `from_dict` and computed properties:
    - `instantaneous_power_w -> int | None` (EPC 231, signed watts)
    - `cumulative_energy_kwh -> float | None` (EPC 224 × coefficient(EPC 211, default 1) × unit multiplier(EPC 225))
    - `cumulative_energy_reverse_kwh -> float | None` (EPC 227, same scaling)
  - Unit multiplier table `{0: 1, 1: 0.1, 2: 0.01, 3: 0.001, 4: 0.0001, 10: 10, 11: 100, 12: 1000, 13: 10000}`; missing EPC 225 ⇒ energy properties return `None`.

- [ ] **Step 1: Write the failing tests** — append to `test_models.py`:

```python
from aionatureremo import SmartMeter  # merge into the existing import block


def _meter(props: list[dict[str, object]]) -> SmartMeter:
    return SmartMeter.from_dict({"echonetlite_properties": props})


SMART_METER_PROPS: list[dict[str, object]] = [
    {"name": "coefficient", "epc": 211, "val": "1", "updated_at": "2026-07-18T07:00:00Z"},
    {"name": "cumulative_electric_energy_effective_digits", "epc": 215, "val": "6"},
    {"name": "normal_direction_cumulative_electric_energy", "epc": 224, "val": "123456"},
    {"name": "cumulative_electric_energy_unit", "epc": 225, "val": "1"},
    {"name": "reverse_direction_cumulative_electric_energy", "epc": 227, "val": "1234"},
    {"name": "measured_instantaneous", "epc": 231, "val": "520"},
]


def test_smart_meter_energy_math() -> None:
    """kWh = raw x coefficient x unit multiplier; power is raw watts."""
    meter = _meter(SMART_METER_PROPS)

    assert meter.instantaneous_power_w == 520
    assert meter.cumulative_energy_kwh == 12345.6
    assert meter.cumulative_energy_reverse_kwh == 123.4


def test_smart_meter_multiplying_unit_codes() -> None:
    """Unit codes 10-13 multiply (a naive 10^-n formula would be wrong)."""
    meter = _meter(
        [
            {"epc": 224, "val": "5", "name": "normal"},
            {"epc": 225, "val": "11", "name": "unit"},
        ]
    )

    assert meter.cumulative_energy_kwh == 500.0


def test_smart_meter_negative_power() -> None:
    """Instantaneous power is signed (negative = exporting)."""
    meter = _meter([{"epc": 231, "val": "-300", "name": "instant"}])

    assert meter.instantaneous_power_w == -300


def test_smart_meter_missing_unit_returns_none() -> None:
    """Without EPC 225 the cumulative energy cannot be scaled."""
    meter = _meter([{"epc": 224, "val": "123456", "name": "normal"}])

    assert meter.cumulative_energy_kwh is None
    assert meter.cumulative_energy_reverse_kwh is None
    assert meter.instantaneous_power_w is None


def test_smart_meter_coefficient_defaults_to_one() -> None:
    """Missing coefficient (EPC 211) defaults to 1."""
    meter = _meter(
        [
            {"epc": 224, "val": "100", "name": "normal"},
            {"epc": 225, "val": "2", "name": "unit"},
        ]
    )

    assert meter.cumulative_energy_kwh == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest lib/aionatureremo/tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'SmartMeter'`

- [ ] **Step 3: Implement** — append to `models.py`:

```python
EPC_COEFFICIENT = 211
EPC_EFFECTIVE_DIGITS = 215
EPC_NORMAL_CUMULATIVE_ENERGY = 224
EPC_CUMULATIVE_ENERGY_UNIT = 225
EPC_REVERSE_CUMULATIVE_ENERGY = 227
EPC_INSTANTANEOUS_POWER = 231

# ECHONET Lite EPC 0xE1 unit codes. Codes 10-13 MULTIPLY; a 10^-n shortcut
# formula is wrong for them, so this must stay a lookup table.
ENERGY_UNIT_MULTIPLIERS: dict[int, float] = {
    0: 1.0,
    1: 0.1,
    2: 0.01,
    3: 0.001,
    4: 0.0001,
    10: 10.0,
    11: 100.0,
    12: 1000.0,
    13: 10000.0,
}


@dataclass(frozen=True, slots=True)
class EchonetLiteProperty:
    """A raw ECHONET Lite property exposed by a smart meter."""

    name: str
    epc: int
    value: str
    updated_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EchonetLiteProperty:
        """Build from an API payload."""
        return cls(
            name=str(data.get("name") or ""),
            epc=int(data["epc"]),
            value=str(data.get("val") or ""),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass(frozen=True, slots=True)
class SmartMeter:
    """An ECHONET Lite smart meter paired with a Nature Remo E."""

    properties: list[EchonetLiteProperty]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmartMeter:
        """Build from an API payload."""
        return cls(
            properties=[
                EchonetLiteProperty.from_dict(item)
                for item in data.get("echonetlite_properties") or []
                if isinstance(item, dict) and "epc" in item
            ]
        )

    def _int_property(self, epc: int) -> int | None:
        """Return an EPC value as int, or None when absent/invalid."""
        for prop in self.properties:
            if prop.epc == epc:
                try:
                    return int(prop.value)
                except ValueError:
                    return None
        return None

    @property
    def instantaneous_power_w(self) -> int | None:
        """Instantaneous power in watts (negative = exporting)."""
        return self._int_property(EPC_INSTANTANEOUS_POWER)

    def _cumulative_kwh(self, epc: int) -> float | None:
        """Scale a raw cumulative counter into kWh."""
        raw = self._int_property(epc)
        unit_code = self._int_property(EPC_CUMULATIVE_ENERGY_UNIT)
        if raw is None or unit_code is None:
            return None
        multiplier = ENERGY_UNIT_MULTIPLIERS.get(unit_code)
        if multiplier is None:
            return None
        coefficient = self._int_property(EPC_COEFFICIENT)
        if coefficient is None:
            coefficient = 1
        return round(raw * coefficient * multiplier, 4)

    @property
    def cumulative_energy_kwh(self) -> float | None:
        """Cumulative purchased energy in kWh."""
        return self._cumulative_kwh(EPC_NORMAL_CUMULATIVE_ENERGY)

    @property
    def cumulative_energy_reverse_kwh(self) -> float | None:
        """Cumulative sold energy in kWh."""
        return self._cumulative_kwh(EPC_REVERSE_CUMULATIVE_ENERGY)
```

Add `EchonetLiteProperty`, `SmartMeter`, `ENERGY_UNIT_MULTIPLIERS` to `__init__.py` imports/`__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest lib/aionatureremo/tests -v`
Expected: all pass.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat(lib): add smart meter model with ECHONET energy math

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Library — Appliance model, `get_appliances`, command methods

**Files:**
- Modify: `lib/aionatureremo/src/aionatureremo/models.py`, `lib/aionatureremo/src/aionatureremo/client.py`, `lib/aionatureremo/src/aionatureremo/__init__.py`
- Test: `lib/aionatureremo/tests/test_models.py`, `lib/aionatureremo/tests/test_client.py`

**Interfaces:**
- Produces:
  - `Appliance(id: str, type: str, nickname: str, image: str, device_id: str | None, model: ApplianceModel | None, settings: AirconSettings | None, aircon: Aircon | None, tv: TV | None, light: Light | None, smart_meter: SmartMeter | None, signals: list[Signal])` with `from_dict`
  - Appliance type constants: `APPLIANCE_TYPE_AC = "AC"`, `APPLIANCE_TYPE_TV = "TV"`, `APPLIANCE_TYPE_LIGHT = "LIGHT"`, `APPLIANCE_TYPE_IR = "IR"`, `APPLIANCE_TYPE_SMART_METER = "EL_SMART_METER"`
  - `await client.get_appliances() -> list[Appliance]`
  - `await client.set_aircon_settings(appliance_id, *, operation_mode=None, temperature=None, air_volume=None, air_direction=None, air_direction_h=None, button=None, temperature_unit=None) -> AirconSettings` — only non-`None` kwargs are sent (empty string **is** sent; `button=""` means power on)
  - `await client.send_tv_button(appliance_id, button: str) -> TVState`
  - `await client.send_light_button(appliance_id, button: str) -> LightState`
  - `await client.send_signal(signal_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `test_models.py`:

```python
from aionatureremo import Appliance  # merge into the existing import block


def test_appliance_from_dict_ac() -> None:
    """An AC appliance wires settings, aircon, model and device id."""
    appliance = Appliance.from_dict(
        {
            "id": "appliance-ac-1",
            "type": "AC",
            "nickname": "Living AC",
            "image": "ico_ac_1",
            "device": {"id": "device-1", "name": "Living Remo"},
            "model": {"id": "model-1", "manufacturer": "daikin", "name": "Daikin AC"},
            "settings": {"temp": "26", "mode": "cool", "vol": "auto", "button": ""},
            "aircon": AIRCON_PAYLOAD,
            "signals": [],
        }
    )

    assert appliance.type == "AC"
    assert appliance.device_id == "device-1"
    assert appliance.model is not None
    assert appliance.model.manufacturer == "daikin"
    assert appliance.settings is not None
    assert appliance.settings.mode == "cool"
    assert appliance.aircon is not None
    assert "cool" in appliance.aircon.modes
    assert appliance.tv is None
    assert appliance.smart_meter is None


def test_appliance_from_dict_ir_minimal() -> None:
    """An IR appliance has signals and no sub-objects."""
    appliance = Appliance.from_dict(
        {
            "id": "appliance-ir-1",
            "type": "IR",
            "nickname": "Fan",
            "signals": [{"id": "signal-1", "name": "Power", "image": "ico_io"}],
        }
    )

    assert appliance.device_id is None
    assert appliance.model is None
    assert [s.name for s in appliance.signals] == ["Power"]
```

Append to `test_client.py`:

```python
async def test_get_appliances(client: NatureRemoClient, mock_api: aioresponses) -> None:
    """Appliances endpoint parses into typed Appliance objects."""
    mock_api.get(
        f"{API}/1/appliances",
        payload=[
            {
                "id": "appliance-tv-1",
                "type": "TV",
                "nickname": "Living TV",
                "device": {"id": "device-1"},
                "tv": {"state": {"input": "t"}, "buttons": [{"name": "power"}]},
            }
        ],
    )

    appliances = await client.get_appliances()

    assert appliances[0].type == "TV"
    assert appliances[0].tv is not None
    assert appliances[0].tv.state.input == "t"


async def test_set_aircon_settings(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """Only provided kwargs are form-encoded; empty strings are kept."""
    mock_api.post(
        f"{API}/1/appliances/appliance-ac-1/aircon_settings",
        payload={"temp": "27", "mode": "cool", "vol": "auto", "button": ""},
    )

    settings = await client.set_aircon_settings(
        "appliance-ac-1",
        operation_mode="cool",
        temperature="27",
        air_volume="auto",
        button="",
    )

    assert settings.temperature == "27"
    calls = list(mock_api.requests.values())[0]
    assert calls[0].kwargs["data"] == {
        "operation_mode": "cool",
        "temperature": "27",
        "air_volume": "auto",
        "button": "",
    }


async def test_send_tv_button(client: NatureRemoClient, mock_api: aioresponses) -> None:
    """TV button POST returns the new TV state."""
    mock_api.post(f"{API}/1/appliances/appliance-tv-1/tv", payload={"input": "bs"})

    state = await client.send_tv_button("appliance-tv-1", "bs")

    assert state.input == "bs"
    calls = list(mock_api.requests.values())[0]
    assert calls[0].kwargs["data"] == {"button": "bs"}


async def test_send_light_button(
    client: NatureRemoClient, mock_api: aioresponses
) -> None:
    """Light button POST returns the new light state."""
    mock_api.post(
        f"{API}/1/appliances/appliance-light-1/light",
        payload={"power": "off", "brightness": "100", "last_button": "off"},
    )

    state = await client.send_light_button("appliance-light-1", "off")

    assert state.power == "off"


async def test_send_signal(client: NatureRemoClient, mock_api: aioresponses) -> None:
    """Signal send POSTs an empty body and returns None."""
    mock_api.post(f"{API}/1/signals/signal-1/send", body="")

    assert await client.send_signal("signal-1") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest lib/aionatureremo/tests -v`
Expected: FAIL — `ImportError: cannot import name 'Appliance'`

- [ ] **Step 3: Implement**

Append to `models.py`:

```python
APPLIANCE_TYPE_AC = "AC"
APPLIANCE_TYPE_TV = "TV"
APPLIANCE_TYPE_LIGHT = "LIGHT"
APPLIANCE_TYPE_IR = "IR"
APPLIANCE_TYPE_SMART_METER = "EL_SMART_METER"


@dataclass(frozen=True, slots=True)
class Appliance:
    """An appliance registered on a Nature Remo device."""

    id: str
    type: str
    nickname: str
    image: str
    device_id: str | None
    model: ApplianceModel | None
    settings: AirconSettings | None
    aircon: Aircon | None
    tv: TV | None
    light: Light | None
    smart_meter: SmartMeter | None
    signals: list[Signal]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Appliance:
        """Build from an API payload; absent sub-objects stay None."""
        device = data.get("device") or {}
        return cls(
            id=str(data["id"]),
            type=str(data.get("type") or ""),
            nickname=str(data.get("nickname") or ""),
            image=str(data.get("image") or ""),
            device_id=str(device["id"]) if device.get("id") else None,
            model=ApplianceModel.from_dict(data["model"]) if data.get("model") else None,
            settings=(
                AirconSettings.from_dict(data["settings"])
                if data.get("settings")
                else None
            ),
            aircon=Aircon.from_dict(data["aircon"]) if data.get("aircon") else None,
            tv=TV.from_dict(data["tv"]) if data.get("tv") else None,
            light=Light.from_dict(data["light"]) if data.get("light") else None,
            smart_meter=(
                SmartMeter.from_dict(data["smart_meter"])
                if data.get("smart_meter")
                else None
            ),
            signals=[
                Signal.from_dict(item)
                for item in data.get("signals") or []
                if isinstance(item, dict) and "id" in item
            ],
        )
```

Append to `NatureRemoClient` in `client.py` (extend the `.models` import with `Appliance`, `AirconSettings`, `LightState`, `TVState`):

```python
    async def get_appliances(self) -> list[Appliance]:
        """Return all appliances on the account."""
        data = await self._request("GET", "/1/appliances")
        return [Appliance.from_dict(item) for item in data]

    async def set_aircon_settings(
        self,
        appliance_id: str,
        *,
        operation_mode: str | None = None,
        temperature: str | None = None,
        air_volume: str | None = None,
        air_direction: str | None = None,
        air_direction_h: str | None = None,
        button: str | None = None,
        temperature_unit: str | None = None,
    ) -> AirconSettings:
        """Update AC settings; only provided fields are sent."""
        params = {
            "operation_mode": operation_mode,
            "temperature": temperature,
            "air_volume": air_volume,
            "air_direction": air_direction,
            "air_direction_h": air_direction_h,
            "button": button,
            "temperature_unit": temperature_unit,
        }
        data = await self._request(
            "POST",
            f"/1/appliances/{appliance_id}/aircon_settings",
            data={key: value for key, value in params.items() if value is not None},
        )
        return AirconSettings.from_dict(data or {})

    async def send_tv_button(self, appliance_id: str, button: str) -> TVState:
        """Press a TV button and return the new TV state."""
        data = await self._request(
            "POST", f"/1/appliances/{appliance_id}/tv", data={"button": button}
        )
        return TVState.from_dict(data or {})

    async def send_light_button(self, appliance_id: str, button: str) -> LightState:
        """Press a light button and return the new light state."""
        data = await self._request(
            "POST", f"/1/appliances/{appliance_id}/light", data={"button": button}
        )
        return LightState.from_dict(data or {})

    async def send_signal(self, signal_id: str) -> None:
        """Send a learned IR signal."""
        await self._request("POST", f"/1/signals/{signal_id}/send")
```

Add to `__init__.py` imports/`__all__`: `Appliance` and the five `APPLIANCE_TYPE_*` constants.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest lib/aionatureremo/tests -v`
Expected: all pass (~24 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat(lib): add Appliance model, get_appliances, command methods

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Integration scaffold — const, coordinator, base entities, manifest, test fixtures

**Files:**
- Create: `custom_components/nature_remo/__init__.py` (docstring only for now), `custom_components/nature_remo/const.py`, `custom_components/nature_remo/coordinator.py`, `custom_components/nature_remo/entity.py`, `custom_components/nature_remo/manifest.json`
- Create: `tests/__init__.py` (empty), `tests/conftest.py`, `tests/fixtures/devices.json`, `tests/fixtures/appliances.json`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Produces:
  - `const.DOMAIN = "nature_remo"`, `const.UPDATE_INTERVAL = timedelta(seconds=60)`
  - `coordinator.NatureRemoData(devices: dict[str, Device], appliances: dict[str, Appliance])`
  - `type NatureRemoConfigEntry = ConfigEntry[NatureRemoCoordinator]`
  - `NatureRemoCoordinator(hass, config_entry, client)` with `.client`, `@callback async_update_appliance(appliance)`, `@callback async_update_device(device)` (optimistic updates)
  - `entity.NatureRemoDeviceEntity(coordinator, device_id)` — `.device: Device` property, device registry info for the Remo hardware
  - `entity.NatureRemoApplianceEntity(coordinator, appliance_id)` — `.appliance: Appliance` property, appliance device linked `via_device` to its Remo
  - Test fixtures: `mock_client` (AsyncMock), `mock_config_entry`, `devices`, `appliances` pytest fixtures; fixture ids `device-remo3-1`, `device-mini-1`, `device-remoe-1`, `appliance-ac-1`, `appliance-tv-1`, `appliance-light-1`, `appliance-ir-1`, `appliance-meter-1`

- [ ] **Step 1: Create integration skeleton files**

`custom_components/nature_remo/__init__.py`:

```python
"""The Nature Remo integration."""
```

`custom_components/nature_remo/const.py`:

```python
"""Constants for the Nature Remo integration."""

from datetime import timedelta

DOMAIN = "nature_remo"
UPDATE_INTERVAL = timedelta(seconds=60)
```

`custom_components/nature_remo/manifest.json` (replace `<GITHUB_OWNER>` with `gh api user --jq .login` output, as in Task 1):

```json
{
  "domain": "nature_remo",
  "name": "Nature Remo",
  "codeowners": ["@<GITHUB_OWNER>"],
  "config_flow": true,
  "documentation": "https://github.com/<GITHUB_OWNER>/home-assistant-nature-remo-integration",
  "integration_type": "hub",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/<GITHUB_OWNER>/home-assistant-nature-remo-integration/issues",
  "loggers": ["aionatureremo"],
  "requirements": ["aionatureremo==0.1.0"],
  "version": "0.1.0"
}
```

`custom_components/nature_remo/coordinator.py`:

```python
"""Update coordinator for the Nature Remo integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aionatureremo import (
    Appliance,
    Device,
    NatureRemoAuthError,
    NatureRemoClient,
    NatureRemoError,
    NatureRemoRateLimitError,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type NatureRemoConfigEntry = ConfigEntry[NatureRemoCoordinator]


@dataclass
class NatureRemoData:
    """Data fetched from the Nature API in one update cycle."""

    devices: dict[str, Device]
    appliances: dict[str, Appliance]


class NatureRemoCoordinator(DataUpdateCoordinator[NatureRemoData]):
    """Poll devices and appliances within the 30 req / 5 min rate budget."""

    config_entry: NatureRemoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: NatureRemoConfigEntry,
        client: NatureRemoClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> NatureRemoData:
        """Fetch devices and appliances (two API calls, sequential)."""
        # Sequential rather than gather: deterministic error attribution and
        # no orphaned-task warnings when the first call fails.
        try:
            devices = await self.client.get_devices()
            appliances = await self.client.get_appliances()
        except NatureRemoAuthError as err:
            raise ConfigEntryAuthFailed(
                "Access token is invalid or was revoked"
            ) from err
        except NatureRemoRateLimitError as err:
            raise UpdateFailed(
                f"Nature API rate limit exceeded (resets at epoch {err.reset})"
            ) from err
        except NatureRemoError as err:
            raise UpdateFailed(
                f"Error communicating with the Nature API: {err}"
            ) from err
        return NatureRemoData(
            devices={device.id: device for device in devices},
            appliances={appliance.id: appliance for appliance in appliances},
        )

    @callback
    def async_update_appliance(self, appliance: Appliance) -> None:
        """Apply an optimistic appliance update from a command response."""
        self.async_set_updated_data(
            NatureRemoData(
                devices=self.data.devices,
                appliances={**self.data.appliances, appliance.id: appliance},
            )
        )

    @callback
    def async_update_device(self, device: Device) -> None:
        """Apply an optimistic device update from a command response."""
        self.async_set_updated_data(
            NatureRemoData(
                devices={**self.data.devices, device.id: device},
                appliances=self.data.appliances,
            )
        )
```

`custom_components/nature_remo/entity.py`:

```python
"""Base entities for the Nature Remo integration."""

from __future__ import annotations

from aionatureremo import Appliance, Device
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NatureRemoCoordinator


class NatureRemoDeviceEntity(CoordinatorEntity[NatureRemoCoordinator]):
    """An entity belonging to a Nature Remo hardware device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NatureRemoCoordinator, device_id: str) -> None:
        """Initialize with device registry info for the Remo hardware."""
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data.devices[device_id]
        firmware = device.firmware_version
        model, _, sw_version = firmware.partition("/")
        device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device.name,
            manufacturer="Nature",
            model=model or None,
            sw_version=sw_version or None,
            serial_number=device.serial_number,
            configuration_url="https://home.nature.global/",
        )
        if device.mac_address:
            device_info["connections"] = {
                (CONNECTION_NETWORK_MAC, device.mac_address)
            }
        self._attr_device_info = device_info

    @property
    def device(self) -> Device:
        """Return the current device data."""
        return self.coordinator.data.devices[self._device_id]

    @property
    def available(self) -> bool:
        """Unavailable when the device disappears from the account."""
        return super().available and self._device_id in self.coordinator.data.devices


class NatureRemoApplianceEntity(CoordinatorEntity[NatureRemoCoordinator]):
    """An entity belonging to an appliance controlled through a Remo."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize with an appliance device linked to its Remo."""
        super().__init__(coordinator)
        self._appliance_id = appliance_id
        appliance = coordinator.data.appliances[appliance_id]
        model = appliance.model
        device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance_id)},
            name=appliance.nickname,
            manufacturer=model.manufacturer if model else None,
            model=(model.name or model.remote_name) if model else None,
        )
        if appliance.device_id:
            device_info["via_device"] = (DOMAIN, appliance.device_id)
        self._attr_device_info = device_info

    @property
    def appliance(self) -> Appliance:
        """Return the current appliance data."""
        return self.coordinator.data.appliances[self._appliance_id]

    @property
    def available(self) -> bool:
        """Unavailable when the appliance disappears from the account."""
        return (
            super().available
            and self._appliance_id in self.coordinator.data.appliances
        )
```

- [ ] **Step 2: Create test fixtures**

`tests/fixtures/devices.json`:

```json
[
  {
    "id": "device-remo3-1",
    "name": "Living Remo",
    "temperature_offset": 0,
    "humidity_offset": 0,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2026-07-18T07:59:30Z",
    "firmware_version": "Remo/1.14.8",
    "mac_address": "ab:cd:ef:12:34:56",
    "bt_mac_address": "ab:cd:ef:12:34:57",
    "serial_number": "1W123456789012",
    "newest_events": {
      "te": { "val": 26.4, "created_at": "2026-07-18T07:59:00Z" },
      "hu": { "val": 52, "created_at": "2026-07-18T07:59:00Z" },
      "il": { "val": 123.4, "created_at": "2026-07-18T07:58:00Z" },
      "mo": { "val": 1, "created_at": "2026-07-18T07:50:00Z" }
    }
  },
  {
    "id": "device-mini-1",
    "name": "Bedroom Remo mini",
    "temperature_offset": 1,
    "humidity_offset": 0,
    "created_at": "2025-02-01T00:00:00Z",
    "updated_at": "2026-07-18T07:59:30Z",
    "firmware_version": "Remo-mini/1.10.0",
    "mac_address": "ab:cd:ef:12:34:58",
    "serial_number": "2W123456789012",
    "newest_events": {
      "te": { "val": 24.0, "created_at": "2026-07-18T07:59:10Z" }
    }
  },
  {
    "id": "device-remoe-1",
    "name": "Remo E lite",
    "temperature_offset": 0,
    "humidity_offset": 0,
    "created_at": "2025-03-01T00:00:00Z",
    "updated_at": "2026-07-18T07:59:30Z",
    "firmware_version": "Remo-E-lite/1.7.2",
    "mac_address": "ab:cd:ef:12:34:59",
    "serial_number": "4W123456789012",
    "newest_events": {}
  }
]
```

`tests/fixtures/appliances.json`:

```json
[
  {
    "id": "appliance-ac-1",
    "device": { "id": "device-remo3-1", "name": "Living Remo" },
    "model": {
      "id": "model-ac-1",
      "country": "JP",
      "manufacturer": "daikin",
      "remote_name": "ARC478A30",
      "series": "Daikin AC",
      "name": "Daikin AC 001",
      "image": "ico_ac_1"
    },
    "type": "AC",
    "nickname": "Living AC",
    "image": "ico_ac_1",
    "settings": {
      "temp": "26",
      "temp_unit": "c",
      "mode": "cool",
      "vol": "auto",
      "dir": "swing",
      "dirh": "",
      "button": "",
      "updated_at": "2026-07-18T06:00:00Z"
    },
    "aircon": {
      "range": {
        "modes": {
          "cool": {
            "temp": ["24", "25", "26", "27", "28"],
            "vol": ["1", "2", "3", "auto"],
            "dir": ["1", "2", "swing", "auto"],
            "dirh": ["1", "2", "3", "swing"]
          },
          "warm": {
            "temp": ["18", "19", "20", "21", "22"],
            "vol": ["1", "2", "3", "auto"],
            "dir": ["1", "2", "swing", "auto"],
            "dirh": []
          },
          "dry": { "temp": [], "vol": ["auto"], "dir": [], "dirh": [] },
          "blow": { "temp": [], "vol": ["1", "2", "auto"], "dir": [], "dirh": [] },
          "auto": {
            "temp": ["-2", "-1", "0", "+1", "+2"],
            "vol": ["auto"],
            "dir": [],
            "dirh": []
          }
        },
        "fixedButtons": ["power-off"]
      },
      "tempUnit": "c"
    },
    "signals": []
  },
  {
    "id": "appliance-tv-1",
    "device": { "id": "device-remo3-1", "name": "Living Remo" },
    "model": {
      "id": "model-tv-1",
      "country": "JP",
      "manufacturer": "sony",
      "remote_name": "RM-JD030",
      "series": "Sony TV",
      "name": "Sony TV 001",
      "image": "ico_tv"
    },
    "type": "TV",
    "nickname": "Living TV",
    "image": "ico_tv",
    "tv": {
      "state": { "input": "t" },
      "buttons": [
        { "name": "power", "image": "ico_io", "label": "TV_power" },
        { "name": "input", "image": "ico_input", "label": "TV_input" },
        { "name": "t", "image": "ico_t", "label": "TV_t" },
        { "name": "bs", "image": "ico_bs", "label": "TV_bs" },
        { "name": "cs", "image": "ico_cs", "label": "TV_cs" },
        { "name": "vol-up", "image": "ico_vol_up", "label": "TV_vol_up" },
        { "name": "vol-down", "image": "ico_vol_down", "label": "TV_vol_down" },
        { "name": "mute", "image": "ico_mute", "label": "TV_mute" },
        { "name": "ch-up", "image": "ico_ch_up", "label": "TV_ch_up" },
        { "name": "ch-down", "image": "ico_ch_down", "label": "TV_ch_down" }
      ]
    },
    "signals": []
  },
  {
    "id": "appliance-light-1",
    "device": { "id": "device-mini-1", "name": "Bedroom Remo mini" },
    "model": {
      "id": "model-light-1",
      "country": "JP",
      "manufacturer": "panasonic",
      "remote_name": "HK9493",
      "series": "Panasonic Light",
      "name": "Panasonic Light 001",
      "image": "ico_light"
    },
    "type": "LIGHT",
    "nickname": "Bedroom Light",
    "image": "ico_light",
    "light": {
      "state": { "brightness": "100", "power": "on", "last_button": "on" },
      "buttons": [
        { "name": "on", "image": "ico_on", "label": "Light_on" },
        { "name": "off", "image": "ico_off", "label": "Light_off" },
        { "name": "night", "image": "ico_light_night", "label": "Light_night" },
        { "name": "on-100", "image": "ico_light_all", "label": "Light_all" },
        { "name": "bright-up", "image": "ico_arrow_top", "label": "Light_bright_up" },
        { "name": "bright-down", "image": "ico_arrow_bottom", "label": "Light_bright_down" }
      ]
    },
    "signals": []
  },
  {
    "id": "appliance-ir-1",
    "device": { "id": "device-remo3-1", "name": "Living Remo" },
    "model": null,
    "type": "IR",
    "nickname": "Fan",
    "image": "ico_ir",
    "signals": [
      { "id": "signal-1", "name": "Power", "image": "ico_io" },
      { "id": "signal-2", "name": "Speed", "image": "ico_arrow_top" }
    ]
  },
  {
    "id": "appliance-meter-1",
    "device": { "id": "device-remoe-1", "name": "Remo E lite" },
    "model": null,
    "type": "EL_SMART_METER",
    "nickname": "Smart meter",
    "image": "ico_smartmeter",
    "smart_meter": {
      "echonetlite_properties": [
        { "name": "coefficient", "epc": 211, "val": "1", "updated_at": "2026-07-18T07:55:00Z" },
        { "name": "cumulative_electric_energy_effective_digits", "epc": 215, "val": "6", "updated_at": "2026-07-18T07:55:00Z" },
        { "name": "normal_direction_cumulative_electric_energy", "epc": 224, "val": "123456", "updated_at": "2026-07-18T07:55:00Z" },
        { "name": "cumulative_electric_energy_unit", "epc": 225, "val": "1", "updated_at": "2026-07-18T07:55:00Z" },
        { "name": "reverse_direction_cumulative_electric_energy", "epc": 227, "val": "1234", "updated_at": "2026-07-18T07:55:00Z" },
        { "name": "measured_instantaneous", "epc": 231, "val": "520", "updated_at": "2026-07-18T07:58:00Z" }
      ]
    },
    "signals": []
  }
]
```

- [ ] **Step 3: Create `tests/conftest.py`** (and empty `tests/__init__.py`)

```python
"""Common fixtures for Nature Remo integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aionatureremo import Appliance, Device, RateLimit, User
from homeassistant.const import CONF_API_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"


def load_json_fixture(name: str) -> list[dict[str, object]]:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
def devices() -> list[Device]:
    """Devices parsed from the fixture payload."""
    return [Device.from_dict(item) for item in load_json_fixture("devices.json")]


@pytest.fixture
def appliances() -> list[Appliance]:
    """Appliances parsed from the fixture payload."""
    return [Appliance.from_dict(item) for item in load_json_fixture("appliances.json")]


@pytest.fixture
def mock_client(devices: list[Device], appliances: list[Appliance]) -> AsyncMock:
    """A mocked NatureRemoClient preloaded with fixture data."""
    client = AsyncMock()
    client.get_user.return_value = User(id="user-1", nickname="Alice")
    client.get_devices.return_value = devices
    client.get_appliances.return_value = appliances
    client.rate_limit = RateLimit(limit=30, remaining=25, reset=1752825600)
    return client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the fixture account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Alice",
        data={CONF_API_TOKEN: "test-token"},
        unique_id="user-1",
    )
```

- [ ] **Step 4: Write the failing coordinator tests** — `tests/test_coordinator.py`:

```python
"""Tests for the Nature Remo coordinator."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import (
    NatureRemoAuthError,
    NatureRemoConnectionError,
    NatureRemoRateLimitError,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.coordinator import NatureRemoCoordinator


@pytest.fixture
def coordinator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> NatureRemoCoordinator:
    """A coordinator wired to the mocked client."""
    mock_config_entry.add_to_hass(hass)
    return NatureRemoCoordinator(hass, mock_config_entry, mock_client)


async def test_update_success(coordinator: NatureRemoCoordinator) -> None:
    """A successful update indexes devices and appliances by id."""
    data = await coordinator._async_update_data()

    assert set(data.devices) == {"device-remo3-1", "device-mini-1", "device-remoe-1"}
    assert set(data.appliances) == {
        "appliance-ac-1",
        "appliance-tv-1",
        "appliance-light-1",
        "appliance-ir-1",
        "appliance-meter-1",
    }


async def test_auth_error_raises_config_entry_auth_failed(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """A 401 from the API triggers reauth."""
    mock_client.get_devices.side_effect = NatureRemoAuthError(401, "bad token")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_rate_limit_raises_update_failed_with_reset(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """A 429 becomes UpdateFailed mentioning the reset epoch."""
    mock_client.get_appliances.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=1752825600
    )

    with pytest.raises(UpdateFailed, match="1752825600"):
        await coordinator._async_update_data()


async def test_connection_error_raises_update_failed(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """Network trouble becomes UpdateFailed."""
    mock_client.get_devices.side_effect = NatureRemoConnectionError("refused")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_optimistic_updates(coordinator: NatureRemoCoordinator) -> None:
    """async_update_appliance/device replace items and push new data."""
    coordinator.async_set_updated_data(await coordinator._async_update_data())

    appliance = replace(
        coordinator.data.appliances["appliance-ac-1"], nickname="Renamed AC"
    )
    coordinator.async_update_appliance(appliance)
    assert coordinator.data.appliances["appliance-ac-1"].nickname == "Renamed AC"

    device = replace(coordinator.data.devices["device-remo3-1"], name="Renamed Remo")
    coordinator.async_update_device(device)
    assert coordinator.data.devices["device-remo3-1"].name == "Renamed Remo"
```

- [ ] **Step 5: Run tests — fixtures parse and coordinator fails first**

Run: `uv run pytest tests/test_coordinator.py -v`
Expected before implementation exists: FAIL at import (`ModuleNotFoundError`/`ImportError`). After creating the Step 1 files: all 5 PASS.

(If the files from Step 1 were created before running, the first run may already pass — acceptable; the point of the run is verifying fixture JSON parses through the real library models.)

- [ ] **Step 6: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`
Expected: all green (library tests + 5 coordinator tests).

```bash
git add -A
git commit -m "feat: add integration scaffold with coordinator and base entities

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Integration setup and unload

**Files:**
- Modify: `custom_components/nature_remo/__init__.py`, `tests/conftest.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `NatureRemoCoordinator`, `NatureRemoConfigEntry` from Task 7.
- Produces:
  - `__init__.PLATFORMS: list[Platform]` (starts empty; platform tasks append to it)
  - `async_setup_entry(hass, entry: NatureRemoConfigEntry) -> bool` storing the coordinator in `entry.runtime_data`
  - `async_unload_entry(hass, entry) -> bool`
  - conftest: `mock_client` now patches `custom_components.nature_remo.NatureRemoClient`; new async fixture `init_integration` returning a set-up `MockConfigEntry`

- [ ] **Step 1: Write the failing tests** — `tests/test_init.py`:

```python
"""Tests for Nature Remo integration setup."""

from unittest.mock import AsyncMock

from aionatureremo import NatureRemoAuthError, NatureRemoConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.coordinator import NatureRemoCoordinator


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, stores a coordinator, and unloads cleanly."""
    assert init_integration.state is ConfigEntryState.LOADED
    coordinator = init_integration.runtime_data
    assert isinstance(coordinator, NatureRemoCoordinator)
    assert "appliance-ac-1" in coordinator.data.appliances

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_on_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A connection failure during first refresh puts the entry in retry."""
    mock_client.get_devices.side_effect = NatureRemoConnectionError("refused")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_auth_error_is_setup_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """An auth failure during first refresh marks the entry as errored."""
    mock_client.get_devices.side_effect = NatureRemoAuthError(401, "bad token")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
```

- [ ] **Step 2: Update `tests/conftest.py`** — make `mock_client` patch the integration and add `init_integration`.

Replace the `mock_client` fixture with (adds the `patch` context; new imports shown):

```python
from collections.abc import Generator
from unittest.mock import AsyncMock, patch
```

```python
@pytest.fixture
def mock_client(
    devices: list[Device], appliances: list[Appliance]
) -> Generator[AsyncMock]:
    """A mocked NatureRemoClient preloaded with fixture data."""
    client = AsyncMock()
    client.get_user.return_value = User(id="user-1", nickname="Alice")
    client.get_devices.return_value = devices
    client.get_appliances.return_value = appliances
    client.rate_limit = RateLimit(limit=30, remaining=25, reset=1752825600)
    with patch(
        "custom_components.nature_remo.NatureRemoClient", return_value=client
    ):
        yield client
```

Append at the end of `tests/conftest.py`:

```python
@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> MockConfigEntry:
    """Set up the integration with the mocked client."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
```

(add `from homeassistant.core import HomeAssistant` to the conftest imports.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -v`
Expected: FAIL — setup returns False / `AttributeError` (no `async_setup_entry`).

- [ ] **Step 4: Implement** — replace `custom_components/nature_remo/__init__.py` with:

```python
"""The Nature Remo integration."""

from __future__ import annotations

from aionatureremo import NatureRemoClient
from homeassistant.const import CONF_API_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> bool:
    """Set up Nature Remo from a config entry."""
    client = NatureRemoClient(
        entry.data[CONF_API_TOKEN], async_get_clientsession(hass)
    )
    coordinator = NatureRemoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_init.py -v`
Expected: 3 passed.

- [ ] **Step 6: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: set up config entry with coordinator in runtime_data

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Config flow — user, reauth, reconfigure + translations

**Files:**
- Create: `custom_components/nature_remo/config_flow.py`, `custom_components/nature_remo/strings.json`, `custom_components/nature_remo/translations/en.json`, `custom_components/nature_remo/translations/ja.json`
- Modify: `tests/conftest.py` (patch the flow's client too)
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `mock_client` / `init_integration` fixtures; `NatureRemoAuthError`, `NatureRemoError`.
- Produces: `NatureRemoConfigFlow` with steps `user`, `reauth`/`reauth_confirm`, `reconfigure`. Entry data: `{CONF_API_TOKEN: str}`; unique_id = Nature user id; title = account nickname.

- [ ] **Step 1: Update `tests/conftest.py`** — the `mock_client` fixture must also patch the flow module. Replace its `with` line:

```python
    with (
        patch(
            "custom_components.nature_remo.NatureRemoClient", return_value=client
        ),
        patch(
            "custom_components.nature_remo.config_flow.NatureRemoClient",
            return_value=client,
        ),
    ):
        yield client
```

- [ ] **Step 2: Write the failing tests** — `tests/test_config_flow.py`:

```python
"""Tests for the Nature Remo config flow."""

from unittest.mock import AsyncMock

import pytest
from aionatureremo import NatureRemoAuthError, NatureRemoConnectionError, User
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN


async def test_user_flow_success(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """The happy path creates an entry titled with the account nickname."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "test-token"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alice"
    assert result["data"] == {CONF_API_TOKEN: "test-token"}
    assert result["result"].unique_id == "user-1"


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (NatureRemoAuthError(401, "bad token"), "invalid_auth"),
        (NatureRemoConnectionError("refused"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    side_effect: Exception,
    error: str,
) -> None:
    """Each failure shows an error and the flow can still finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_client.get_user.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "bad-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.get_user.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "test-token"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_aborts_on_duplicate_account(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same Nature account cannot be added twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "test-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """Reauth replaces the token on the existing entry."""
    result = await init_integration.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert init_integration.data[CONF_API_TOKEN] == "new-token"


async def test_reauth_flow_wrong_account(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """A token for a different Nature account is rejected."""
    result = await init_integration.start_reauth_flow(hass)

    mock_client.get_user.return_value = User(id="user-2", nickname="Bob")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "other-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert init_integration.data[CONF_API_TOKEN] == "test-token"


async def test_reconfigure_flow_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """Reconfigure swaps the token for the same account."""
    result = await init_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "rotated-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data[CONF_API_TOKEN] == "rotated-token"
```

Note: `start_reauth_flow` / `start_reconfigure_flow` are `MockConfigEntry` helpers in current pytest-homeassistant-custom-component. If missing, fall back to `hass.config_entries.flow.async_init(DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data)` (and `"reconfigure"` respectively).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_flow.py -v`
Expected: FAIL — no config flow handler / patch target `config_flow` missing.

- [ ] **Step 4: Implement**

`custom_components/nature_remo/config_flow.py`:

```python
"""Config flow for the Nature Remo integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aionatureremo import NatureRemoAuthError, NatureRemoClient, NatureRemoError, User
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_TOKEN_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_TOKEN): str})


class NatureRemoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Nature Remo config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def _async_validate(
        self, token: str, errors: dict[str, str]
    ) -> User | None:
        """Validate the token, filling errors on failure."""
        client = NatureRemoClient(token, async_get_clientsession(self.hass))
        try:
            return await client.get_user()
        except NatureRemoAuthError:
            errors["base"] = "invalid_auth"
        except NatureRemoError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating the access token")
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the personal access token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user = await self._async_validate(user_input[CONF_API_TOKEN], errors)
            if user is not None:
                await self.async_set_unique_id(user.id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user.nickname, data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=STEP_TOKEN_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after an authentication failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a replacement token for the same account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user = await self._async_validate(user_input[CONF_API_TOKEN], errors)
            if user is not None:
                await self.async_set_unique_id(user.id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user replace the token from the UI."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user = await self._async_validate(user_input[CONF_API_TOKEN], errors)
            if user is not None:
                await self.async_set_unique_id(user.id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
        )
```

`custom_components/nature_remo/strings.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "description": "Enter a personal access token issued at [home.nature.global](https://home.nature.global/).",
        "data": {
          "api_token": "Access token"
        },
        "data_description": {
          "api_token": "Personal access token for the Nature account."
        }
      },
      "reauth_confirm": {
        "description": "The access token is no longer valid. Issue a new token at [home.nature.global](https://home.nature.global/) and enter it here.",
        "data": {
          "api_token": "Access token"
        },
        "data_description": {
          "api_token": "Personal access token for the same Nature account."
        }
      },
      "reconfigure": {
        "description": "Replace the access token for this Nature account.",
        "data": {
          "api_token": "Access token"
        },
        "data_description": {
          "api_token": "Personal access token for the same Nature account."
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect",
      "invalid_auth": "Invalid authentication",
      "unknown": "Unexpected error"
    },
    "abort": {
      "already_configured": "Account is already configured",
      "reauth_successful": "Re-authentication was successful",
      "reconfigure_successful": "Re-configuration was successful",
      "wrong_account": "The token belongs to a different Nature account"
    }
  }
}
```

`custom_components/nature_remo/translations/en.json`: identical content to `strings.json` (custom integrations serve translations from this file; keep the two in sync in every later task that touches strings).

`custom_components/nature_remo/translations/ja.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "description": "[home.nature.global](https://home.nature.global/) で発行したアクセストークンを入力してください。",
        "data": {
          "api_token": "アクセストークン"
        },
        "data_description": {
          "api_token": "Nature アカウントの個人アクセストークン。"
        }
      },
      "reauth_confirm": {
        "description": "アクセストークンが無効になりました。[home.nature.global](https://home.nature.global/) で新しいトークンを発行して入力してください。",
        "data": {
          "api_token": "アクセストークン"
        },
        "data_description": {
          "api_token": "同じ Nature アカウントの個人アクセストークン。"
        }
      },
      "reconfigure": {
        "description": "この Nature アカウントのアクセストークンを差し替えます。",
        "data": {
          "api_token": "アクセストークン"
        },
        "data_description": {
          "api_token": "同じ Nature アカウントの個人アクセストークン。"
        }
      }
    },
    "error": {
      "cannot_connect": "接続に失敗しました",
      "invalid_auth": "認証情報が無効です",
      "unknown": "予期しないエラーが発生しました"
    },
    "abort": {
      "already_configured": "このアカウントはすでに設定されています",
      "reauth_successful": "再認証に成功しました",
      "reconfigure_successful": "再設定に成功しました",
      "wrong_account": "トークンが別の Nature アカウントのものです"
    }
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_flow.py -v`
Expected: 8 passed (1 + 3 parametrized + 4).

Also add the reauth-trigger assertion to `tests/test_init.py` now that the flow exists — append to `test_setup_auth_error_is_setup_error`:

```python
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)
```

Run: `uv run pytest tests/test_init.py -v`
Expected: 3 passed.

- [ ] **Step 6: Check config-flow coverage (must be 100%)**

Run: `uv run pytest tests/test_config_flow.py --cov=custom_components.nature_remo.config_flow --cov-report=term-missing`
Expected: `config_flow.py` at 100%. If any line is missed, add a test for it before continuing (this is a hard Bronze requirement).

- [ ] **Step 7: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add config flow with reauth and reconfigure

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Sensor platform — Remo device sensors (te/hu/il/mo)

**Files:**
- Create: `custom_components/nature_remo/sensor.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS), `custom_components/nature_remo/strings.json`, `custom_components/nature_remo/translations/en.json`, `custom_components/nature_remo/translations/ja.json`
- Test: `tests/test_sensor.py`

**Interfaces:**
- Consumes: `NatureRemoDeviceEntity`, `NatureRemoConfigEntry`, fixtures from Task 7.
- Produces: sensors with unique_ids `{device_id}_temperature`, `{device_id}_humidity`, `{device_id}_illuminance`, `{device_id}_last_motion`; entities are created **per event key present** and new ones are added dynamically via a coordinator listener (`_sync_entities` pattern reused by every later platform task).

- [ ] **Step 1: Write the failing tests** — `tests/test_sensor.py`:

```python
"""Tests for the Nature Remo sensor platform."""

from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
from aionatureremo import NatureRemoConnectionError
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)


async def test_remo_device_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A Remo 3 exposes temperature, humidity, illuminance and last motion."""
    temperature = hass.states.get("sensor.living_remo_temperature")
    assert temperature is not None
    assert temperature.state == "26.4"
    assert temperature.attributes["device_class"] == "temperature"
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.attributes["state_class"] == "measurement"

    humidity = hass.states.get("sensor.living_remo_humidity")
    assert humidity is not None
    assert humidity.state == "52.0"
    assert humidity.attributes["device_class"] == "humidity"
    assert humidity.attributes["unit_of_measurement"] == "%"

    illuminance = hass.states.get("sensor.living_remo_illuminance")
    assert illuminance is not None
    assert illuminance.state == "123.4"
    assert "device_class" not in illuminance.attributes
    assert "unit_of_measurement" not in illuminance.attributes

    motion = hass.states.get("sensor.living_remo_last_motion")
    assert motion is not None
    assert motion.state == "2026-07-18T07:50:00+00:00"
    assert motion.attributes["device_class"] == "timestamp"


async def test_sensors_follow_event_presence(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A Remo mini (te only) gets no humidity; Remo E lite gets nothing."""
    assert hass.states.get("sensor.bedroom_remo_mini_temperature") is not None
    assert hass.states.get("sensor.bedroom_remo_mini_humidity") is None
    assert hass.states.get("sensor.bedroom_remo_mini_illuminance") is None
    assert hass.states.get("sensor.bedroom_remo_mini_last_motion") is None
    assert hass.states.get("sensor.remo_e_lite_temperature") is None


async def test_sensors_unavailable_on_update_failure(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A failed poll marks sensors unavailable."""
    mock_client.get_devices.side_effect = NatureRemoConnectionError("refused")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    state = hass.states.get("sensor.living_remo_temperature")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sensor.py -v`
Expected: FAIL — entity states are None (platform not registered).

- [ ] **Step 3: Implement**

`custom_components/nature_remo/sensor.py`:

```python
"""Sensor platform for the Nature Remo integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from aionatureremo import (
    EVENT_HUMIDITY,
    EVENT_ILLUMINATION,
    EVENT_MOVEMENT,
    EVENT_TEMPERATURE,
    Device,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import NatureRemoConfigEntry
from .entity import NatureRemoDeviceEntity

PARALLEL_UPDATES = 0


def _event_value(device: Device, key: str) -> float | None:
    """Return the value of a device event, if present."""
    event = device.events.get(key)
    return event.value if event else None


def _event_timestamp(device: Device, key: str) -> datetime | None:
    """Return the timestamp of a device event, if present."""
    event = device.events.get(key)
    return event.created_at if event else None


@dataclass(frozen=True, kw_only=True)
class NatureRemoDeviceSensorDescription(SensorEntityDescription):
    """Describes a sensor derived from a Remo device event."""

    event_key: str
    value_fn: Callable[[Device], StateType | datetime]


DEVICE_SENSORS: tuple[NatureRemoDeviceSensorDescription, ...] = (
    NatureRemoDeviceSensorDescription(
        key="temperature",
        event_key=EVENT_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda device: _event_value(device, EVENT_TEMPERATURE),
    ),
    NatureRemoDeviceSensorDescription(
        key="humidity",
        event_key=EVENT_HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda device: _event_value(device, EVENT_HUMIDITY),
    ),
    NatureRemoDeviceSensorDescription(
        key="illuminance",
        event_key=EVENT_ILLUMINATION,
        translation_key="illuminance",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _event_value(device, EVENT_ILLUMINATION),
    ),
    NatureRemoDeviceSensorDescription(
        key="last_motion",
        event_key=EVENT_MOVEMENT,
        translation_key="last_motion",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: _event_timestamp(device, EVENT_MOVEMENT),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors, adding new ones as they appear."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[SensorEntity] = []
        for device_id, device in coordinator.data.devices.items():
            for description in DEVICE_SENSORS:
                unique_id = f"{device_id}_{description.key}"
                if unique_id in known or description.event_key not in device.events:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoDeviceSensor(coordinator, device_id, description)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoDeviceSensor(NatureRemoDeviceEntity, SensorEntity):
    """A sensor backed by a Remo device event."""

    entity_description: NatureRemoDeviceSensorDescription

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        device_id: str,
        description: NatureRemoDeviceSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.device)
```

(the import line in this file is `from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator`.)

In `custom_components/nature_remo/__init__.py`, change:

```python
PLATFORMS: list[Platform] = []
```

to:

```python
PLATFORMS: list[Platform] = [Platform.SENSOR]
```

Add to the `"entity"` section of `strings.json` **and** `translations/en.json` (create the `"entity"` top-level key; keep both files in sync):

```json
  "entity": {
    "sensor": {
      "illuminance": { "name": "Illuminance" },
      "last_motion": { "name": "Last motion" }
    }
  }
```

And in `translations/ja.json`:

```json
  "entity": {
    "sensor": {
      "illuminance": { "name": "明るさ" },
      "last_motion": { "name": "最終人感検知" }
    }
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sensor.py tests/test_init.py -v`
Expected: all pass (init tests still green with the platform registered).

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add Remo device sensors (temperature, humidity, illuminance, motion)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Sensor platform — smart meter (power / energy)

**Files:**
- Modify: `custom_components/nature_remo/sensor.py`, `custom_components/nature_remo/strings.json`, `custom_components/nature_remo/translations/en.json`, `custom_components/nature_remo/translations/ja.json`
- Test: `tests/test_sensor.py`

**Interfaces:**
- Consumes: `SmartMeter` helpers (`instantaneous_power_w`, `cumulative_energy_kwh`, `cumulative_energy_reverse_kwh`), `NatureRemoApplianceEntity`.
- Produces: sensors with unique_ids `{appliance_id}_instantaneous_power`, `{appliance_id}_cumulative_energy_normal`, `{appliance_id}_cumulative_energy_reverse`; each is created only when its value is currently computable (missing EPC ⇒ no entity, added later if it appears).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_sensor.py`:

```python
from aionatureremo import Appliance  # merge into the existing import block
from tests.conftest import load_json_fixture  # if import fails, use a relative import: from .conftest import load_json_fixture


async def test_smart_meter_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The smart meter exposes signed power and cumulative energies."""
    power = hass.states.get("sensor.smart_meter_power")
    assert power is not None
    assert power.state == "520"
    assert power.attributes["device_class"] == "power"
    assert power.attributes["unit_of_measurement"] == "W"
    assert power.attributes["state_class"] == "measurement"

    purchased = hass.states.get("sensor.smart_meter_purchased_energy")
    assert purchased is not None
    assert purchased.state == "12345.6"
    assert purchased.attributes["device_class"] == "energy"
    assert purchased.attributes["unit_of_measurement"] == "kWh"
    assert purchased.attributes["state_class"] == "total_increasing"

    sold = hass.states.get("sensor.smart_meter_sold_energy")
    assert sold is not None
    assert sold.state == "123.4"
    assert sold.attributes["state_class"] == "total_increasing"


async def test_smart_meter_without_reverse_direction(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A meter without EPC 227 (no solar) gets no sold-energy sensor."""
    payloads = load_json_fixture("appliances.json")
    for payload in payloads:
        if payload["id"] == "appliance-meter-1":
            payload["smart_meter"]["echonetlite_properties"] = [
                prop
                for prop in payload["smart_meter"]["echonetlite_properties"]
                if prop["epc"] != 227
            ]
    mock_client.get_appliances.return_value = [
        Appliance.from_dict(item) for item in payloads
    ]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.smart_meter_purchased_energy") is not None
    assert hass.states.get("sensor.smart_meter_sold_energy") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sensor.py -v`
Expected: the two new tests FAIL (states are None); earlier tests still pass.

- [ ] **Step 3: Implement** — extend `custom_components/nature_remo/sensor.py`:

Add imports: `from aionatureremo import APPLIANCE_TYPE_SMART_METER, SmartMeter`, `from homeassistant.const import UnitOfEnergy, UnitOfPower`, `from .entity import NatureRemoApplianceEntity, NatureRemoDeviceEntity` (extend the existing import), `from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator` (already extended in Task 10).

Add after `DEVICE_SENSORS`:

```python
@dataclass(frozen=True, kw_only=True)
class NatureRemoSmartMeterSensorDescription(SensorEntityDescription):
    """Describes a sensor derived from smart meter properties."""

    value_fn: Callable[[SmartMeter], StateType]


SMART_METER_SENSORS: tuple[NatureRemoSmartMeterSensorDescription, ...] = (
    NatureRemoSmartMeterSensorDescription(
        key="instantaneous_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda meter: meter.instantaneous_power_w,
    ),
    NatureRemoSmartMeterSensorDescription(
        key="cumulative_energy_normal",
        translation_key="cumulative_energy_normal",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda meter: meter.cumulative_energy_kwh,
    ),
    NatureRemoSmartMeterSensorDescription(
        key="cumulative_energy_reverse",
        translation_key="cumulative_energy_reverse",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda meter: meter.cumulative_energy_reverse_kwh,
    ),
)
```

Extend `_sync_entities` inside `async_setup_entry` — after the device loop, before the `if new_entities:` line, add:

```python
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_SMART_METER
                or appliance.smart_meter is None
            ):
                continue
            for meter_description in SMART_METER_SENSORS:
                unique_id = f"{appliance_id}_{meter_description.key}"
                if (
                    unique_id in known
                    or meter_description.value_fn(appliance.smart_meter) is None
                ):
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoSmartMeterSensor(
                        coordinator, appliance_id, meter_description
                    )
                )
```

Add the entity class at the end of the file:

```python
class NatureRemoSmartMeterSensor(NatureRemoApplianceEntity, SensorEntity):
    """A sensor backed by an ECHONET Lite smart meter property."""

    entity_description: NatureRemoSmartMeterSensorDescription

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        description: NatureRemoSmartMeterSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, appliance_id)
        self.entity_description = description
        self._attr_unique_id = f"{appliance_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the current value."""
        meter = self.appliance.smart_meter
        if meter is None:
            return None
        return self.entity_description.value_fn(meter)
```

Add to the `"sensor"` entity section of `strings.json` / `translations/en.json`:

```json
      "cumulative_energy_normal": { "name": "Purchased energy" },
      "cumulative_energy_reverse": { "name": "Sold energy" }
```

`translations/ja.json`:

```json
      "cumulative_energy_normal": { "name": "買電量" },
      "cumulative_energy_reverse": { "name": "売電量" }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sensor.py -v`
Expected: all pass.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add smart meter power and energy sensors

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: Climate platform (AC)

**Files:**
- Create: `custom_components/nature_remo/climate.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS)
- Test: `tests/test_climate.py`

**Interfaces:**
- Consumes: `NatureRemoApplianceEntity`, `coordinator.async_update_appliance`, `client.set_aircon_settings(...)`, `EVENT_TEMPERATURE` / `EVENT_HUMIDITY`.
- Produces: one climate entity per `AC` appliance, unique_id = `{appliance_id}`. Mode mapping `cool→COOL, warm→HEAT, dry→DRY, blow→FAN_ONLY, auto→AUTO` (+ `OFF` via `button="power-off"`). Every command sends the full current settings coerced into the target mode's allowed ranges.

- [ ] **Step 1: Write the failing tests** — `tests/test_climate.py`:

```python
"""Tests for the Nature Remo climate platform."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import AirconSettings, Appliance, NatureRemoRateLimitError
from homeassistant.components.climate import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_SWING_HORIZONTAL_MODE,
    ATTR_SWING_HORIZONTAL_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ATTR_TARGET_TEMP_STEP,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_HORIZONTAL_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTITY = "climate.living_ac"


def _settings(**overrides: str | None) -> AirconSettings:
    """Build an AirconSettings for mock command responses."""
    values: dict[str, str | None] = {
        "temperature": "26",
        "temperature_unit": "c",
        "mode": "cool",
        "volume": "auto",
        "direction": "swing",
        "direction_h": "",
        "button": "",
        "updated_at": None,
    }
    values.update(overrides)
    return AirconSettings(**values)  # type: ignore[arg-type]


async def test_climate_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The AC exposes dynamic modes, ranges and current readings."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 26.4
    assert state.attributes[ATTR_CURRENT_HUMIDITY] == 52
    assert state.attributes[ATTR_TEMPERATURE] == 26.0
    assert state.attributes[ATTR_FAN_MODE] == "auto"
    assert state.attributes[ATTR_SWING_MODE] == "swing"
    assert set(state.attributes[ATTR_HVAC_MODES]) == {
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    }
    assert state.attributes[ATTR_FAN_MODES] == ["1", "2", "3", "auto"]
    assert state.attributes[ATTR_SWING_MODES] == ["1", "2", "swing", "auto"]
    assert state.attributes[ATTR_SWING_HORIZONTAL_MODES] == ["1", "2", "3", "swing"]
    assert state.attributes[ATTR_MIN_TEMP] == 24.0
    assert state.attributes[ATTR_MAX_TEMP] == 28.0
    assert state.attributes[ATTR_TARGET_TEMP_STEP] == 1.0


async def test_climate_off_state_from_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """button == power-off reports HVACMode.OFF."""
    mock_client.get_appliances.return_value = [
        replace(appliance, settings=replace(appliance.settings, button="power-off"))
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """turn_off sends the full settings plus power-off; turn_on restores."""
    mock_client.set_aircon_settings.return_value = _settings(button="power-off")
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    call = mock_client.set_aircon_settings.call_args
    assert call.args == ("appliance-ac-1",)
    assert call.kwargs["button"] == "power-off"
    assert call.kwargs["operation_mode"] == "cool"
    assert call.kwargs["temperature"] == "26"
    assert call.kwargs["air_volume"] == "auto"
    assert call.kwargs["air_direction"] == "swing"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF  # optimistic update from the response

    mock_client.set_aircon_settings.return_value = _settings()
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["button"] == ""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL


async def test_climate_set_temperature(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature snaps the value into the mode's allowed list."""
    mock_client.set_aircon_settings.return_value = _settings(temperature="27")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 27},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["temperature"] == "27"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_TEMPERATURE] == 27.0


async def test_climate_set_temperature_with_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature with hvac_mode switches mode in the same command."""
    mock_client.set_aircon_settings.return_value = _settings(
        mode="warm", temperature="20"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 20, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "20"


async def test_climate_set_hvac_mode_coerces_settings(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """cool(26)→warm snaps the temperature into warm's 18-22 range."""
    mock_client.set_aircon_settings.return_value = _settings(
        mode="warm", temperature="22"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "22"  # 26 snapped to warm's max 22
    assert kwargs["button"] == ""
    assert "air_direction_h" not in kwargs  # warm has no dirh range
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.HEAT


async def test_climate_set_fan_and_swing_modes(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Fan, vertical swing and horizontal swing map to vol/dir/dirh."""
    mock_client.set_aircon_settings.return_value = _settings(volume="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_volume"] == "2"

    mock_client.set_aircon_settings.return_value = _settings(direction="1")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_MODE: "1"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction"] == "1"

    mock_client.set_aircon_settings.return_value = _settings(direction_h="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_HORIZONTAL_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_HORIZONTAL_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction_h"] == "2"


async def test_climate_command_failure_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """API failures surface as HomeAssistantError."""
    mock_client.set_aircon_settings.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=1752825600
    )
    with pytest.raises(HomeAssistantError, match="Living AC"):
        await hass.services.async_call(
            CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_climate.py -v`
Expected: FAIL — `climate.living_ac` does not exist.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/climate.py`:

```python
"""Climate platform for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    EVENT_HUMIDITY,
    EVENT_TEMPERATURE,
    AirconModeRange,
    NatureRemoError,
)
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

NATURE_TO_HVAC: dict[str, HVACMode] = {
    "cool": HVACMode.COOL,
    "warm": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "blow": HVACMode.FAN_ONLY,
    "auto": HVACMode.AUTO,
}
HVAC_TO_NATURE: dict[HVACMode, str] = {
    hvac: nature for nature, hvac in NATURE_TO_HVAC.items()
}

POWER_OFF_BUTTON = "power-off"
POWER_ON_BUTTON = ""


def _parse_float(value: str) -> float | None:
    """Parse a numeric API string ("26", "26.5", "+2"), None when invalid."""
    try:
        return float(value)
    except ValueError:
        return None


def _coerce_to_allowed(current: str, allowed: list[str]) -> str:
    """Keep current if allowed; else snap to the numerically closest value."""
    if current in allowed:
        return current
    target = _parse_float(current)
    if target is not None:
        best: str | None = None
        best_distance = float("inf")
        for candidate in allowed:
            parsed = _parse_float(candidate)
            if parsed is None:
                continue
            distance = abs(parsed - target)
            if distance < best_distance:
                best = candidate
                best_distance = distance
        if best is not None:
            return best
    return allowed[0]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up climate entities for AC appliances."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoClimate] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_AC
                or appliance.aircon is None
                or appliance_id in known
            ):
                continue
            known.add(appliance_id)
            new_entities.append(NatureRemoClimate(coordinator, appliance_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoClimate(NatureRemoApplianceEntity, ClimateEntity):
    """Climate entity backed by a Nature Remo AC appliance."""

    _attr_name = None

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id

    @property
    def _mode_range(self) -> AirconModeRange | None:
        """Return the allowed values for the current operation mode."""
        appliance = self.appliance
        if appliance.aircon is None or appliance.settings is None:
            return None
        return appliance.aircon.modes.get(appliance.settings.mode)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Features depend on what the current mode's ranges offer."""
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if (mode_range := self._mode_range) is None:
            return features
        if mode_range.temperatures:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if mode_range.volumes:
            features |= ClimateEntityFeature.FAN_MODE
        if mode_range.directions:
            features |= ClimateEntityFeature.SWING_MODE
        if mode_range.directions_h:
            features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
        return features

    @property
    def temperature_unit(self) -> str:
        """Celsius unless the appliance reports Fahrenheit."""
        settings = self.appliance.settings
        if settings is not None and settings.temperature_unit == "f":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """OFF plus the modes the AC supports."""
        modes = [HVACMode.OFF]
        if (aircon := self.appliance.aircon) is not None:
            modes.extend(
                NATURE_TO_HVAC[mode] for mode in aircon.modes if mode in NATURE_TO_HVAC
            )
        return modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        """OFF when powered off via button, else the mapped mode."""
        settings = self.appliance.settings
        if settings is None:
            return None
        if settings.button == POWER_OFF_BUTTON:
            return HVACMode.OFF
        return NATURE_TO_HVAC.get(settings.mode)

    @property
    def target_temperature(self) -> float | None:
        """The set temperature; None for modes without one."""
        settings = self.appliance.settings
        if settings is None:
            return None
        return _parse_float(settings.temperature)

    @property
    def target_temperature_step(self) -> float | None:
        """Smallest gap between allowed temperatures."""
        if (mode_range := self._mode_range) is None or not mode_range.temperatures:
            return None
        values = sorted(
            parsed
            for value in mode_range.temperatures
            if (parsed := _parse_float(value)) is not None
        )
        steps = [
            second - first
            for first, second in zip(values, values[1:], strict=False)
            if second > first
        ]
        return min(steps) if steps else 1.0

    @property
    def min_temp(self) -> float:
        """Lowest allowed temperature in the current mode."""
        if (mode_range := self._mode_range) and mode_range.temperatures:
            values = [
                parsed
                for value in mode_range.temperatures
                if (parsed := _parse_float(value)) is not None
            ]
            if values:
                return min(values)
        return super().min_temp

    @property
    def max_temp(self) -> float:
        """Highest allowed temperature in the current mode."""
        if (mode_range := self._mode_range) and mode_range.temperatures:
            values = [
                parsed
                for value in mode_range.temperatures
                if (parsed := _parse_float(value)) is not None
            ]
            if values:
                return max(values)
        return super().max_temp

    def _device_event_value(self, key: str) -> float | None:
        """Read a sensor event from the Remo the appliance is bound to."""
        appliance = self.appliance
        if appliance.device_id is None:
            return None
        device = self.coordinator.data.devices.get(appliance.device_id)
        if device is None:
            return None
        event = device.events.get(key)
        return event.value if event else None

    @property
    def current_temperature(self) -> float | None:
        """Room temperature from the bound Remo."""
        return self._device_event_value(EVENT_TEMPERATURE)

    @property
    def current_humidity(self) -> float | None:
        """Room humidity from the bound Remo."""
        return self._device_event_value(EVENT_HUMIDITY)

    @property
    def fan_mode(self) -> str | None:
        """Current air volume."""
        settings = self.appliance.settings
        return (settings.volume or None) if settings else None

    @property
    def fan_modes(self) -> list[str] | None:
        """Allowed air volumes in the current mode."""
        mode_range = self._mode_range
        if mode_range is None or not mode_range.volumes:
            return None
        return list(mode_range.volumes)

    @property
    def swing_mode(self) -> str | None:
        """Current vertical airflow direction."""
        settings = self.appliance.settings
        return (settings.direction or None) if settings else None

    @property
    def swing_modes(self) -> list[str] | None:
        """Allowed vertical airflow directions in the current mode."""
        mode_range = self._mode_range
        if mode_range is None or not mode_range.directions:
            return None
        return list(mode_range.directions)

    @property
    def swing_horizontal_mode(self) -> str | None:
        """Current horizontal airflow direction."""
        settings = self.appliance.settings
        return (settings.direction_h or None) if settings else None

    @property
    def swing_horizontal_modes(self) -> list[str] | None:
        """Allowed horizontal airflow directions in the current mode."""
        mode_range = self._mode_range
        if mode_range is None or not mode_range.directions_h:
            return None
        return list(mode_range.directions_h)

    async def _async_send(
        self,
        *,
        operation_mode: str | None = None,
        temperature: str | None = None,
        air_volume: str | None = None,
        air_direction: str | None = None,
        air_direction_h: str | None = None,
        button: str = POWER_ON_BUTTON,
    ) -> None:
        """Send the full current settings with the requested overrides."""
        appliance = self.appliance
        settings = appliance.settings
        aircon = appliance.aircon
        mode = operation_mode or (settings.mode if settings else "")
        payload: dict[str, str] = {"button": button}
        if mode:
            payload["operation_mode"] = mode
            mode_range = aircon.modes.get(mode) if aircon else None
            if mode_range is not None:
                current_temp = settings.temperature if settings else ""
                current_vol = settings.volume if settings else ""
                current_dir = settings.direction if settings else ""
                current_dirh = settings.direction_h if settings else ""
                if mode_range.temperatures:
                    payload["temperature"] = _coerce_to_allowed(
                        temperature if temperature is not None else current_temp,
                        mode_range.temperatures,
                    )
                if mode_range.volumes:
                    payload["air_volume"] = _coerce_to_allowed(
                        air_volume if air_volume is not None else current_vol,
                        mode_range.volumes,
                    )
                if mode_range.directions:
                    payload["air_direction"] = _coerce_to_allowed(
                        air_direction if air_direction is not None else current_dir,
                        mode_range.directions,
                    )
                if mode_range.directions_h:
                    payload["air_direction_h"] = _coerce_to_allowed(
                        air_direction_h
                        if air_direction_h is not None
                        else current_dirh,
                        mode_range.directions_h,
                    )
        try:
            new_settings = await self.coordinator.client.set_aircon_settings(
                appliance.id, **payload
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to update {appliance.nickname}: {err}"
            ) from err
        self.coordinator.async_update_appliance(
            replace(appliance, settings=new_settings)
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode; OFF maps to the power-off button."""
        if hvac_mode == HVACMode.OFF:
            await self._async_send(button=POWER_OFF_BUTTON)
            return
        nature_mode = HVAC_TO_NATURE.get(hvac_mode)
        aircon = self.appliance.aircon
        if nature_mode is None or aircon is None or nature_mode not in aircon.modes:
            raise ServiceValidationError(f"Unsupported HVAC mode: {hvac_mode}")
        await self._async_send(operation_mode=nature_mode)

    async def async_turn_on(self) -> None:
        """Power on, restoring the last settings."""
        await self._async_send()

    async def async_turn_off(self) -> None:
        """Power off, keeping the settings for the next power-on."""
        await self._async_send(button=POWER_OFF_BUTTON)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature (optionally with a mode change)."""
        operation_mode: str | None = None
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            if hvac_mode == HVACMode.OFF:
                await self._async_send(button=POWER_OFF_BUTTON)
                return
            operation_mode = HVAC_TO_NATURE.get(hvac_mode)
        temperature = kwargs.get(ATTR_TEMPERATURE)
        await self._async_send(
            operation_mode=operation_mode,
            temperature=None if temperature is None else str(temperature),
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the air volume."""
        mode_range = self._mode_range
        if mode_range is None or fan_mode not in mode_range.volumes:
            raise ServiceValidationError(f"Unsupported fan mode: {fan_mode}")
        await self._async_send(air_volume=fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the vertical airflow direction."""
        mode_range = self._mode_range
        if mode_range is None or swing_mode not in mode_range.directions:
            raise ServiceValidationError(f"Unsupported swing mode: {swing_mode}")
        await self._async_send(air_direction=swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set the horizontal airflow direction."""
        mode_range = self._mode_range
        if mode_range is None or swing_horizontal_mode not in mode_range.directions_h:
            raise ServiceValidationError(
                f"Unsupported horizontal swing mode: {swing_horizontal_mode}"
            )
        await self._async_send(air_direction_h=swing_horizontal_mode)
```

Note on `str(temperature)`: `set_temperature` receives a float (e.g. `27.0`); `_coerce_to_allowed` snaps `"27.0"` to the allowed `"27"` numerically, and to `"26.5"` for half-degree ACs, so the string sent always comes from the appliance's own allowed list.

In `custom_components/nature_remo/__init__.py`:

```python
PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_climate.py -v`
Expected: 8 passed.

If `ATTR_SWING_HORIZONTAL_MODE(S)` / `SERVICE_SET_SWING_HORIZONTAL_MODE` imports fail, they live in `homeassistant.components.climate.const` (available since HA 2024.12) — import from there instead; do NOT drop horizontal swing support.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add climate platform for AC appliances

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Light platform

**Files:**
- Create: `custom_components/nature_remo/light.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS)
- Test: `tests/test_light.py`

**Interfaces:**
- Consumes: `NatureRemoApplianceEntity`, `client.send_light_button(appliance_id, button) -> LightState`, `coordinator.async_update_appliance`.
- Produces: one on/off light per `LIGHT` appliance, unique_id = `{appliance_id}`. With discrete `on`/`off` buttons the state tracks `light.state.power`; with only an `onoff` toggle the entity is `assumed_state`.

- [ ] **Step 1: Write the failing tests** — `tests/test_light.py`:

```python
"""Tests for the Nature Remo light platform."""

from unittest.mock import AsyncMock

from aionatureremo import Appliance, LightState
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import load_json_fixture

ENTITY = "light.bedroom_light"


async def test_light_state_and_turn_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The light reflects state.power and sends discrete on/off buttons."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON
    assert ATTR_ASSUMED_STATE not in state.attributes

    mock_client.send_light_button.return_value = LightState(
        brightness="100", power="off", last_button="off"
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    mock_client.send_light_button.assert_called_once_with("appliance-light-1", "off")
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_OFF  # optimistic update from the response

    mock_client.send_light_button.return_value = LightState(
        brightness="100", power="on", last_button="on"
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.send_light_button.call_args.args == ("appliance-light-1", "on")
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON


async def test_light_toggle_only_model_is_assumed_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A light with only an onoff button toggles and is assumed_state."""
    payloads = load_json_fixture("appliances.json")
    for payload in payloads:
        if payload["id"] == "appliance-light-1":
            payload["light"]["buttons"] = [
                {"name": "onoff", "image": "ico_on", "label": "Light_onoff"}
            ]
    mock_client.get_appliances.return_value = [
        Appliance.from_dict(item) for item in payloads
    ]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_ASSUMED_STATE] is True

    mock_client.send_light_button.return_value = LightState(
        brightness="100", power="off", last_button="onoff"
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    mock_client.send_light_button.assert_called_once_with(
        "appliance-light-1", "onoff"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_light.py -v`
Expected: FAIL — `light.bedroom_light` does not exist.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/light.py`:

```python
"""Light platform for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aionatureremo import APPLIANCE_TYPE_LIGHT, NatureRemoError
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

BUTTON_ON = "on"
BUTTON_OFF = "off"
BUTTON_TOGGLE = "onoff"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up light entities for LIGHT appliances."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoLight] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_LIGHT
                or appliance.light is None
                or appliance_id in known
            ):
                continue
            known.add(appliance_id)
            new_entities.append(NatureRemoLight(coordinator, appliance_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoLight(NatureRemoApplianceEntity, LightEntity):
    """An on/off light backed by a Nature Remo LIGHT appliance."""

    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize; fall back to toggle-only control when needed."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id
        light = coordinator.data.appliances[appliance_id].light
        buttons = {button.name for button in light.buttons} if light else set()
        self._has_discrete_power = BUTTON_ON in buttons and BUTTON_OFF in buttons
        self._attr_assumed_state = not self._has_discrete_power

    @property
    def is_on(self) -> bool | None:
        """Track the power state Nature reports."""
        light = self.appliance.light
        if light is None or light.state.power is None:
            return None
        return light.state.power == "on"

    async def _async_press(self, button: str) -> None:
        """Send a light button and apply the returned state."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_light_button(
                appliance.id, button
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to control {appliance.nickname}: {err}"
            ) from err
        if appliance.light is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, light=replace(appliance.light, state=new_state))
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        await self._async_press(
            BUTTON_ON if self._has_discrete_power else BUTTON_TOGGLE
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_press(
            BUTTON_OFF if self._has_discrete_power else BUTTON_TOGGLE
        )
```

In `custom_components/nature_remo/__init__.py`:

```python
PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.LIGHT, Platform.SENSOR]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_light.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add light platform for LIGHT appliances

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 14: Remote platform (TV)

**Files:**
- Create: `custom_components/nature_remo/remote.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS)
- Test: `tests/test_remote.py`

**Interfaces:**
- Consumes: `NatureRemoApplianceEntity`, `client.send_tv_button(appliance_id, button) -> TVState`.
- Produces: one remote per `TV` appliance, unique_id = `{appliance_id}`, `assumed_state`. `remote.send_command` accepts any button name from `tv.buttons` (honoring `num_repeats` / `delay_secs`); unknown names raise `ServiceValidationError`. `turn_on`/`turn_off` press the `power` button.

- [ ] **Step 1: Write the failing tests** — `tests/test_remote.py`:

```python
"""Tests for the Nature Remo remote platform."""

from unittest.mock import AsyncMock, call

import pytest
from aionatureremo import TVState
from homeassistant.components.remote import (
    ATTR_COMMAND,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DOMAIN as REMOTE_DOMAIN,
    SERVICE_SEND_COMMAND,
)
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTITY = "remote.living_tv"


async def test_remote_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A stateless IR remote reports unknown and assumed_state."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_ASSUMED_STATE] is True


async def test_remote_send_command_with_repeats(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Commands are validated and repeated in order."""
    mock_client.send_tv_button.return_value = TVState(input="t")
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_SEND_COMMAND,
        {
            ATTR_ENTITY_ID: ENTITY,
            ATTR_COMMAND: ["vol-up", "vol-down"],
            ATTR_NUM_REPEATS: 2,
            ATTR_DELAY_SECS: 0,
        },
        blocking=True,
    )
    assert mock_client.send_tv_button.call_args_list == [
        call("appliance-tv-1", "vol-up"),
        call("appliance-tv-1", "vol-down"),
        call("appliance-tv-1", "vol-up"),
        call("appliance-tv-1", "vol-down"),
    ]


async def test_remote_send_unknown_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A button the TV does not have raises and sends nothing."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: ENTITY, ATTR_COMMAND: ["does-not-exist"]},
            blocking=True,
        )
    mock_client.send_tv_button.assert_not_called()


async def test_remote_turn_on_off_press_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """turn_on and turn_off both press the power toggle."""
    mock_client.send_tv_button.return_value = TVState(input="t")
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.send_tv_button.call_args_list == [
        call("appliance-tv-1", "power"),
        call("appliance-tv-1", "power"),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_remote.py -v`
Expected: FAIL — `remote.living_tv` does not exist.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/remote.py`:

```python
"""Remote platform for Nature Remo TV appliances."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from aionatureremo import APPLIANCE_TYPE_TV, NatureRemoError
from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

POWER_BUTTON = "power"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up remote entities for TV appliances."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoTVRemote] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_TV
                or appliance.tv is None
                or appliance_id in known
            ):
                continue
            known.add(appliance_id)
            new_entities.append(NatureRemoTVRemote(coordinator, appliance_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoTVRemote(NatureRemoApplianceEntity, RemoteEntity):
    """A remote sending the TV's IR buttons through the cloud."""

    _attr_name = None
    _attr_assumed_state = True

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize the remote."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id

    @property
    def _button_names(self) -> set[str]:
        """Button names the TV supports."""
        tv = self.appliance.tv
        return {button.name for button in tv.buttons} if tv else set()

    async def _async_press(self, button: str) -> None:
        """Validate and send one button, applying the returned state."""
        if button not in self._button_names:
            raise ServiceValidationError(f"Unknown TV button: {button}")
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_tv_button(
                appliance.id, button
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to control {appliance.nickname}: {err}"
            ) from err
        if appliance.tv is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, tv=replace(appliance.tv, state=new_state))
            )

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send button names, honoring repeats and delays."""
        commands = list(command)
        for name in commands:
            if name not in self._button_names:
                raise ServiceValidationError(f"Unknown TV button: {name}")
        num_repeats: int = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = float(kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS))
        first = True
        for _ in range(num_repeats):
            for name in commands:
                if not first and delay:
                    await asyncio.sleep(delay)
                first = False
                await self._async_press(name)

    async def async_turn_on(self, activity: str | None = None, **kwargs: Any) -> None:
        """Press the power toggle."""
        await self._async_press(POWER_BUTTON)

    async def async_turn_off(self, activity: str | None = None, **kwargs: Any) -> None:
        """Press the power toggle."""
        await self._async_press(POWER_BUTTON)
```

In `custom_components/nature_remo/__init__.py`:

```python
PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.REMOTE,
    Platform.SENSOR,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_remote.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add remote platform for TV appliances

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 15: Select platform (TV input)

**Files:**
- Create: `custom_components/nature_remo/select.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS), `strings.json`, `translations/en.json`, `translations/ja.json`
- Test: `tests/test_select.py`

**Interfaces:**
- Consumes: `NatureRemoApplianceEntity`, `client.send_tv_button`, `TVState`.
- Produces: a select per TV whose buttons include **at least two** of `t` / `bs` / `cs`; unique_id = `{appliance_id}_input`, translation_key `tv_input`. (実機検証ポイント: 入力切替ボタンの実名称が `t/bs/cs` でない機種が見つかったら、この対応表を広げる — spec §9.)

- [ ] **Step 1: Write the failing tests** — `tests/test_select.py`:

```python
"""Tests for the Nature Remo select platform."""

from unittest.mock import AsyncMock

from aionatureremo import Appliance, TVState
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import load_json_fixture

ENTITY = "select.living_tv_input"


async def test_select_state_and_options(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The TV input select mirrors state.input."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "t"
    assert state.attributes[ATTR_OPTIONS] == ["t", "bs", "cs"]


async def test_select_option_sends_button(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Selecting an input presses the matching TV button."""
    mock_client.send_tv_button.return_value = TVState(input="bs")
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "bs"},
        blocking=True,
    )
    mock_client.send_tv_button.assert_called_once_with("appliance-tv-1", "bs")
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "bs"


async def test_select_optimistic_when_response_lacks_input(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A response without input still updates the state optimistically."""
    mock_client.send_tv_button.return_value = TVState(input=None)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "cs"},
        blocking=True,
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "cs"


async def test_no_select_without_input_buttons(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A TV without t/bs/cs buttons gets no input select."""
    payloads = load_json_fixture("appliances.json")
    for payload in payloads:
        if payload["id"] == "appliance-tv-1":
            payload["tv"]["buttons"] = [
                button
                for button in payload["tv"]["buttons"]
                if button["name"] not in ("t", "bs", "cs")
            ]
    mock_client.get_appliances.return_value = [
        Appliance.from_dict(item) for item in payloads
    ]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_select.py -v`
Expected: FAIL — `select.living_tv_input` does not exist.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/select.py`:

```python
"""Select platform for Nature Remo TV input switching."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import APPLIANCE_TYPE_TV, NatureRemoError, TVState
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

# TV input buttons whose names match the state.input values.
INPUT_BUTTONS = ("t", "bs", "cs")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up input selects for TVs that expose input buttons."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoTVInputSelect] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_TV
                or appliance.tv is None
                or appliance_id in known
            ):
                continue
            button_names = {button.name for button in appliance.tv.buttons}
            options = [name for name in INPUT_BUTTONS if name in button_names]
            if len(options) < 2:
                continue
            known.add(appliance_id)
            new_entities.append(
                NatureRemoTVInputSelect(coordinator, appliance_id, options)
            )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoTVInputSelect(NatureRemoApplianceEntity, SelectEntity):
    """Selects the TV input source (terrestrial / BS / CS)."""

    _attr_translation_key = "tv_input"

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        options: list[str],
    ) -> None:
        """Initialize with the inputs this TV exposes."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_input"
        self._attr_options = options

    @property
    def current_option(self) -> str | None:
        """The input Nature reports, if it is one of our options."""
        tv = self.appliance.tv
        current = tv.state.input if tv else None
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Switch input by pressing the matching TV button."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_tv_button(
                appliance.id, option
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to control {appliance.nickname}: {err}"
            ) from err
        if new_state.input is None:
            new_state = TVState(input=option)
        if appliance.tv is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, tv=replace(appliance.tv, state=new_state))
            )
```

In `custom_components/nature_remo/__init__.py`:

```python
PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
]
```

Add to the `"entity"` section of `strings.json` / `translations/en.json`:

```json
    "select": {
      "tv_input": {
        "name": "Input",
        "state": {
          "t": "Terrestrial",
          "bs": "BS",
          "cs": "CS"
        }
      }
    }
```

`translations/ja.json`:

```json
    "select": {
      "tv_input": {
        "name": "入力切替",
        "state": {
          "t": "地上波",
          "bs": "BS",
          "cs": "CS"
        }
      }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_select.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add TV input select

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 16: Button platform (IR signals + extra light buttons)

**Files:**
- Create: `custom_components/nature_remo/button.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS), `strings.json`, `translations/en.json`, `translations/ja.json`
- Test: `tests/test_button.py`

**Interfaces:**
- Consumes: `client.send_signal(signal_id)`, `client.send_light_button`, `NatureRemoApplianceEntity`.
- Produces:
  - One button per learned IR signal on **any** appliance: unique_id `{appliance_id}_signal_{signal_id}`, name = the user-defined signal name.
  - One button per LIGHT button other than `on`/`off`/`onoff`: unique_id `{appliance_id}_button_{name}`; known names get translation_keys (`night`, `on_100`, `on_favorite`, `bright_up`, `bright_down`, `colortemp_up`, `colortemp_down`), unknown names fall back to their API label.

- [ ] **Step 1: Write the failing tests** — `tests/test_button.py`:

```python
"""Tests for the Nature Remo button platform."""

from unittest.mock import AsyncMock

from aionatureremo import LightState
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN


async def test_ir_signal_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Each learned IR signal becomes a button that sends it."""
    state = hass.states.get("button.fan_power")
    assert state is not None
    assert hass.states.get("button.fan_speed") is not None

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.fan_power"},
        blocking=True,
    )
    mock_client.send_signal.assert_called_once_with("signal-1")


async def test_light_extra_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Non-power light buttons become buttons; on/off do not."""
    entity_registry = er.async_get(hass)

    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_night"
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_on"
        )
        is None
    )
    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_off"
        )
        is None
    )

    mock_client.send_light_button.return_value = LightState(
        brightness="0", power="on", last_button="night"
    )
    night_entity = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_night"
    )
    assert night_entity is not None
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: night_entity}, blocking=True
    )
    mock_client.send_light_button.assert_called_once_with(
        "appliance-light-1", "night"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_button.py -v`
Expected: FAIL — button entities do not exist.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/button.py`:

```python
"""Button platform for IR signals and extra light buttons."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import (
    APPLIANCE_TYPE_LIGHT,
    ApplianceButton,
    NatureRemoError,
    Signal,
)
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

LIGHT_POWER_BUTTONS = {"on", "off", "onoff"}
KNOWN_LIGHT_BUTTON_KEYS = {
    "night": "night",
    "on-100": "on_100",
    "on-favorite": "on_favorite",
    "bright-up": "bright_up",
    "bright-down": "bright_down",
    "colortemp-up": "colortemp_up",
    "colortemp-down": "colortemp_down",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons for IR signals and extra light buttons."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[ButtonEntity] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for signal in appliance.signals:
                unique_id = f"{appliance_id}_signal_{signal.id}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoSignalButton(coordinator, appliance_id, signal)
                )
            if appliance.type != APPLIANCE_TYPE_LIGHT or appliance.light is None:
                continue
            for button in appliance.light.buttons:
                if button.name in LIGHT_POWER_BUTTONS:
                    continue
                unique_id = f"{appliance_id}_button_{button.name}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoLightButton(coordinator, appliance_id, button)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoSignalButton(NatureRemoApplianceEntity, ButtonEntity):
    """Sends one learned IR signal."""

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        signal: Signal,
    ) -> None:
        """Initialize from the signal's user-defined name."""
        super().__init__(coordinator, appliance_id)
        self._signal_id = signal.id
        self._attr_unique_id = f"{appliance_id}_signal_{signal.id}"
        self._attr_name = signal.name

    async def async_press(self) -> None:
        """Send the IR signal."""
        try:
            await self.coordinator.client.send_signal(self._signal_id)
        except NatureRemoError as err:
            raise HomeAssistantError(f"Failed to send IR signal: {err}") from err


class NatureRemoLightButton(NatureRemoApplianceEntity, ButtonEntity):
    """Presses one non-power light button (night, brightness, ...)."""

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        button: ApplianceButton,
    ) -> None:
        """Initialize with a translation for known button names."""
        super().__init__(coordinator, appliance_id)
        self._button_name = button.name
        self._attr_unique_id = f"{appliance_id}_button_{button.name}"
        if (translation_key := KNOWN_LIGHT_BUTTON_KEYS.get(button.name)) is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = button.label or button.name

    async def async_press(self) -> None:
        """Press the light button and apply the returned state."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_light_button(
                appliance.id, self._button_name
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to control {appliance.nickname}: {err}"
            ) from err
        if appliance.light is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, light=replace(appliance.light, state=new_state))
            )
```

In `custom_components/nature_remo/__init__.py`:

```python
PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
]
```

Add to the `"entity"` section of `strings.json` / `translations/en.json`:

```json
    "button": {
      "night": { "name": "Night light" },
      "on_100": { "name": "Full brightness" },
      "on_favorite": { "name": "Favorite" },
      "bright_up": { "name": "Brightness up" },
      "bright_down": { "name": "Brightness down" },
      "colortemp_up": { "name": "Color temperature up" },
      "colortemp_down": { "name": "Color temperature down" }
    }
```

`translations/ja.json`:

```json
    "button": {
      "night": { "name": "常夜灯" },
      "on_100": { "name": "全灯" },
      "on_favorite": { "name": "お気に入り" },
      "bright_up": { "name": "明るく" },
      "bright_down": { "name": "暗く" },
      "colortemp_up": { "name": "色温度を上げる" },
      "colortemp_down": { "name": "色温度を下げる" }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_button.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add buttons for IR signals and extra light controls

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 17: Number platform (sensor offsets)

**Files:**
- Create: `custom_components/nature_remo/number.py`
- Modify: `custom_components/nature_remo/__init__.py` (PLATFORMS), `strings.json`, `translations/en.json`, `translations/ja.json`
- Test: `tests/test_number.py`

**Interfaces:**
- Consumes: `client.set_temperature_offset` / `client.set_humidity_offset` (both return the updated `Device`), `coordinator.async_update_device`.
- Produces: config-category numbers `{device_id}_temperature_offset` (−10…10, step 1) and `{device_id}_humidity_offset` (−20…20, step 1), created only when the device measures the corresponding quantity (`te` / `hu` event present). 範囲は実機検証ポイント（spec §9）。

- [ ] **Step 1: Write the failing tests** — `tests/test_number.py`:

```python
"""Tests for the Nature Remo number platform."""

from dataclasses import replace
from unittest.mock import AsyncMock

from aionatureremo import Device
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_offset_numbers_follow_sensor_presence(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Remo 3 gets both offsets; mini (te only) gets no humidity offset."""
    temperature_offset = hass.states.get("number.living_remo_temperature_offset")
    assert temperature_offset is not None
    assert temperature_offset.state == "0.0"
    assert temperature_offset.attributes["min"] == -10
    assert temperature_offset.attributes["max"] == 10
    assert hass.states.get("number.living_remo_humidity_offset") is not None

    mini_temperature = hass.states.get(
        "number.bedroom_remo_mini_temperature_offset"
    )
    assert mini_temperature is not None
    assert mini_temperature.state == "1.0"
    assert hass.states.get("number.bedroom_remo_mini_humidity_offset") is None

    assert hass.states.get("number.remo_e_lite_temperature_offset") is None


async def test_set_temperature_offset(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    devices: list[Device],
) -> None:
    """Setting the number calls the API and applies the response."""
    mock_client.set_temperature_offset.return_value = replace(
        devices[0], temperature_offset=2.0
    )
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: "number.living_remo_temperature_offset",
            ATTR_VALUE: 2,
        },
        blocking=True,
    )
    mock_client.set_temperature_offset.assert_called_once_with("device-remo3-1", 2)
    state = hass.states.get("number.living_remo_temperature_offset")
    assert state is not None
    assert state.state == "2.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_number.py -v`
Expected: FAIL — number entities do not exist.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/number.py`:

```python
"""Number platform for Nature Remo sensor calibration offsets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aionatureremo import (
    EVENT_HUMIDITY,
    EVENT_TEMPERATURE,
    Device,
    NatureRemoClient,
    NatureRemoError,
)
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoDeviceEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NatureRemoNumberDescription(NumberEntityDescription):
    """Describes a device calibration offset."""

    event_key: str
    value_fn: Callable[[Device], float]
    set_fn: Callable[[NatureRemoClient, str, int], Awaitable[Device]]


NUMBERS: tuple[NatureRemoNumberDescription, ...] = (
    NatureRemoNumberDescription(
        key="temperature_offset",
        translation_key="temperature_offset",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=-10,
        native_max_value=10,
        native_step=1,
        event_key=EVENT_TEMPERATURE,
        value_fn=lambda device: device.temperature_offset,
        set_fn=lambda client, device_id, value: client.set_temperature_offset(
            device_id, value
        ),
    ),
    NatureRemoNumberDescription(
        key="humidity_offset",
        translation_key="humidity_offset",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=-20,
        native_max_value=20,
        native_step=1,
        event_key=EVENT_HUMIDITY,
        value_fn=lambda device: device.humidity_offset,
        set_fn=lambda client, device_id, value: client.set_humidity_offset(
            device_id, value
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up offset numbers for devices that measure te/hu."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoOffsetNumber] = []
        for device_id, device in coordinator.data.devices.items():
            for description in NUMBERS:
                unique_id = f"{device_id}_{description.key}"
                if unique_id in known or description.event_key not in device.events:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoOffsetNumber(coordinator, device_id, description)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoOffsetNumber(NatureRemoDeviceEntity, NumberEntity):
    """A sensor calibration offset stored on the Remo."""

    entity_description: NatureRemoNumberDescription

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        device_id: str,
        description: NatureRemoNumberDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float:
        """Return the current offset."""
        return self.entity_description.value_fn(self.device)

    async def async_set_native_value(self, value: float) -> None:
        """Write the offset and apply the returned device state."""
        try:
            device = await self.entity_description.set_fn(
                self.coordinator.client, self._device_id, int(value)
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to update the offset: {err}"
            ) from err
        self.coordinator.async_update_device(device)
```

In `custom_components/nature_remo/__init__.py`:

```python
PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
]
```

Add to the `"entity"` section of `strings.json` / `translations/en.json`:

```json
    "number": {
      "temperature_offset": { "name": "Temperature offset" },
      "humidity_offset": { "name": "Humidity offset" }
    }
```

`translations/ja.json`:

```json
    "number": {
      "temperature_offset": { "name": "温度補正" },
      "humidity_offset": { "name": "湿度補正" }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_number.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add offset number entities

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 18: Dynamic devices — add on poll, remove stale

**Files:**
- Modify: `custom_components/nature_remo/__init__.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: the `_sync_entities` listeners each platform already registered (new entities appear automatically); device registry helpers.
- Produces: stale device-registry entries are removed after each refresh; `async_remove_config_entry_device` allows manual deletion only for devices gone from the account.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_init.py`:

```python
from datetime import timedelta

import homeassistant.util.dt as dt_util
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.nature_remo import async_remove_config_entry_device
from custom_components.nature_remo.const import DOMAIN


async def test_new_appliance_adds_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list,
) -> None:
    """An appliance appearing on a later poll creates its entities."""
    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-meter-1"
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.smart_meter_power") is None

    mock_client.get_appliances.return_value = appliances
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.smart_meter_power") is not None


async def test_stale_device_is_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list,
) -> None:
    """An appliance that disappears is removed from the device registry."""
    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )

    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-ir-1"
    ]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is None
    )


async def test_remove_config_entry_device(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Manual removal is allowed only for devices gone from the account."""
    device_registry = dr.async_get(hass)

    active = device_registry.async_get_device(
        identifiers={(DOMAIN, "appliance-ac-1")}
    )
    assert active is not None
    assert (
        await async_remove_config_entry_device(hass, init_integration, active)
        is False
    )

    ghost = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={(DOMAIN, "ghost-appliance")},
    )
    assert (
        await async_remove_config_entry_device(hass, init_integration, ghost) is True
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -v`
Expected: the three new tests FAIL (`ImportError: cannot import name 'async_remove_config_entry_device'`; stale device persists).

- [ ] **Step 3: Implement** — in `custom_components/nature_remo/__init__.py`:

Add imports:

```python
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
```

Add before `async_setup_entry`:

```python
@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: NatureRemoConfigEntry
) -> None:
    """Drop registry devices that no longer exist on the account."""
    coordinator = entry.runtime_data
    current_ids = set(coordinator.data.devices) | set(coordinator.data.appliances)
    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        identifiers = {
            identifier[1]
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN
        }
        if identifiers and not identifiers & current_ids:
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )
```

In `async_setup_entry`, after `entry.runtime_data = coordinator` and before the platform forward, add:

```python
    _async_remove_stale_devices(hass, entry)
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: _async_remove_stale_devices(hass, entry)
        )
    )
```

Add at the end of the file:

```python
async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing a device only when it is gone from the account."""
    coordinator = entry.runtime_data
    current_ids = set(coordinator.data.devices) | set(coordinator.data.appliances)
    return not any(
        identifier[0] == DOMAIN and identifier[1] in current_ids
        for identifier in device_entry.identifiers
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_init.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add dynamic entity creation and stale device cleanup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 19: Diagnostics

**Files:**
- Create: `custom_components/nature_remo/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `entry.runtime_data` coordinator, `coordinator.client.rate_limit`.
- Produces: `async_get_config_entry_diagnostics(hass, entry) -> dict` with the token, MAC addresses and serial numbers redacted.

- [ ] **Step 1: Write the failing test** — `tests/test_diagnostics.py`:

```python
"""Tests for Nature Remo diagnostics."""

from homeassistant.components.diagnostics import REDACTED
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Diagnostics include data but never the token, MACs or serials."""
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)

    assert diagnostics["entry_data"][CONF_API_TOKEN] == REDACTED
    assert diagnostics["rate_limit"]["limit"] == 30

    devices = diagnostics["devices"]
    assert any(device["id"] == "device-remo3-1" for device in devices)
    for device in devices:
        assert device["mac_address"] in (REDACTED, None)
        assert device["serial_number"] in (REDACTED, None)

    appliances = diagnostics["appliances"]
    assert any(appliance["id"] == "appliance-ac-1" for appliance in appliances)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_diagnostics.py -v`
Expected: FAIL — `ModuleNotFoundError: custom_components.nature_remo.diagnostics`.

- [ ] **Step 3: Implement**

`custom_components/nature_remo/diagnostics.py`:

```python
"""Diagnostics support for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import NatureRemoConfigEntry

TO_REDACT = {CONF_API_TOKEN, "mac_address", "bt_mac_address", "serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NatureRemoConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for the config entry."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "rate_limit": asdict(coordinator.client.rate_limit),
        "devices": async_redact_data(
            [asdict(device) for device in coordinator.data.devices.values()],
            TO_REDACT,
        ),
        "appliances": async_redact_data(
            [asdict(appliance) for appliance in coordinator.data.appliances.values()],
            TO_REDACT,
        ),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_diagnostics.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: add config entry diagnostics with secret redaction

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 20: icons.json and quality_scale.yaml

**Files:**
- Create: `custom_components/nature_remo/icons.json`, `custom_components/nature_remo/quality_scale.yaml`

**Interfaces:**
- Consumes: every translation_key defined in Tasks 10–17.
- Produces: icon translations for all custom-named entities; an honest quality-scale ledger for the future core PR.

- [ ] **Step 1: Create `custom_components/nature_remo/icons.json`**

```json
{
  "entity": {
    "sensor": {
      "illuminance": { "default": "mdi:brightness-6" },
      "last_motion": { "default": "mdi:motion-sensor" }
    },
    "number": {
      "temperature_offset": { "default": "mdi:thermometer-plus" },
      "humidity_offset": { "default": "mdi:water-plus" }
    },
    "select": {
      "tv_input": { "default": "mdi:television-guide" }
    },
    "button": {
      "night": { "default": "mdi:weather-night" },
      "on_100": { "default": "mdi:brightness-7" },
      "on_favorite": { "default": "mdi:star" },
      "bright_up": { "default": "mdi:brightness-6" },
      "bright_down": { "default": "mdi:brightness-4" },
      "colortemp_up": { "default": "mdi:thermometer-chevron-up" },
      "colortemp_down": { "default": "mdi:thermometer-chevron-down" }
    }
  }
}
```

- [ ] **Step 2: Create `custom_components/nature_remo/quality_scale.yaml`**

```yaml
rules:
  # Bronze
  action-setup:
    status: exempt
    comment: The integration does not register custom service actions.
  appropriate-polling: done
  brands: todo
  common-modules: done
  config-flow: done
  config-flow-test-coverage: done
  dependency-transparency: todo # pending the first PyPI release of aionatureremo
  docs-actions:
    status: exempt
    comment: The integration does not register custom service actions.
  docs-high-level-description: todo
  docs-installation-instructions: todo
  docs-removal-instructions: todo
  entity-event-setup:
    status: exempt
    comment: The client library does not emit events; all data arrives via polling.
  entity-unique-id: done
  has-entity-name: done
  runtime-data: done
  test-before-configure: done
  test-before-setup: done
  unique-config-entry: done
  # Silver
  action-exceptions: done
  config-entry-unloading: done
  docs-configuration-parameters: todo
  docs-installation-parameters: todo
  entity-unavailable: done
  integration-owner: done
  log-when-unavailable: done
  parallel-updates: done
  reauthentication-flow: done
  test-coverage: done
  # Gold
  devices: done
  diagnostics: done
  discovery:
    status: exempt
    comment: Cloud-polling service; devices are not discoverable on the local network.
  discovery-update-info:
    status: exempt
    comment: No discovery.
  docs-data-update: todo
  docs-examples: todo
  docs-known-limitations: todo
  docs-supported-devices: todo
  docs-supported-functions: todo
  docs-troubleshooting: todo
  docs-use-cases: todo
  dynamic-devices: done
  entity-category: done
  entity-device-class: done
  entity-disabled-by-default:
    status: exempt
    comment: No noisy or rarely used entities are created.
  entity-translations: done
  exception-translations: todo
  icon-translations: done
  reconfiguration-flow: done
  repair-issues:
    status: exempt
    comment: No repairable issues are raised by this integration.
  stale-devices: done
  # Platinum
  async-dependency: done
  inject-websession: done
  strict-typing: done
```

- [ ] **Step 3: Verify and commit**

Run: `uv run python -c "import json; json.load(open('custom_components/nature_remo/icons.json'))"`
Expected: no output (valid JSON).

Run: `uv run pytest -q`
Expected: all green.

```bash
git add -A
git commit -m "chore: add icon translations and quality scale ledger

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 21: CI workflows, README (EN/JA), core submission guide

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/publish-lib.yml`, `README.md`, `README.ja.md`, `docs/CORE_SUBMISSION.md`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run mypy

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: >
          uv run pytest -q
          --cov=custom_components.nature_remo --cov=aionatureremo
          --cov-report=term-missing

  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master
```

- [ ] **Step 2: Create `.github/workflows/publish-lib.yml`**

```yaml
name: Publish aionatureremo

on:
  push:
    tags: ["aionatureremo-v*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write # PyPI trusted publishing
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv build lib/aionatureremo --out-dir dist
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 3: Create `README.md`**

````markdown
# Nature Remo integration for Home Assistant

A Home Assistant integration for the [Nature Remo](https://nature.global/) smart
remote family, built on the [Nature Remo Cloud API](https://developer.nature.global/)
and aimed at inclusion in Home Assistant core (this repository develops it as a
custom component; see [docs/CORE_SUBMISSION.md](docs/CORE_SUBMISSION.md)).

## Features

| Nature Remo | Home Assistant |
| --- | --- |
| Air conditioner | `climate` — modes, target temperature, fan, vertical & horizontal swing |
| TV | `remote` (every IR button via `remote.send_command`) + input `select` |
| Light | `light` (on/off) + `button` for night / full / brightness buttons |
| Custom IR appliance | one `button` per learned signal |
| Built-in sensors | `sensor` — temperature, humidity, brightness, last motion |
| Sensor calibration | `number` — temperature / humidity offsets |
| Remo E / E lite smart meter | `sensor` — instantaneous power, purchased & sold energy (Energy dashboard ready) |

## Installation (manual, pre-release)

1. Install the client library into your Home Assistant Python environment:
   `pip install aionatureremo` (before the PyPI release: `pip install -e lib/aionatureremo`).
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
````

- [ ] **Step 4: Create `README.ja.md`** — a faithful Japanese translation of README.md (same sections: 概要 / 機能表 / インストール / 設定 / 既知の制限 / 開発 / ライセンス). Translate the prose; keep the tables' HA platform names and commands in English.

- [ ] **Step 5: Create `docs/CORE_SUBMISSION.md`**

```markdown
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

climate → light/remote/select/button/number → diagnostics & dynamic/stale
devices. One platform (or one coherent feature) per PR.

## 5. Documentation PRs

`home-assistant/home-assistant.io`: one page per integration
(`source/_integrations/nature_remo.markdown`), updated alongside each core PR.
The `docs-*` quality-scale rules map to sections of that page.
```

- [ ] **Step 6: Verify and commit**

Run: `uv run pytest -q && uv run ruff check .`
Expected: green.

```bash
git add -A
git commit -m "chore: add CI, publish workflow, READMEs and core submission guide

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 22: Final verification pass

**Files:** none (verification only; fix anything found and commit fixes).

- [ ] **Step 1: Full test suite with coverage**

Run: `uv run pytest --cov=custom_components.nature_remo --cov=aionatureremo --cov-report=term-missing`
Expected: all tests pass. `config_flow.py` **must show 100%**; other integration modules should be ≥95%. Add tests for any gap.

- [ ] **Step 2: Lint and type checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 3: Manifest / structure sanity**

Run: `uv run python -c "import json; m=json.load(open('custom_components/nature_remo/manifest.json')); assert m['iot_class']=='cloud_polling' and m['config_flow'] and m['requirements']==['aionatureremo==0.1.0'] and 'version' in m, m; print('manifest ok')"`
Expected: `manifest ok`

Verify `strings.json` and `translations/en.json` are identical:
Run: `uv run python -c "import json; a=json.load(open('custom_components/nature_remo/strings.json')); b=json.load(open('custom_components/nature_remo/translations/en.json')); assert a==b; print('translations in sync')"`
Expected: `translations in sync`

- [ ] **Step 4: Real-hardware smoke test (requires the user's Remo + token — coordinate with them)**

This is the spec §9 verification list. In a dev HA instance (or the user's HA):
1. `pip install -e lib/aionatureremo` into the HA venv, symlink `custom_components/nature_remo`, restart.
2. Add the integration via UI with a real token; confirm devices/entities appear.
3. Verify: AC on/off + temperature from HA and from the Nature app (state converges within a minute); TV `select` options match real input buttons (adjust `INPUT_BUTTONS` if the API uses different names); offset number ranges accepted by the API; light buttons behave.
4. Record findings in `docs/superpowers/specs/2026-07-18-nature-remo-integration-design.md` §9 and adjust code/fixtures if reality disagrees.

- [ ] **Step 5: Commit any fixes; final state**

```bash
git status   # expect: clean tree, all work committed
git log --oneline   # expect: one commit per task
```

---

## Plan Self-Review Notes

- **Spec coverage:** spec §4 (library) → Tasks 2–6; §5.1–5.5 (setup, flow, coordinator, registry, errors) → Tasks 7–9, 18; §6 entity table → Tasks 10–17 (unique_ids match the spec exactly); §7 tests → per-task tests + Task 22; §8 core strategy → Task 21 (CORE_SUBMISSION.md); §9 verification points → Task 22 Step 4; §10 out-of-scope honored (no EL_* beyond smart meter, no options flow, no OAuth).
- **Deliberate deviations from the spec (approved rationale inline):**
  1. Coordinator fetches sequentially instead of `asyncio.gather` (deterministic error attribution; still 2 calls/cycle) — Task 7.
  2. Platform tests use explicit state assertions instead of syrupy snapshots (avoids depending on snapshot-helper availability outside core; assertions are stronger documentation) — all platform tasks.
  3. Signal buttons are created for signals on **any** appliance type, a superset of the spec's "IR appliances" (signals can exist on other types; harmless and more complete) — Task 16.
  4. Smart-meter energy sensors: created when the value is computable and added later if EPCs appear (spec said "never create when E1 missing"; the dynamic behavior is strictly better) — Task 11.
- **Known environment risks for executors:** exact import paths that may vary by HA version are flagged inline (aioresponses introspection in Task 2, `AddConfigEntryEntitiesCallback`, swing-horizontal constants in Task 12, `start_reauth_flow` helpers in Task 9). In each case the fallback is stated — adapt, don't drop features.









