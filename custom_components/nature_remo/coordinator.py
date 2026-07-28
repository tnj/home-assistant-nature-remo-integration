"""Update coordinator for the Nature Remo integration."""

from __future__ import annotations

import asyncio
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
        # Number of successful real polls. Optimistic pushes (see
        # async_update_appliance) notify listeners without touching it, so
        # registry cleanups can tell "the API did not report this id again"
        # from "a command response refreshed one appliance".
        self.poll_count = 0
        self._write_locks: dict[str, asyncio.Lock] = {}
        # Optimistic pushes tagged with the generation they landed in, so a
        # fetch that was already in flight when one arrived can put it back on
        # top of its own (pre-write) snapshot. Both maps are keyed by id, so
        # they stay bounded by the size of the account.
        self._push_generation = 0
        self._pushed_devices: dict[str, tuple[int, Device]] = {}
        self._pushed_appliances: dict[str, tuple[int, Appliance]] = {}

    def async_write_lock(self, appliance_id: str) -> asyncio.Lock:
        """Per-appliance lock serializing settings writes across platforms.

        Every settings payload embeds the full current extras dict (extras
        omitted from a write are cleared server-side), so writes arriving
        from different platforms (climate vs the extras switch/select/time
        entities) must not interleave: the later writer would build its
        payload from pre-write coordinator data and silently revert the
        earlier write. Callers must re-read the appliance from coordinator
        data after acquiring the lock.
        """
        return self._write_locks.setdefault(appliance_id, asyncio.Lock())

    def _merge_pushes_since(
        self, generation: int, data: NatureRemoData
    ) -> NatureRemoData:
        """Re-apply optimistic pushes that landed while this fetch was running.

        ``DataUpdateCoordinator._async_refresh`` assigns ``self.data`` from
        this coroutine's result unconditionally, and ``async_set_updated_data``
        cancels the scheduled refresh but not one already in flight. A write
        completing during the two API calls would therefore be overwritten by
        the pre-write snapshot the fetch started from — and, because the push
        rescheduled the next poll, stay reverted for a full update interval:
        long enough for the next writer to build its payload (settings.extra
        above all) from the rolled-back data and clear the earlier write
        server-side. Entries pushed after this fetch started therefore win
        here; the next poll converges on the server's own view.

        Ids the fetch did not report at all are deliberately not resurrected:
        an appliance deleted in the Nature app must still reach the removal
        grace period.
        """
        if self._push_generation == generation:
            return data
        devices = {
            device_id: device
            for device_id, (pushed_at, device) in self._pushed_devices.items()
            if pushed_at > generation and device_id in data.devices
        }
        appliances = {
            appliance_id: appliance
            for appliance_id, (
                pushed_at,
                appliance,
            ) in self._pushed_appliances.items()
            if pushed_at > generation and appliance_id in data.appliances
        }
        if not devices and not appliances:
            return data
        return NatureRemoData(
            devices={**data.devices, **devices},
            appliances={**data.appliances, **appliances},
        )

    async def _async_update_data(self) -> NatureRemoData:
        """Fetch devices and appliances (two API calls, sequential)."""
        # Only pushes arriving after this point are overlaid back below.
        generation = self._push_generation
        # Sequential rather than gather: deterministic error attribution and
        # no orphaned-task warnings when the first call fails.
        try:
            devices = await self.client.get_devices()
            appliances = await self.client.get_appliances()
        except NatureRemoAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except NatureRemoRateLimitError as err:
            if err.reset is not None:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="update_rate_limited",
                    translation_placeholders={"reset": str(err.reset)},
                ) from err
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except NatureRemoError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.poll_count += 1
        return self._merge_pushes_since(
            generation,
            NatureRemoData(
                devices={device.id: device for device in devices},
                appliances={appliance.id: appliance for appliance in appliances},
            ),
        )

    @callback
    def async_update_appliance(self, appliance: Appliance) -> None:
        """Apply an optimistic appliance update from a command response."""
        self._push_generation += 1
        self._pushed_appliances[appliance.id] = (self._push_generation, appliance)
        self.async_set_updated_data(
            NatureRemoData(
                devices=self.data.devices,
                appliances={**self.data.appliances, appliance.id: appliance},
            )
        )

    @callback
    def async_update_device(self, device: Device) -> None:
        """Apply an optimistic device update from a command response."""
        self._push_generation += 1
        self._pushed_devices[device.id] = (self._push_generation, device)
        self.async_set_updated_data(
            NatureRemoData(
                devices={**self.data.devices, device.id: device},
                appliances=self.data.appliances,
            )
        )
