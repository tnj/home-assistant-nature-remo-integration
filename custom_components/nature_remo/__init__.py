"""The Nature Remo integration."""

from __future__ import annotations

from aionatureremo import NatureRemoClient
from homeassistant.const import CONF_API_TOKEN, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import (
    StaleIdTracker,
    build_appliance_device_info,
    build_remo_device_info,
)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


@callback
def _async_register_devices(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> None:
    """Register every Remo hub and every appliance up front (spec 5.4).

    Appliance entities link to their hub via ``via_device=(DOMAIN, device.id)``,
    but Remo hubs would otherwise only materialize as a side effect of their own
    sensor/number entities. Energy-only hubs (Remo E / E lite) report no such
    events, so their device would never be registered and their appliances would
    dangle. Registering here — before platforms are forwarded — guarantees every
    ``via_device`` target exists regardless of platform setup ordering.

    Appliances are registered from the same builder their entities use, and on
    every poll: a device an entity created keeps the nickname it was created
    with, so re-registering is what makes a rename in the Nature app show up.
    Hubs come first so no ``via_device`` target is missing when it is needed.
    """
    coordinator = entry.runtime_data
    device_registry = dr.async_get(hass)
    for device in coordinator.data.devices.values():
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **build_remo_device_info(device),
        )
    for appliance in coordinator.data.appliances.values():
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **build_appliance_device_info(appliance),
        )


def _async_stale_device_remover(
    hass: HomeAssistant, entry: NatureRemoConfigEntry
) -> CALLBACK_TYPE:
    """Build the per-poll callback dropping devices gone from the account.

    Removing a device takes its entities, its area assignment and every
    automation wired to them along, so it waits for
    ``STALE_POLLS_BEFORE_REMOVAL`` consecutive real polls without the id
    rather than acting on a single truncated response.
    """
    coordinator = entry.runtime_data
    device_registry = dr.async_get(hass)
    stale = StaleIdTracker(coordinator)

    @callback
    def _remove_stale_devices() -> None:
        current_ids = set(coordinator.data.devices) | set(coordinator.data.appliances)
        for device_entry in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            identifiers = {
                identifier[1]
                for identifier in device_entry.identifiers
                if identifier[0] == DOMAIN
            }
            if not identifiers:
                continue
            # Keyed on the registry id: it is stable and unique even for an
            # entry carrying several identifiers.
            if identifiers & current_ids:
                stale.async_seen(device_entry.id)
            elif stale.async_record_miss(device_entry.id):
                device_registry.async_update_device(
                    device_entry.id, remove_config_entry_id=entry.entry_id
                )

    return _remove_stale_devices


async def async_setup_entry(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> bool:
    """Set up Nature Remo from a config entry."""
    client = NatureRemoClient(entry.data[CONF_API_TOKEN], async_get_clientsession(hass))
    coordinator = NatureRemoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    remove_stale_devices = _async_stale_device_remover(hass, entry)
    _async_register_devices(hass, entry)
    remove_stale_devices()
    entry.async_on_unload(
        coordinator.async_add_listener(lambda: _async_register_devices(hass, entry))
    )
    entry.async_on_unload(coordinator.async_add_listener(remove_stale_devices))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


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
