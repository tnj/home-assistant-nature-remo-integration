"""Light platform for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any

from aionatureremo import APPLIANCE_TYPE_LIGHT, NatureRemoError
from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator, NatureRemoData
from .entity import (
    EntityFactory,
    NatureRemoApplianceEntity,
    async_manage_platform_entities,
    command_error_message,
)

PARALLEL_UPDATES = 1

BUTTON_ON = "on"
BUTTON_OFF = "off"
BUTTON_TOGGLE = "onoff"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up light entities for LIGHT appliances."""
    coordinator = entry.runtime_data

    def _build_entities(data: NatureRemoData) -> dict[str, EntityFactory]:
        # The unique_id of a light entity is the bare appliance id.
        return {
            appliance_id: partial(NatureRemoLight, coordinator, appliance_id)
            for appliance_id, appliance in data.appliances.items()
            if appliance.type == APPLIANCE_TYPE_LIGHT and appliance.light is not None
        }

    async_manage_platform_entities(
        hass,
        entry,
        async_add_entities,
        domain=Platform.LIGHT,
        build_entities=_build_entities,
    )


class NatureRemoLight(NatureRemoApplianceEntity, LightEntity):
    """An on/off light backed by a Nature Remo LIGHT appliance."""

    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize; fall back to toggle-only control when needed."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        light = coordinator.data.appliances[appliance_id].light
        buttons = {button.name for button in light.buttons} if light else set()
        self._has_discrete_power = BUTTON_ON in buttons and BUTTON_OFF in buttons
        self._attr_assumed_state = not self._has_discrete_power

    @property
    def is_on(self) -> bool | None:
        """Track the power state Nature reports."""
        light = self.appliance.light
        if light is None or light.state.power is None:
            return None
        return light.state.power == "on"

    async def _async_press(self, button: str) -> None:
        """Send a light button and apply the returned state."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_light_button(
                appliance.id, button
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err
        if appliance.light is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, light=replace(appliance.light, state=new_state))
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        await self._async_press(
            BUTTON_ON if self._has_discrete_power else BUTTON_TOGGLE
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_press(
            BUTTON_OFF if self._has_discrete_power else BUTTON_TOGGLE
        )
