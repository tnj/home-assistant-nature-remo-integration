"""Select platform for Nature Remo TV input switching."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import APPLIANCE_TYPE_TV, NatureRemoError, TVState
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity, command_error_message

PARALLEL_UPDATES = 1

# For each state.input code, the candidate button names that switch to it,
# real-world long name first and short legacy name as fallback. Real Remo
# accounts expose the long names (e.g. "input-terrestrial"); some older or
# simulated payloads only have the short codes.
INPUT_SOURCES: dict[str, tuple[str, ...]] = {
    "t": ("input-terrestrial", "t"),
    "bs": ("input-bs", "bs"),
    "cs": ("input-cs", "cs"),
}


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
            button_map: dict[str, str] = {}
            for code, candidates in INPUT_SOURCES.items():
                button = next((c for c in candidates if c in button_names), None)
                if button is not None:
                    button_map[code] = button
            if len(button_map) < 2:
                continue
            known.add(appliance_id)
            new_entities.append(
                NatureRemoTVInputSelect(coordinator, appliance_id, button_map)
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
        button_map: dict[str, str],
    ) -> None:
        """Initialize with the input codes this TV resolves to real buttons."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_input"
        self._button_map = button_map
        self._attr_options = [code for code in INPUT_SOURCES if code in button_map]

    @property
    def current_option(self) -> str | None:
        """The input Nature reports, if it is one of our options."""
        tv = self.appliance.tv
        current = tv.state.input if tv else None
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Switch input by pressing the button resolved for this code."""
        appliance = self.appliance
        button = self._button_map[option]
        try:
            new_state = await self.coordinator.client.send_tv_button(
                appliance.id, button
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err
        if new_state.input is None:
            new_state = TVState(input=option)
        if appliance.tv is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, tv=replace(appliance.tv, state=new_state))
            )
