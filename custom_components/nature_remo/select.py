"""Select platform for multi-option AC / floor heater extra parameters."""

from __future__ import annotations

from functools import partial

from aionatureremo import AirconExtra
from homeassistant.components.select import SelectEntity
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

KNOWN_EXTRA_TRANSLATION_KEYS = {"humid": "humid", "dehumid": "dehumid"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects for multi-option AC / floor heater extra parameters."""
    coordinator = entry.runtime_data

    def _build_entities(data: NatureRemoData) -> dict[str, EntityFactory]:
        # Multi-option "choice" extras (e.g. Daikin humid:
        # off/40%/45%/50%/continuous/beauty) map onto a select; see
        # entity.extra_platform for the shared classification (and why
        # availability plays no part in it).
        return {
            f"{appliance_id}_extra_{extra.id}": partial(
                NatureRemoExtraSelect, coordinator, appliance_id, extra
            )
            for appliance_id, appliance in data.appliances.items()
            for extra in extras_catalog(appliance)
            if extra_platform(extra) is Platform.SELECT
        }

    async_manage_platform_entities(
        hass,
        entry,
        async_add_entities,
        domain=Platform.SELECT,
        build_entities=_build_entities,
    )


class NatureRemoExtraSelect(NatureRemoExtraEntity, SelectEntity):
    """Selects one value of a multi-option remote-side extra parameter.

    Options are the API's raw vocabulary (e.g. "off" / "40%" /
    "continuous"), untranslated — the same policy as fan/swing modes.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        extra: AirconExtra,
    ) -> None:
        """Initialize from the appliance's extras catalog entry."""
        super().__init__(coordinator, appliance_id, extra)
        self._last_options = [option.value for option in extra.options]
        translation_key = KNOWN_EXTRA_TRANSLATION_KEYS.get(extra.id)
        if translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = extra.text or extra.id

    @property
    def options(self) -> list[str]:
        """Follow the catalog: a firmware update can restate the options.

        The extras catalog is remote-side data that changes when Nature
        updates the remote definition (or when the user re-registers the
        appliance), so the option list is read per poll rather than frozen at
        entity creation. The last known list covers a poll that no longer
        lists the extra.
        """
        for extra in extras_catalog(self.appliance):
            if extra.id == self._extra_id:
                self._last_options = [option.value for option in extra.options]
                break
        return self._last_options

    @property
    def current_option(self) -> str | None:
        """The stored extra value; None until the first write stores one."""
        value = self._stored_value
        if value is None or value not in self.options:
            return None
        return value

    async def async_select_option(self, option: str) -> None:
        """Write the selected value."""
        await self._async_write_extra(option)
