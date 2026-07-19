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
