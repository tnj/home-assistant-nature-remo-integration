"""Base entities for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    APPLIANCE_TYPE_FLOOR_HEATER,
    AirconExtra,
    Appliance,
    Device,
    NatureRemoError,
    NatureRemoRateLimitError,
)
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
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


def extras_catalog(appliance: Appliance) -> list[AirconExtra]:
    """The appliance's extras catalog: aircon for ACs, floor_heater for FHs."""
    if appliance.type == APPLIANCE_TYPE_FLOOR_HEATER:
        return appliance.floor_heater.extras if appliance.floor_heater else []
    if appliance.type == APPLIANCE_TYPE_AC:
        return appliance.aircon.extras if appliance.aircon else []
    return []


class NatureRemoExtraEntity(NatureRemoApplianceEntity):
    """Base for entities backed by one remote-side extra parameter.

    Extras (e.g. Daikin autoclean/humid/new_sleep, Corona save_energy) are
    remote-side state baked into every transmitted frame; writes send only
    the current power button plus the merged extras so nothing else
    changes. ACs write through aircon_settings; floor heaters through
    floor_heater_settings. Shared by the switch (binary choice), select
    (multi-option choice), and time (type "time") platforms.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        extra: AirconExtra,
    ) -> None:
        """Initialize from the appliance's extras catalog entry."""
        super().__init__(coordinator, appliance_id)
        self._extra_id = extra.id
        self._attr_unique_id = f"{appliance_id}_extra_{extra.id}"

    @property
    def available(self) -> bool:
        """Track the extra's mode-dependent catalog availability.

        The extras catalog is static across operation modes, but each entry's
        ``availability`` flips between "available" and "hidden" with the
        CURRENT mode (probe-verified on a Daikin arc472a82: e.g. powerful is
        available in warm/cool but hidden in dry/blow/auto). Writing a hidden
        extra returns HTTP 200 yet is silently ignored server-side, so the
        entity must go unavailable instead of becoming a silent no-op.
        """
        if not super().available:
            return False
        return any(
            extra.id == self._extra_id and extra.availability == "available"
            for extra in extras_catalog(self.appliance)
        )

    @property
    def _stored_value(self) -> str | None:
        """The extra's stored value, if the API reports one."""
        settings = self.appliance.settings
        if settings is None:
            return None
        return settings.extra.get(self._extra_id)

    async def _async_write_extra(self, value: str) -> None:
        """Write the extra value, preserving the current power button."""
        appliance = self.appliance
        settings = appliance.settings
        new_extra = dict(settings.extra) if settings is not None else {}
        new_extra[self._extra_id] = value
        button = settings.button if settings is not None else None
        try:
            if appliance.type == APPLIANCE_TYPE_FLOOR_HEATER:
                # floor_heater_settings returns the FULL updated Appliance,
                # so the fresh extras catalog replaces the old one wholesale.
                new_appliance = await self.coordinator.client.set_floor_heater_settings(
                    appliance.id, button=button, extra=new_extra
                )
            else:
                new_settings = await self.coordinator.client.set_aircon_settings(
                    appliance.id, button=button, extra=new_extra
                )
                new_appliance = replace(appliance, settings=new_settings)
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to update {appliance.nickname}", err)
            ) from err
        # Apply server truth first so entity state never lies, then verify
        # the echo: a successful write always echoes the extra back
        # (probe-verified), while a write the server silently ignored (the
        # extra went hidden between polls, e.g. right after a mode change)
        # returns 200 with the extra missing from settings.extra.
        self.coordinator.async_update_appliance(new_appliance)
        echoed = (
            new_appliance.settings.extra.get(self._extra_id)
            if new_appliance.settings is not None
            else None
        )
        if echoed != value:
            raise HomeAssistantError(
                f"Failed to update {appliance.nickname}: the API ignored the "
                f"write to '{self._extra_id}' (not available in the current "
                "operation mode)"
            )
