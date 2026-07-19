"""Button platform for IR signals and extra light buttons."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import (
    APPLIANCE_TYPE_LIGHT,
    ApplianceButton,
    NatureRemoError,
    Signal,
)
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity, command_error_message

PARALLEL_UPDATES = 1

LIGHT_POWER_BUTTONS = {"on", "off", "onoff"}
KNOWN_LIGHT_BUTTON_KEYS = {
    "night": "night",
    "on-100": "on_100",
    "on-favorite": "on_favorite",
    "bright-up": "bright_up",
    "bright-down": "bright_down",
    "colortemp-up": "colortemp_up",
    "colortemp-down": "colortemp_down",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons for IR signals and extra light buttons."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[ButtonEntity] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for signal in appliance.signals:
                unique_id = f"{appliance_id}_signal_{signal.id}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoSignalButton(coordinator, appliance_id, signal)
                )
            if appliance.type != APPLIANCE_TYPE_LIGHT or appliance.light is None:
                continue
            for button in appliance.light.buttons:
                if button.name in LIGHT_POWER_BUTTONS:
                    continue
                unique_id = f"{appliance_id}_button_{button.name}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoLightButton(coordinator, appliance_id, button)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoSignalButton(NatureRemoApplianceEntity, ButtonEntity):
    """Sends one learned IR signal."""

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        signal: Signal,
    ) -> None:
        """Initialize from the signal's user-defined name."""
        super().__init__(coordinator, appliance_id)
        self._signal_id = signal.id
        self._attr_unique_id = f"{appliance_id}_signal_{signal.id}"
        self._attr_name = signal.name

    async def async_press(self) -> None:
        """Send the IR signal."""
        try:
            await self.coordinator.client.send_signal(self._signal_id)
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message("Failed to send IR signal", err)
            ) from err


class NatureRemoLightButton(NatureRemoApplianceEntity, ButtonEntity):
    """Presses one non-power light button (night, brightness, ...)."""

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        button: ApplianceButton,
    ) -> None:
        """Initialize with a translation for known button names."""
        super().__init__(coordinator, appliance_id)
        self._button_name = button.name
        self._attr_unique_id = f"{appliance_id}_button_{button.name}"
        if (translation_key := KNOWN_LIGHT_BUTTON_KEYS.get(button.name)) is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = button.label or button.name

    async def async_press(self) -> None:
        """Press the light button and apply the returned state."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_light_button(
                appliance.id, self._button_name
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err
        if appliance.light is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, light=replace(appliance.light, state=new_state))
            )
