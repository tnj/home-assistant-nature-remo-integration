"""Time platform for schedule-type AC / floor heater extra parameters."""

from __future__ import annotations

from datetime import time
from functools import partial

from aionatureremo import AirconExtra
from homeassistant.components.time import TimeEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator, NatureRemoData
from .entity import (
    EntityFactory,
    NatureRemoExtraEntity,
    async_manage_platform_entities,
    extra_platform,
    extras_catalog,
)

PARALLEL_UPDATES = 1

KNOWN_EXTRA_TRANSLATION_KEYS = {"new_sleep": "new_sleep"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up time entities for schedule-type extra parameters."""
    coordinator = entry.runtime_data

    def _build_entities(data: NatureRemoData) -> dict[str, EntityFactory]:
        # type "time" extras (e.g. Daikin new_sleep) carry an HH:MM value
        # instead of an options list; see entity.extra_platform for the
        # shared classification (and why availability plays no part in it).
        return {
            f"{appliance_id}_extra_{extra.id}": partial(
                NatureRemoExtraTime, coordinator, appliance_id, extra
            )
            for appliance_id, appliance in data.appliances.items()
            for extra in extras_catalog(appliance)
            if extra_platform(extra) is Platform.TIME
        }

    async_manage_platform_entities(
        hass,
        entry,
        async_add_entities,
        domain=Platform.TIME,
        build_entities=_build_entities,
    )


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
