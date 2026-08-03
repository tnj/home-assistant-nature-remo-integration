"""Switch platform for binary AC / floor heater extra parameters."""

from __future__ import annotations

from functools import partial
from typing import Any

from aionatureremo import AirconExtra
from homeassistant.components.switch import SwitchEntity
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

# Extra ids seen on real remotes, mapped to a localized name. Anything else
# falls back to the catalog's own `text`, which the API only ships in
# English. `sleep` is the binary spelling of night set mode on newer Daikin
# remotes (arc478a119); `new_sleep` on arc472a82 is a time extra and lives in
# time.py.
KNOWN_EXTRA_TRANSLATION_KEYS = {
    "autoclean": "autoclean",
    "eco": "eco",
    "hotwind": "hotwind",
    "powerful": "powerful",
    "sleep": "sleep",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for binary AC / floor heater extra parameters."""
    coordinator = entry.runtime_data

    def _build_entities(data: NatureRemoData) -> dict[str, EntityFactory]:
        # Only binary on/off extras map onto a switch; see
        # entity.extra_platform for the shared classification (and why
        # availability plays no part in it).
        return {
            f"{appliance_id}_extra_{extra.id}": partial(
                NatureRemoACExtraSwitch, coordinator, appliance_id, extra
            )
            for appliance_id, appliance in data.appliances.items()
            for extra in extras_catalog(appliance)
            if extra_platform(extra) is Platform.SWITCH
        }

    async_manage_platform_entities(
        hass,
        entry,
        async_add_entities,
        domain=Platform.SWITCH,
        build_entities=_build_entities,
    )


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
