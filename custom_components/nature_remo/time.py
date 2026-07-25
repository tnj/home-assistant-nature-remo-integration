"""Time platform for schedule-type AC / floor heater extra parameters."""

from __future__ import annotations

from datetime import time

from aionatureremo import AirconExtra
from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoExtraEntity, extras_catalog

PARALLEL_UPDATES = 1

KNOWN_EXTRA_TRANSLATION_KEYS = {"new_sleep": "new_sleep"}
EXTRA_TYPE_TIME = "time"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up time entities for schedule-type extra parameters."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoExtraTime] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for extra in extras_catalog(appliance):
                # type "time" extras (e.g. Daikin new_sleep) carry an HH:MM
                # value instead of an options list. availability is NOT
                # checked — tracked dynamically by the entity's `available`.
                if extra.type != EXTRA_TYPE_TIME:
                    continue
                unique_id = f"{appliance_id}_extra_{extra.id}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoExtraTime(coordinator, appliance_id, extra)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoExtraTime(NatureRemoExtraEntity, TimeEntity):
    """Sets a schedule-type remote-side extra (e.g. Daikin new_sleep).

    The cloud stores an HH:MM string written as ``extra.$id=HH:MM``
    (probe-verified). The catalog's defaultTime is the remote's default,
    not a stored value, so the state stays unknown until the first write.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        extra: AirconExtra,
    ) -> None:
        """Initialize from the appliance's extras catalog entry."""
        super().__init__(coordinator, appliance_id, extra)
        translation_key = KNOWN_EXTRA_TRANSLATION_KEYS.get(extra.id)
        if translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = extra.text or extra.id

    @property
    def native_value(self) -> time | None:
        """The stored HH:MM value; None until the first write stores one."""
        value = self._stored_value
        if value is None:
            return None
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        """Write the time as HH:MM (the API's observed wire format)."""
        await self._async_write_extra(value.strftime("%H:%M"))
