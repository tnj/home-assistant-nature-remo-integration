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
    """Build a coordinator wired to the mocked client."""
    mock_config_entry.add_to_hass(hass)
    return NatureRemoCoordinator(hass, mock_config_entry, mock_client)


async def test_update_success(coordinator: NatureRemoCoordinator) -> None:
    """A successful update indexes devices and appliances by id."""
    data = await coordinator._async_update_data()

    assert set(data.devices) == {"device-remo3-1", "device-mini-1", "device-remoe-1"}
    assert set(data.appliances) == {
        "appliance-ac-1",
        "appliance-ac-2",
        "appliance-tv-1",
        "appliance-light-1",
        "appliance-ir-1",
        "appliance-meter-1",
        "appliance-floorheater-1",
        "appliance-projector-1",
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
