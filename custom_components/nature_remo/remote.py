"""Remote platform for Nature Remo TV appliances."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from aionatureremo import APPLIANCE_TYPE_TV, NatureRemoError
from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity

PARALLEL_UPDATES = 1

POWER_BUTTON = "power"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up remote entities for TV appliances."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoTVRemote] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_TV
                or appliance.tv is None
                or appliance_id in known
            ):
                continue
            known.add(appliance_id)
            new_entities.append(NatureRemoTVRemote(coordinator, appliance_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoTVRemote(NatureRemoApplianceEntity, RemoteEntity):
    """A remote sending the TV's IR buttons through the cloud."""

    _attr_name = None
    _attr_assumed_state = True

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize the remote."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id

    @property
    def _button_names(self) -> set[str]:
        """Button names the TV supports."""
        tv = self.appliance.tv
        return {button.name for button in tv.buttons} if tv else set()

    async def _async_press(self, button: str) -> None:
        """Validate and send one button, applying the returned state."""
        if button not in self._button_names:
            raise ServiceValidationError(f"Unknown TV button: {button}")
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_tv_button(
                appliance.id, button
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                f"Failed to control {appliance.nickname}: {err}"
            ) from err
        if appliance.tv is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, tv=replace(appliance.tv, state=new_state))
            )

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send button names, honoring repeats and delays."""
        commands = list(command)
        for name in commands:
            if name not in self._button_names:
                raise ServiceValidationError(f"Unknown TV button: {name}")
        num_repeats: int = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = float(kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS))
        first = True
        for _ in range(num_repeats):
            for name in commands:
                if not first and delay:
                    await asyncio.sleep(delay)
                first = False
                await self._async_press(name)

    async def async_turn_on(self, activity: str | None = None, **kwargs: Any) -> None:
        """Press the power toggle."""
        await self._async_press(POWER_BUTTON)

    async def async_turn_off(self, activity: str | None = None, **kwargs: Any) -> None:
        """Press the power toggle."""
        await self._async_press(POWER_BUTTON)
