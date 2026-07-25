"""Switch platform for AC / floor heater device-specific extra parameters."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    APPLIANCE_TYPE_FLOOR_HEATER,
    AirconExtra,
    Appliance,
    NatureRemoError,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity, command_error_message

PARALLEL_UPDATES = 1

KNOWN_EXTRA_TRANSLATION_KEYS = {"autoclean": "autoclean"}
_ON_OFF = {"on", "off"}


def _extras_catalog(appliance: Appliance) -> list[AirconExtra]:
    """The appliance's extras catalog: aircon for ACs, floor_heater for FHs."""
    if appliance.type == APPLIANCE_TYPE_FLOOR_HEATER:
        return appliance.floor_heater.extras if appliance.floor_heater else []
    if appliance.type == APPLIANCE_TYPE_AC:
        return appliance.aircon.extras if appliance.aircon else []
    return []


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for binary AC / floor heater extra parameters."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoACExtraSwitch] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for extra in _extras_catalog(appliance):
                # Only binary on/off extras map onto a switch. Non-binary
                # extras (multi-option "choice", optionless "time") are
                # skipped; an empty options list yields an empty set here,
                # which simply fails the comparison. availability is NOT
                # checked: the catalog is static across operation modes and
                # only each entry's availability flips with the current mode
                # (probe-verified), so every binary extra gets an entity and
                # the entity's `available` property tracks the flips.
                if {option.value for option in extra.options} != _ON_OFF:
                    continue
                unique_id = f"{appliance_id}_extra_{extra.id}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoACExtraSwitch(coordinator, appliance_id, extra)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoACExtraSwitch(NatureRemoApplianceEntity, SwitchEntity):
    """Toggles a remote-side extra parameter (e.g. Daikin autoclean).

    Extras are remote-side state baked into every transmitted frame; this
    switch updates the stored value through a partial settings send
    (current power button + the new extra value), so no other setting is
    touched and the appliance's power state is preserved. ACs write through
    aircon_settings; floor heaters through floor_heater_settings.
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
        translation_key = KNOWN_EXTRA_TRANSLATION_KEYS.get(extra.id)
        if translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = extra.text or extra.id

    @property
    def available(self) -> bool:
        """Track the extra's mode-dependent catalog availability.

        The extras catalog is static across operation modes, but each entry's
        ``availability`` flips between "available" and "hidden" with the
        CURRENT mode (probe-verified on a Daikin arc472a82: e.g. powerful is
        available in warm/cool but hidden in dry/blow/auto). Writing a hidden
        extra returns HTTP 200 yet is silently ignored server-side, so the
        switch must go unavailable instead of becoming a silent no-op.
        """
        if not super().available:
            return False
        return any(
            extra.id == self._extra_id and extra.availability == "available"
            for extra in _extras_catalog(self.appliance)
        )

    @property
    def is_on(self) -> bool | None:
        """Return the stored extra value, if the API reports one."""
        settings = self.appliance.settings
        if settings is None:
            return None
        value = settings.extra.get(self._extra_id)
        if value is None:
            return None
        return value == "on"

    async def _async_set(self, value: str) -> None:
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the extra."""
        await self._async_set("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the extra."""
        await self._async_set("off")
