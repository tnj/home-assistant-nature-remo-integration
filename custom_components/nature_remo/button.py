"""Button platform for IR signals, light/TV/projector buttons, and AC fixed buttons."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    APPLIANCE_TYPE_LIGHT,
    APPLIANCE_TYPE_LIGHT_PROJECTOR,
    APPLIANCE_TYPE_TV,
    ApplianceButton,
    LightProjectorButton,
    NatureRemoError,
    Signal,
)
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity, command_error_message

PARALLEL_UPDATES = 1

LIGHT_POWER_BUTTONS = {"on", "off", "onoff"}
KNOWN_LIGHT_BUTTON_KEYS = {
    "night": "night",
    "on-100": "on_100",
    "on-favorite": "on_favorite",
    "bright-up": "bright_up",
    "bright-down": "bright_down",
    "colortemp-up": "colortemp_up",
    "colortemp-down": "colortemp_down",
}

# The everyday controls: power, input cycle, channel up/down, volume up/down.
# These are the only TV buttons enabled by default; every other button in
# KNOWN_TV_BUTTON_NAMES (and any unrecognized name) is created disabled.
# "power" is a toggle-only IR signal and this button is its primary control
# surface (there is no remote entity; the TV has no discrete on/off codes).
SHORTCUT_TV_BUTTON_NAMES = frozenset(
    {"power", "select-input-src", "ch-up", "ch-down", "vol-up", "vol-down"}
)

# Button names the Nature API is known to enumerate in tv.buttons[]. Names
# outside this vocabulary still get an entity (see NatureRemoTVButton),
# falling back to their API-provided label. Each known name's translation key
# is name.replace("-", "_") (verified against strings.json's button section).
KNOWN_TV_BUTTON_NAMES = frozenset(
    {
        "input-terrestrial",
        "input-bs",
        "input-cs",
        "select-input-src",
        "power",
        "mute",
        "vol-up",
        "vol-down",
        "ch-up",
        "ch-down",
        "ch-1",
        "ch-2",
        "ch-3",
        "ch-4",
        "ch-5",
        "ch-6",
        "ch-7",
        "ch-8",
        "ch-9",
        "ch-10",
        "ch-11",
        "ch-12",
        "up",
        "down",
        "left",
        "right",
        "ok",
        "back",
        "exit",
        "home",
        "settings",
        "submenu",
        "display",
        "d",
        "tv-schedule",
        "select-audio",
        "blue",
        "red",
        "green",
        "yellow",
        "play",
        "pause",
        "stop",
        "prev",
        "next",
        "fast-rewind",
        "fast-forward",
        "record",
        "rewind-10-sec",
        "forward-30-sec",
        "clear-sound",
        "rec-list",
        "program-info",
        "subtitle",
        "tool",
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons for IR signals and extra light buttons."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[ButtonEntity] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            for signal in appliance.signals:
                unique_id = f"{appliance_id}_signal_{signal.id}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    NatureRemoSignalButton(coordinator, appliance_id, signal)
                )
            if appliance.type == APPLIANCE_TYPE_LIGHT and appliance.light is not None:
                for button in appliance.light.buttons:
                    if button.name in LIGHT_POWER_BUTTONS:
                        continue
                    unique_id = f"{appliance_id}_button_{button.name}"
                    if unique_id in known:
                        continue
                    known.add(unique_id)
                    new_entities.append(
                        NatureRemoLightButton(coordinator, appliance_id, button)
                    )
            if appliance.type == APPLIANCE_TYPE_TV and appliance.tv is not None:
                for button in appliance.tv.buttons:
                    if not button.name:
                        continue
                    unique_id = f"{appliance_id}_button_{button.name}"
                    if unique_id in known:
                        continue
                    known.add(unique_id)
                    new_entities.append(
                        NatureRemoTVButton(coordinator, appliance_id, button)
                    )
            if (
                appliance.type == APPLIANCE_TYPE_LIGHT_PROJECTOR
                and appliance.light_projector is not None
            ):
                # The library already flattened the layout tree in document
                # order and skipped empty names.
                for projector_button in appliance.light_projector.buttons:
                    unique_id = f"{appliance_id}_button_{projector_button.name}"
                    if unique_id in known:
                        continue
                    known.add(unique_id)
                    new_entities.append(
                        NatureRemoLightProjectorButton(
                            coordinator, appliance_id, projector_button
                        )
                    )
            if appliance.type == APPLIANCE_TYPE_AC and appliance.aircon is not None:
                for name in appliance.aircon.fixed_buttons:
                    # power-off is the climate entity's HVACMode.OFF.
                    if not name or name == "power-off":
                        continue
                    unique_id = f"{appliance_id}_button_{name}"
                    if unique_id in known:
                        continue
                    known.add(unique_id)
                    new_entities.append(
                        NatureRemoACFixedButton(coordinator, appliance_id, name)
                    )
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoSignalButton(NatureRemoApplianceEntity, ButtonEntity):
    """Sends one learned IR signal."""

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        signal: Signal,
    ) -> None:
        """Initialize from the signal's user-defined name."""
        super().__init__(coordinator, appliance_id)
        self._signal_id = signal.id
        self._attr_unique_id = f"{appliance_id}_signal_{signal.id}"
        self._attr_name = signal.name

    async def async_press(self) -> None:
        """Send the IR signal."""
        try:
            await self.coordinator.client.send_signal(self._signal_id)
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message("Failed to send IR signal", err)
            ) from err


