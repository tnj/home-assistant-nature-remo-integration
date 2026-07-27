"""Switch platform for binary AC / floor heater extra parameters."""

from __future__ import annotations

from typing import Any

from aionatureremo import AirconExtra
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoExtraEntity, extra_platform, extras_catalog

PARALLEL_UPDATES = 1

KNOWN_EXTRA_TRANSLATION_KEYS = {"autoclean": "autoclean"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for binary AC / floor heater extra parameters."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoACExtraSwitch] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for extra in extras_catalog(appliance):
                # Only binary on/off extras map onto a switch; see
                # entity.extra_platform for the shared classification (and
                # why availability plays no part in it).
                if extra_platform(extra) is not Platform.SWITCH:
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


class NatureRemoACExtraSwitch(NatureRemoExtraEntity, SwitchEntity):
    """Toggles a binary remote-side extra parameter (e.g. Daikin autoclean)."""

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
    def is_on(self) -> bool | None:
        """Return the stored extra value, if the API reports one."""
        value = self._stored_value
        if value is None:
            return None
        return value == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the extra."""
        await self._async_write_extra("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the extra."""
        await self._async_write_extra("off")
