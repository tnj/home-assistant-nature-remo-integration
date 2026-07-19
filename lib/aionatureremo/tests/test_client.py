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
