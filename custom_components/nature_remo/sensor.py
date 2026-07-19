"""Sensor platform for the Nature Remo integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from aionatureremo import (
    EVENT_HUMIDITY,
    EVENT_ILLUMINATION,
    EVENT_MOVEMENT,
    EVENT_TEMPERATURE,
    Device,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoDeviceEntity

PARALLEL_UPDATES = 0


def _event_value(device: Device, key: str) -> float | None:
    """Return the value of a device event, if present."""
    event = device.events.get(key)
    return event.value if event else None


def _event_timestamp(device: Device, key: str) -> datetime | None:
    """Return the timestamp of a device event, if present."""
    event = device.events.get(key)
    return event.created_at if event else None


@dataclass(frozen=True, kw_only=True)
class NatureRemoDeviceSensorDescription(SensorEntityDescription):
    """Describes a sensor derived from a Remo device event."""

    event_key: str
    value_fn: Callable[[Device], StateType | datetime]


DEVICE_SENSORS: tuple[NatureRemoDeviceSensorDescription, ...] = (
    NatureRemoDeviceSensorDescription(
        key="temperature",
        event_key=EVENT_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda device: _event_value(device, EVENT_TEMPERATURE),
    ),
    NatureRemoDeviceSensorDescription(
        key="humidity",
        event_key=EVENT_HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda device: _event_value(device, EVENT_HUMIDITY),
    ),
    NatureRemoDeviceSensorDescription(
        key="illuminance",
        event_key=EVENT_ILLUMINATION,
        translation_key="illuminance",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _event_value(device, EVENT_ILLUMINATION),
    ),
    NatureRemoDeviceSensorDescription(
        key="last_motion",
        event_key=EVENT_MOVEMENT,
        translation_key="last_motion",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: _event_timestamp(device, EVENT_MOVEMENT),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors, adding new ones as they appear."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[SensorEntity] = []
        for device_id, device in coordinator.data.devices.items():
            for description in DEVICE_SENSORS:
                unique_id = f"{device_id}_{description.key}"
                if unique_id in known or description.event_key not in device.events:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoDeviceSensor(coordinator, device_id, description)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoDeviceSensor(NatureRemoDeviceEntity, SensorEntity):
    """A sensor backed by a Remo device event."""

    entity_description: NatureRemoDeviceSensorDescription

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        device_id: str,
        description: NatureRemoDeviceSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.device)
