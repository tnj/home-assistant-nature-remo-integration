"""Number platform for Nature Remo sensor calibration offsets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from aionatureremo import (
    EVENT_HUMIDITY,
    EVENT_TEMPERATURE,
    Device,
    NatureRemoClient,
    NatureRemoError,
)
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator, NatureRemoData
from .entity import (
    EntityFactory,
    NatureRemoDeviceEntity,
    async_manage_platform_entities,
    command_error_message,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NatureRemoNumberDescription(NumberEntityDescription):
    """Describes a device calibration offset."""

    event_key: str
    value_fn: Callable[[Device], float]
    set_fn: Callable[[NatureRemoClient, str, int], Awaitable[Device]]


NUMBERS: tuple[NatureRemoNumberDescription, ...] = (
    NatureRemoNumberDescription(
        key="temperature_offset",
        translation_key="temperature_offset",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=-10,
        native_max_value=10,
        native_step=1,
        event_key=EVENT_TEMPERATURE,
        value_fn=lambda device: device.temperature_offset,
        set_fn=lambda client, device_id, value: client.set_temperature_offset(
            device_id, value
        ),
    ),
    NatureRemoNumberDescription(
        key="humidity_offset",
        translation_key="humidity_offset",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=-20,
        native_max_value=20,
        native_step=1,
        event_key=EVENT_HUMIDITY,
        value_fn=lambda device: device.humidity_offset,
        set_fn=lambda client, device_id, value: client.set_humidity_offset(
            device_id, value
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up offset numbers for devices that measure te/hu."""
    coordinator = entry.runtime_data

    def _build_entities(data: NatureRemoData) -> dict[str, EntityFactory]:
        # Only devices that actually report the measurement can calibrate it.
        return {
            f"{device_id}_{description.key}": partial(
                NatureRemoOffsetNumber, coordinator, device_id, description
            )
            for device_id, device in data.devices.items()
            for description in NUMBERS
            if description.event_key in device.events
        }

    def _retain(data: NatureRemoData, unique_id: str) -> bool:
        """Keep an offset whose Remo is here but whose event dropped out.

        Membership above is value-gated on the measurement showing up in this
        poll's payload; the offset itself lives on the Remo and survives a
        missing reading. Only the hub disappearing removes the entity, so a
        transient dropout cannot delete the registry entry.
        """
        return any(
            unique_id == f"{device_id}_{description.key}"
            for device_id in data.devices
            for description in NUMBERS
        )

    async_manage_platform_entities(
        hass,
        entry,
        async_add_entities,
        domain=Platform.NUMBER,
        build_entities=_build_entities,
        retain=_retain,
    )


class NatureRemoOffsetNumber(NatureRemoDeviceEntity, NumberEntity):
    """A sensor calibration offset stored on the Remo."""

    entity_description: NatureRemoNumberDescription

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        device_id: str,
        description: NatureRemoNumberDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float:
        """Return the current offset."""
        return self.entity_description.value_fn(self.device)

    async def async_set_native_value(self, value: float) -> None:
        """Write the offset and apply the returned device state."""
        if not value.is_integer():
            raise ServiceValidationError(f"Offset must be a whole number, got {value}")
        try:
            device = await self.entity_description.set_fn(
                self.coordinator.client, self._device_id, int(value)
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message("Failed to update the offset", err)
            ) from err
        self.coordinator.async_update_device(device)
