"""Select platform for multi-option AC / floor heater extra parameters."""

from __future__ import annotations

from aionatureremo import AirconExtra
from homeassistant.components.select import SelectEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoExtraEntity, extra_platform, extras_catalog

PARALLEL_UPDATES = 1

KNOWN_EXTRA_TRANSLATION_KEYS = {"humid": "humid", "dehumid": "dehumid"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects for multi-option AC / floor heater extra parameters."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoExtraSelect] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for extra in extras_catalog(appliance):
                # Multi-option "choice" extras (e.g. Daikin humid:
                # off/40%/45%/50%/continuous/beauty) map onto a select; see
                # entity.extra_platform for the shared classification (and
                # why availability plays no part in it).
                if extra_platform(extra) is not Platform.SELECT:
                    continue
                unique_id = f"{appliance_id}_extra_{extra.id}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoExtraSelect(coordinator, appliance_id, extra)
                )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


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
        self._attr_options = [option.value for option in extra.options]
        translation_key = KNOWN_EXTRA_TRANSLATION_KEYS.get(extra.id)
        if translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = extra.text or extra.id

    @property
    def current_option(self) -> str | None:
        """The stored extra value; None until the first write stores one."""
        value = self._stored_value
        if value is None or value not in self._attr_options:
            return None
        return value

    async def async_select_option(self, option: str) -> None:
        """Write the selected value."""
        await self._async_write_extra(option)
