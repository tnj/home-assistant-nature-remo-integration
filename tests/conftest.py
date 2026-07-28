"""Common fixtures for Nature Remo integration tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import homeassistant.util.dt as dt_util
import pytest
from aionatureremo import (
    AirconSettings,
    Appliance,
    Device,
    NatureRemoClient,
    RateLimit,
    User,
)
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.nature_remo.const import DOMAIN, UPDATE_INTERVAL

FIXTURES = Path(__file__).parent / "fixtures"

# The living-room AC fixture's settings, i.e. the shape every aircon_settings
# command response starts from (cool, 26 C, autoclean stored on the remote).
LIVING_AC_SETTINGS: dict[str, Any] = {
    "temperature": "26",
    "temperature_unit": "c",
    "mode": "cool",
    "volume": "auto",
    "direction": "swing",
    "direction_h": "",
    "button": "",
    "updated_at": None,
    # The real API echoes remote-side extra state in every response.
    "extra": {"autoclean": "on"},
}


def load_json_fixture(name: str) -> list[dict[str, object]]:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


async def async_poll(hass: HomeAssistant, times: int = 1) -> None:
    """Run `times` real coordinator polls, settling the event loop after each."""
    for _ in range(times):
        async_fire_time_changed(
            hass, dt_util.utcnow() + UPDATE_INTERVAL + timedelta(seconds=1)
        )
        await hass.async_block_till_done()


def aircon_settings(**overrides: Any) -> AirconSettings:
    """Build an AirconSettings command response for the living-room AC."""
    values = {**LIVING_AC_SETTINGS, **overrides}
    # Copy the extras dict so no two responses share one mutable default.
    values["extra"] = dict(values["extra"])
    return AirconSettings(**values)


def bedroom_aircon_settings(**overrides: Any) -> AirconSettings:
    """Build an AirconSettings command response for the bedroom AC.

    Mirrors the appliance-ac-2 fixture (warm, 22 C, powerful stored off) so
    a response only differs from server truth where a test says it does.
    """
    return aircon_settings(
        **{
            "temperature": "22",
            "mode": "warm",
            "direction": "auto",
            "direction_h": "auto",
            "extra": {"powerful": "off"},
            **overrides,
        }
    )


def with_extra_availability(
    appliances: list[Appliance], appliance_id: str, availability: dict[str, str]
) -> list[Appliance]:
    """Rebuild the appliance list with selected extras' availability changed."""
    modified = []
    for appliance in appliances:
        if appliance.id == appliance_id and appliance.aircon is not None:
            aircon = replace(
                appliance.aircon,
                extras=[
                    replace(
                        extra,
                        availability=availability.get(extra.id, extra.availability),
                    )
                    for extra in appliance.aircon.extras
                ],
            )
            modified.append(replace(appliance, aircon=aircon))
        else:
            modified.append(appliance)
    return modified


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
    """Build a mocked NatureRemoClient preloaded with fixture data.

    Specced against the real client so a test stubbing a method the library
    does not have fails loudly instead of asserting against a mock that can
    never be called. ``rate_limit`` is an instance attribute (the spec is the
    class), so it is assigned rather than stubbed — ``spec`` restricts reads,
    not writes.
    """
    client = AsyncMock(spec=NatureRemoClient)
    client.get_user.return_value = User(id="user-1", nickname="Alice")
    client.get_devices.return_value = devices
    client.get_appliances.return_value = appliances
    client.rate_limit = RateLimit(limit=30, remaining=25, reset=1752825600)
    with (
        patch("custom_components.nature_remo.NatureRemoClient", return_value=client),
        patch(
            "custom_components.nature_remo.config_flow.NatureRemoClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Build a config entry for the fixture account."""
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
