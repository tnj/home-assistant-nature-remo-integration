"""Select platform for Nature Remo TV input switching."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import APPLIANCE_TYPE_TV, NatureRemoError, TVState
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

# TV input buttons whose names match the state.input values.
INPUT_BUTTONS = ("t", "bs", "cs")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up input selects for TVs that expose input buttons."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoTVInputSelect] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_TV
                or appliance.tv is None
                or appliance_id in known
            ):
                continue
            button_names = {button.name for button in appliance.tv.buttons}
            options = [name for name in INPUT_BUTTONS if name in button_names]
            if len(options) < 2:
                continue
            known.add(appliance_id)
            new_entities.append(
                NatureRemoTVInputSelect(coordinator, appliance_id, options)
            )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoTVInputSelect(NatureRemoApplianceEntity, SelectEntity):
    """Selects the TV input source (terrestrial / BS / CS)."""

    _attr_translation_key = "tv_input"

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        options: list[str],
    ) -> None:
        """Initialize with the inputs this TV exposes."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_input"
        self._attr_options = options

    @property
    def current_option(self) -> str | None:
        """The input Nature reports, if it is one of our options."""
        tv = self.appliance.tv
        current = tv.state.input if tv else None
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Switch input by pressing the matching TV button."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_tv_button(
                appliance.id, option
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to control {appliance.nickname}: {err}"
            ) from err
        if new_state.input is None:
            new_state = TVState(input=option)
        if appliance.tv is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, tv=replace(appliance.tv, state=new_state))
            )
