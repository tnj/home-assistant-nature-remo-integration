"""Button platform for IR signals, extra light buttons, and TV buttons."""

from __future__ import annotations

from dataclasses import replace

from aionatureremo import (
    APPLIANCE_TYPE_LIGHT,
    APPLIANCE_TYPE_TV,
    ApplianceButton,
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

# TV buttons exposed as stateless shortcuts (broadcast band + input-cycle).
# Nature's tv.state.input is the cloud-side virtual remote's band mode, not
# TV state (it changes even while the TV is powered off), so no entity
# claims a current input here — these just press the button. These are the
# only TV buttons enabled by default; every other button in
# KNOWN_TV_BUTTON_KEYS (and any unrecognized name) is created disabled.
SHORTCUT_TV_BUTTON_NAMES = frozenset(
    {"input-terrestrial", "input-bs", "input-cs", "select-input-src"}
)

# Translation keys for every button name the Nature API is known to enumerate
# in tv.buttons[]. Names outside this vocabulary still get an entity (see
# NatureRemoTVButton), falling back to their API-provided label.
KNOWN_TV_BUTTON_KEYS = {
    "input-terrestrial": "input_terrestrial",
    "input-bs": "input_bs",
    "input-cs": "input_cs",
    "select-input-src": "select_input_src",
    "power": "power",
    "mute": "mute",
    "vol-up": "vol_up",
    "vol-down": "vol_down",
    "ch-up": "ch_up",
    "ch-down": "ch_down",
    "ch-1": "ch_1",
    "ch-2": "ch_2",
    "ch-3": "ch_3",
    "ch-4": "ch_4",
    "ch-5": "ch_5",
    "ch-6": "ch_6",
    "ch-7": "ch_7",
    "ch-8": "ch_8",
    "ch-9": "ch_9",
    "ch-10": "ch_10",
    "ch-11": "ch_11",
    "ch-12": "ch_12",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "ok": "ok",
    "back": "back",
    "exit": "exit",
    "home": "home",
    "settings": "settings",
    "submenu": "submenu",
    "display": "display",
    "d": "d",
    "tv-schedule": "tv_schedule",
    "select-audio": "select_audio",
    "blue": "blue",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "play": "play",
    "pause": "pause",
    "stop": "stop",
    "prev": "prev",
    "next": "next",
    "fast-rewind": "fast_rewind",
    "fast-forward": "fast_forward",
    "record": "record",
    "rewind-10-sec": "rewind_10_sec",
    "forward-30-sec": "forward_30_sec",
    "clear-sound": "clear_sound",
    "rec-list": "rec_list",
    "program-info": "program_info",
    "subtitle": "subtitle",
    "tool": "tool",
}


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

    Every button the Nature API lists for the appliance gets an entity so
    none of the remote's preset functions are hidden behind the catch-all
    `remote` entity. Only the four broadcast/input shortcuts are enabled by
    default; the rest are created disabled (entity-disabled-by-default) so
    the entity list isn't flooded but the button is still one click away.
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
        if (translation_key := KNOWN_TV_BUTTON_KEYS.get(button.name)) is not None:
            self._attr_translation_key = translation_key
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