class NatureRemoLightButton(NatureRemoApplianceEntity, ButtonEntity):
    """Presses one non-power light button (night, brightness, ...)."""

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        button: ApplianceButton,
    ) -> None:
        """Initialize with a translation for known button names."""
        super().__init__(coordinator, appliance_id)
        self._button_name = button.name
        self._attr_unique_id = f"{appliance_id}_button_{button.name}"
        if (translation_key := KNOWN_LIGHT_BUTTON_KEYS.get(button.name)) is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = button.label or button.name

    async def async_press(self) -> None:
        """Press the light button and apply the returned state."""
        appliance = self.appliance
        try:
            new_state = await self.coordinator.client.send_light_button(
                appliance.id, self._button_name
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err
        if appliance.light is not None:
            self.coordinator.async_update_appliance(
                replace(appliance, light=replace(appliance.light, state=new_state))
            )


class NatureRemoTVButton(NatureRemoApplianceEntity, ButtonEntity):
    """Presses one API-enumerated TV button (tv.buttons[]).

    Every button the Nature API lists for the appliance gets an entity;
    these buttons ARE the TV's control surface (there is no remote entity).
    Only the everyday shortcuts (power / input / channel / volume) are
    enabled by default; the rest are created disabled
    (entity-disabled-by-default) so the entity list isn't flooded but every
    button is still one click away.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        button: ApplianceButton,
    ) -> None:
        """Initialize with a translation for known button names."""
        super().__init__(coordinator, appliance_id)
        self._button_name = button.name
        self._attr_unique_id = f"{appliance_id}_button_{button.name}"
        self._attr_entity_registry_enabled_default = (
            button.name in SHORTCUT_TV_BUTTON_NAMES
        )
        if button.name in KNOWN_TV_BUTTON_NAMES:
            self._attr_translation_key = button.name.replace("-", "_")
        else:
            self._attr_name = button.label or button.name

    async def async_press(self) -> None:
        """Send the TV button. Stateless: no tv state to update."""
        appliance = self.appliance
        try:
            await self.coordinator.client.send_tv_button(
                appliance.id, self._button_name
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err


class NatureRemoLightProjectorButton(NatureRemoApplianceEntity, ButtonEntity):
    """Presses one light projector button (light_projector layout leaf).

    Deliberately NO translation keys: the leaf names are generic layout
    slots (plus/minus, record, ...) and only the per-model "text" carries
    the real meaning ("Volume Up", "Ok"), so the entity name comes straight
    from that API-provided text.

    Only "io" — the power key, the only everyday control — is enabled by
    default; every other button is created disabled (same philosophy as TV
    buttons). As with the TV power button, "io" is a toggle-only IR signal,
    so a stateless button is the honest control surface.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        button: LightProjectorButton,
    ) -> None:
        """Initialize from the button's API-provided display text."""
        super().__init__(coordinator, appliance_id)
        self._button_name = button.name
        self._attr_unique_id = f"{appliance_id}_button_{button.name}"
        self._attr_entity_registry_enabled_default = button.name == "io"
        self._attr_name = button.text or button.name

    async def async_press(self) -> None:
        """Send the projector button. Stateless: the API returns no state."""
        appliance = self.appliance
        try:
            await self.coordinator.client.send_light_projector_button(
                appliance.id, self._button_name
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err


KNOWN_AC_FIXED_BUTTON_KEYS = {
    "airdir-swing": "airdir_swing",
    "airdir-tilt": "airdir_tilt",
}


class NatureRemoACFixedButton(NatureRemoApplianceEntity, ButtonEntity):
    """Presses one AC fixed button (aircon.range.fixedButtons).

    Fixed buttons are one-shot IR commands outside the mode/temperature
    state machine — on some models (e.g. Fujitsu) they are the only way to
    control airflow swing. power-off is excluded here: that is the climate
    entity's HVACMode.OFF. Stateless press; the next poll refreshes state.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        name: str,
    ) -> None:
        """Initialize with a translation for known fixed-button names."""
        super().__init__(coordinator, appliance_id)
        self._button_name = name
        self._attr_unique_id = f"{appliance_id}_button_{name}"
        if (translation_key := KNOWN_AC_FIXED_BUTTON_KEYS.get(name)) is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = name

    async def async_press(self) -> None:
        """Send the fixed button (button param only, no settings change)."""
        appliance = self.appliance
        try:
            await self.coordinator.client.set_aircon_settings(
                appliance.id, button=self._button_name
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to control {appliance.nickname}", err)
            ) from err
