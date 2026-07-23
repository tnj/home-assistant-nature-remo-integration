"""Switch platform for AC device-specific extra parameters."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aionatureremo import APPLIANCE_TYPE_AC, AirconExtra, NatureRemoError
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for binary AC extra parameters."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoACExtraSwitch] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if appliance.type != APPLIANCE_TYPE_AC or appliance.aircon is None:
                continue
            for extra in appliance.aircon.extras:
                # Only writable, binary on/off extras map onto a switch.
                if extra.availability != "available":
                    continue
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
    """Toggles a remote-side AC extra parameter (e.g. Daikin autoclean).

    Extras are remote-side state baked into every transmitted frame; this
    switch updates the stored value through a partial aircon_settings send
    (current power button + the new extra value), so no other setting is
    touched and the AC's power state is preserved.
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
        try:
            new_settings = await self.coordinator.client.set_aircon_settings(
                appliance.id,
                button=settings.button if settings is not None else None,
                extra=new_extra,
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to update {appliance.nickname}", err)
            ) from err
        self.coordinator.async_update_appliance(
            replace(appliance, settings=new_settings)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the extra."""
        await self._async_set("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the extra."""
        await self._async_set("off")
