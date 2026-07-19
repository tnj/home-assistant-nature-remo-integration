"""Base entities for the Nature Remo integration."""

from __future__ import annotations

from aionatureremo import (
    Appliance,
    Device,
    NatureRemoError,
    NatureRemoRateLimitError,
)
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NatureRemoCoordinator


def build_remo_device_info(device: Device) -> DeviceInfo:
    """Build device-registry info for a Remo hardware device (spec 5.4).

    Shared by the entity base and the eager device registration in
    ``async_setup_entry`` so both describe the hub identically.
    """
    model, _, sw_version = device.firmware_version.partition("/")
    device_info = DeviceInfo(
        identifiers={(DOMAIN, device.id)},
        name=device.name,
        manufacturer="Nature",
        model=model or None,
        sw_version=sw_version or None,
        serial_number=device.serial_number,
        configuration_url="https://home.nature.global/",
    )
    if device.mac_address:
        device_info["connections"] = {(CONNECTION_NETWORK_MAC, device.mac_address)}
    return device_info


def command_error_message(action: str, err: NatureRemoError) -> str:
    """Compose a command-failure message, surfacing the rate-limit reset.

    Spec 5.5 requires command failures to include the rate-limit reset epoch
    when the API returns HTTP 429; other errors keep the plain message.
    """
    message = f"{action}: {err}"
    if isinstance(err, NatureRemoRateLimitError) and err.reset is not None:
        message = f"{message} (rate limit resets at epoch {err.reset})"
    return message


class NatureRemoDeviceEntity(CoordinatorEntity[NatureRemoCoordinator]):
    """An entity belonging to a Nature Remo hardware device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NatureRemoCoordinator, device_id: str) -> None:
        """Initialize with device registry info for the Remo hardware."""
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data.devices[device_id]
        self._attr_device_info = build_remo_device_info(device)

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
            super().available and self._appliance_id in self.coordinator.data.appliances
        )
