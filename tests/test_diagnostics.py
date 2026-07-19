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
