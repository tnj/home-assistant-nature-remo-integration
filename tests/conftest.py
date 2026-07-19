"""Common fixtures for Nature Remo integration tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aionatureremo import Appliance, Device, RateLimit, User
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
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
def mock_client(
    devices: list[Device], appliances: list[Appliance]
) -> Generator[AsyncMock]:
    """A mocked NatureRemoClient preloaded with fixture data."""
    client = AsyncMock()
    client.get_user.return_value = User(id="user-1", nickname="Alice")
    client.get_devices.return_value = devices
    client.get_appliances.return_value = appliances
    client.rate_limit = RateLimit(limit=30, remaining=25, reset=1752825600)
    with patch("custom_components.nature_remo.NatureRemoClient", return_value=client):
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the fixture account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Alice",
        data={CONF_API_TOKEN: "test-token"},
        unique_id="user-1",
    )


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
