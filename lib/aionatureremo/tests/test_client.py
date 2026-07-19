"""Tests for the NatureRemoClient transport layer."""

from collections.abc import AsyncGenerator, Generator

import aiohttp
import pytest
from aionatureremo import (
    NatureRemoApiError,
    NatureRemoAuthError,
    NatureRemoClient,
    NatureRemoConnectionError,
    NatureRemoRateLimitError,
    User,
)
from aioresponses import aioresponses

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
    calls = list(mock_api.requests.values())[0]  # noqa: RUF015
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


async def test_get_devices(client: NatureRemoClient, mock_api: aioresponses) -> None:
    """Devices endpoint parses into a list of Device."""
    mock_api.get(
        f"{API}/1/devices",
        payload=[
            {
                "id": "device-1",
                "name": "Living Remo",
                "firmware_version": "Remo/1.14.8",
                "newest_events": {
                    "te": {"val": 26.4, "created_at": "2026-07-18T07:59:00Z"}
                },
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
    calls = next(iter(mock_api.requests.values()))
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
