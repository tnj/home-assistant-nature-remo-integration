"""Climate platform for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from itertools import pairwise
from typing import Any

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    APPLIANCE_TYPE_FLOOR_HEATER,
    EVENT_HUMIDITY,
    EVENT_TEMPERATURE,
    Aircon,
    AirconModeRange,
    NatureRemoError,
)
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_conversion import TemperatureConverter

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator, NatureRemoData
from .entity import (
    EntityFactory,
    NatureRemoApplianceEntity,
    async_manage_platform_entities,
    command_error_message,
)

PARALLEL_UPDATES = 1

NATURE_TO_HVAC: dict[str, HVACMode] = {
    "cool": HVACMode.COOL,
    "warm": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "blow": HVACMode.FAN_ONLY,
    "auto": HVACMode.AUTO,
}
HVAC_TO_NATURE: dict[HVACMode, str] = {
    hvac: nature for nature, hvac in NATURE_TO_HVAC.items()
}

POWER_OFF_BUTTON = "power-off"
POWER_ON_BUTTON = ""


def _parse_float(value: str) -> float | None:
    """Parse a numeric API string ("26", "26.5", "+2"), None when invalid."""
    try:
        return float(value)
    except ValueError:
        return None


def _is_relative_temperature_list(values: list[str]) -> bool:
    """Return True when a mode's temp list holds relative offsets, not setpoints."""
    for value in values:
        if value.startswith(("+", "-")):
            return True
        parsed = _parse_float(value)
        if parsed is not None and parsed <= 0:
            return True
    return False


def _coerce_to_allowed(current: str, allowed: list[str]) -> str | None:
    """Keep current if allowed; else snap to the numerically closest value.

    None when there is nothing to snap to — current is neither in the list
    nor numerically comparable to it (an empty stored value, or a list
    without a single numeric entry). Callers omit the field entirely then
    instead of inventing a value. Explicit user input is always parseable
    (temperature arrives as str(float), fan/swing values are pre-validated
    against the current mode's list), so this only ever drops stored values.
    """
    if current in allowed:
        return current
    target = _parse_float(current)
    if target is not None:
        best: str | None = None
        best_distance = float("inf")
        for candidate in allowed:
            parsed = _parse_float(candidate)
            if parsed is None:
                continue
            distance = abs(parsed - target)
            if distance < best_distance:
                best = candidate
                best_distance = distance
        if best is not None:
            return best
    return None


def _put_coerced(
    payload: dict[str, str], key: str, current: str, allowed: list[str]
) -> None:
    """Add the coerced value to the payload, omitting unmatchable ones."""
    if (value := _coerce_to_allowed(current, allowed)) is not None:
        payload[key] = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up climate entities for AC and floor heater appliances."""
    coordinator = entry.runtime_data

    def _build_entities(data: NatureRemoData) -> dict[str, EntityFactory]:
        # The unique_id of a climate entity is the bare appliance id.
        entities: dict[str, EntityFactory] = {}
        for appliance_id, appliance in data.appliances.items():
            if appliance.type == APPLIANCE_TYPE_AC and appliance.aircon is not None:
                entities[appliance_id] = partial(
                    NatureRemoClimate, coordinator, appliance_id
                )
            elif (
                appliance.type == APPLIANCE_TYPE_FLOOR_HEATER
                and appliance.floor_heater is not None
            ):
                entities[appliance_id] = partial(
                    NatureRemoFloorHeaterClimate, coordinator, appliance_id
                )
        return entities

    async_manage_platform_entities(
        hass,
        entry,
        async_add_entities,
        domain=Platform.CLIMATE,
        build_entities=_build_entities,
    )


class NatureRemoClimate(NatureRemoApplianceEntity, ClimateEntity):
    """Climate entity backed by a Nature Remo AC appliance."""

    _attr_name = None

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id

    @property
    def _capability(self) -> Aircon | None:
        """The aircon-shaped capability catalog (modes/fixed buttons/extras).

        Subclasses override this for appliance types that reuse the aircon
        capability shape under another key (e.g. floor heaters).
        """
        return self.appliance.aircon

    @property
    def _mode_range(self) -> AirconModeRange | None:
        """Return the allowed values for the current operation mode."""
        capability = self._capability
        settings = self.appliance.settings
        if capability is None or settings is None:
            return None
        return capability.modes.get(settings.mode)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Features depend on what the current mode's ranges offer."""
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if (mode_range := self._mode_range) is None:
            return features
        # Relative-offset modes (auto, sometimes dry) advertise no target
        # temperature: min/max come from the absolute-mode union, so HA would
        # reject every valid offset and accept only absolute values that
        # _coerce_to_allowed would then mangle into the nearest offset.
        if mode_range.temperatures and not _is_relative_temperature_list(
            mode_range.temperatures
        ):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if mode_range.volumes:
            features |= ClimateEntityFeature.FAN_MODE
        if mode_range.directions:
            features |= ClimateEntityFeature.SWING_MODE
        if mode_range.directions_h:
            features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
        return features

    @property
    def temperature_unit(self) -> str:
        """Celsius unless the appliance reports Fahrenheit."""
        settings = self.appliance.settings
        if settings is not None and settings.temperature_unit == "f":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """OFF plus the modes the appliance supports."""
        modes = [HVACMode.OFF]
        if (capability := self._capability) is not None:
            modes.extend(
                NATURE_TO_HVAC[mode]
                for mode in capability.modes
                if mode in NATURE_TO_HVAC
            )
        return modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        """OFF when powered off via button, else the mapped mode."""
        settings = self.appliance.settings
        if settings is None:
            return None
        if settings.button == POWER_OFF_BUTTON:
            return HVACMode.OFF
        return NATURE_TO_HVAC.get(settings.mode)

    @property
    def target_temperature(self) -> float | None:
        """The set temperature; None for modes without an absolute one."""
        settings = self.appliance.settings
        if settings is None:
            return None
        mode_range = self._mode_range
        if mode_range is not None and _is_relative_temperature_list(
            mode_range.temperatures
        ):
            return None
        return _parse_float(settings.temperature)

    def _absolute_temperatures(self) -> list[float]:
        """All absolute temperatures the appliance accepts across modes.

        HA validates set_temperature against min/max BEFORE the entity can
        switch modes, so the advertised range must span every mode (per-mode
        enforcement happens at send time via _coerce_to_allowed). Relative
        offset lists (auto mode, and on some models dry mode too) are
        excluded; real devices send these without a '+' prefix (e.g.
        ["-5",...,"5"]), so a list is treated as relative when any entry
        starts with '+'/'-' or parses to <= 0 -- no real AC setpoint is at
        or below zero in either Celsius or Fahrenheit.
        """
        capability = self._capability
        if capability is None:
            return []
        values: set[float] = set()
        for mode_range in capability.modes.values():
            if _is_relative_temperature_list(mode_range.temperatures):
                continue
            for value in mode_range.temperatures:
                if (parsed := _parse_float(value)) is not None:
                    values.add(parsed)
        return sorted(values)

    @property
    def target_temperature_step(self) -> float | None:
        """Smallest gap between allowed temperatures."""
        # _absolute_temperatures returns a sorted set, so every pair ascends
        # and every gap is positive.
        values = self._absolute_temperatures()
        steps = [second - first for first, second in pairwise(values)]
        return min(steps) if steps else 1.0

    @property
    def min_temp(self) -> float:
        """Lowest temperature accepted by any mode."""
        if values := self._absolute_temperatures():
            return values[0]
        return super().min_temp

    @property
    def max_temp(self) -> float:
        """Highest temperature accepted by any mode."""
        if values := self._absolute_temperatures():
            return values[-1]
        return super().max_temp

    def _device_event_value(self, key: str) -> float | None:
        """Read a sensor event from the Remo the appliance is bound to."""
        appliance = self.appliance
        if appliance.device_id is None:
            return None
        device = self.coordinator.data.devices.get(appliance.device_id)
        if device is None:
            return None
        event = device.events.get(key)
        return event.value if event else None

    @property
    def current_temperature(self) -> float | None:
        """Room temperature from the bound Remo.

        Nature always reports `te` in Celsius, regardless of the AC's
        temperature_unit, so convert when this entity's unit is Fahrenheit.
        """
        value = self._device_event_value(EVENT_TEMPERATURE)
        if value is None or self.temperature_unit != UnitOfTemperature.FAHRENHEIT:
            return value
        return TemperatureConverter.convert(
            value, UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT
        )

    @property
    def current_humidity(self) -> float | None:
        """Room humidity from the bound Remo."""
        return self._device_event_value(EVENT_HUMIDITY)

    @property
    def fan_mode(self) -> str | None:
        """Current air volume."""
        settings = self.appliance.settings
        return (settings.volume or None) if settings else None

    @property
    def fan_modes(self) -> list[str] | None:
        """Allowed air volumes in the current mode."""
        mode_range = self._mode_range
        if mode_range is None or not mode_range.volumes:
            return None
        return list(mode_range.volumes)

    @property
    def swing_mode(self) -> str | None:
        """Current vertical airflow direction."""
        settings = self.appliance.settings
        return (settings.direction or None) if settings else None

    @property
    def swing_modes(self) -> list[str] | None:
        """Allowed vertical airflow directions in the current mode."""
        mode_range = self._mode_range
        if mode_range is None or not mode_range.directions:
            return None
        return list(mode_range.directions)

    @property
    def swing_horizontal_mode(self) -> str | None:
        """Current horizontal airflow direction."""
        settings = self.appliance.settings
        return (settings.direction_h or None) if settings else None

    @property
    def swing_horizontal_modes(self) -> list[str] | None:
        """Allowed horizontal airflow directions in the current mode."""
        mode_range = self._mode_range
        if mode_range is None or not mode_range.directions_h:
            return None
        return list(mode_range.directions_h)

    async def _async_send(
        self,
        *,
        operation_mode: str | None = None,
        temperature: str | None = None,
        air_volume: str | None = None,
        air_direction: str | None = None,
        air_direction_h: str | None = None,
        button: str | None = None,
    ) -> None:
        """Send the full current settings with the requested overrides.

        ``button`` defaults to the appliance's current power button, so a
        temperature/fan/swing change leaves a powered-off unit off; callers
        that mean "power on" pass POWER_ON_BUTTON explicitly.
        """
        async with self.coordinator.async_write_lock(self._appliance_id):
            # Read the appliance only after the lock: a settings write from
            # another platform (the extras switch/select/time entities) may
            # have landed while waiting, and this payload must be built on
            # top of it — settings.extra above all, since extras omitted
            # from a write are cleared server-side.
            appliance = self.appliance
            settings = appliance.settings
            capability = self._capability
            if button is None:
                # settings.button is "" while the unit runs and "power-off"
                # while it is off. Extras writes (entity.py) preserve it the
                # same way, which is probe-verified for those; on a full
                # settings write this relies on the API honoring the button
                # field we send back.
                button = settings.button if settings else POWER_ON_BUTTON
            mode = operation_mode or (settings.mode if settings else "")
            payload: dict[str, str] = {"button": button}
            if mode:
                payload["operation_mode"] = mode
                mode_range = capability.modes.get(mode) if capability else None
                if mode_range is not None:
                    current_temp = settings.temperature if settings else ""
                    current_vol = settings.volume if settings else ""
                    current_dir = settings.direction if settings else ""
                    current_dirh = settings.direction_h if settings else ""
                    # Fields the mode cannot express are left out entirely,
                    # as are stored values nothing in the list can be snapped
                    # to: the cloud restores its own remembered per-mode value
                    # when a field is omitted (probe-verified). Relative-offset
                    # modes therefore get no temperature at all — the stored
                    # value may be on the other scale (warm "25" would coerce
                    # to offset "+2").
                    if mode_range.temperatures and not _is_relative_temperature_list(
                        mode_range.temperatures
                    ):
                        _put_coerced(
                            payload,
                            "temperature",
                            temperature if temperature is not None else current_temp,
                            mode_range.temperatures,
                        )
                    if mode_range.volumes:
                        _put_coerced(
                            payload,
                            "air_volume",
                            air_volume if air_volume is not None else current_vol,
                            mode_range.volumes,
                        )
                    if mode_range.directions:
                        _put_coerced(
                            payload,
                            "air_direction",
                            air_direction if air_direction is not None else current_dir,
                            mode_range.directions,
                        )
                    if mode_range.directions_h:
                        _put_coerced(
                            payload,
                            "air_direction_h",
                            air_direction_h
                            if air_direction_h is not None
                            else current_dirh,
                            mode_range.directions_h,
                        )
            # settings.extra is remote-side state (e.g. Daikin autoclean) that
            # the physical remote bakes into every transmitted frame — pass it
            # back on every send or the state would be silently dropped.
            extra = (
                dict(settings.extra)
                if settings is not None and settings.extra
                else None
            )
            try:
                await self._async_write_settings(extra=extra, payload=payload)
            except NatureRemoError as err:
                raise HomeAssistantError(
                    command_error_message(f"Failed to update {appliance.nickname}", err)
                ) from err

    async def _async_write_settings(
        self, *, extra: dict[str, str] | None, payload: dict[str, str]
    ) -> None:
        """Perform the API write and apply the optimistic coordinator update.

        Overridable so subclasses can target a different settings endpoint;
        _async_send keeps the error wrapping around this call.
        """
        appliance = self.appliance
        old_mode = appliance.settings.mode if appliance.settings else None
        new_settings = await self.coordinator.client.set_aircon_settings(
            appliance.id, extra=extra, **payload
        )
        self.coordinator.async_update_appliance(
            replace(appliance, settings=new_settings)
        )
        if new_settings.mode != old_mode:
            # aircon_settings returns bare settings while extras availability
            # is per-mode, so the stored catalog is stale until the next GET.
            # Refresh now so extras switches can't offer writes the server
            # would silently ignore. (floor_heater_settings returns the full
            # appliance, so the subclass needs no refresh.)
            await self.coordinator.async_request_refresh()

    def _nature_mode_or_raise(self, hvac_mode: HVACMode) -> str:
        """Map an HA mode to its Nature name, rejecting unsupported ones.

        Shared by set_hvac_mode and set_temperature so both reject the same
        modes; HA core only validates hvac_mode for the former.
        """
        nature_mode = HVAC_TO_NATURE.get(hvac_mode)
        capability = self._capability
        if (
            nature_mode is None
            or capability is None
            or nature_mode not in capability.modes
        ):
            raise ServiceValidationError(f"Unsupported HVAC mode: {hvac_mode}")
        return nature_mode

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode; OFF maps to the power-off button."""
        if hvac_mode == HVACMode.OFF:
            await self._async_send(button=POWER_OFF_BUTTON)
            return
        # Selecting an active mode means "power on" in HA.
        await self._async_send(
            operation_mode=self._nature_mode_or_raise(hvac_mode),
            button=POWER_ON_BUTTON,
        )

    async def async_turn_on(self) -> None:
        """Power on, restoring the last settings."""
        await self._async_send(button=POWER_ON_BUTTON)

    async def async_turn_off(self) -> None:
        """Power off, keeping the settings for the next power-on."""
        await self._async_send(button=POWER_OFF_BUTTON)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature (optionally with a mode change).

        A mode change powers the appliance on; a temperature-only call keeps
        the current power state.
        """
        operation_mode: str | None = None
        button: str | None = None
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            if hvac_mode == HVACMode.OFF:
                await self._async_send(button=POWER_OFF_BUTTON)
                return
            operation_mode = self._nature_mode_or_raise(hvac_mode)
            button = POWER_ON_BUTTON
        temperature = kwargs.get(ATTR_TEMPERATURE)
        await self._async_send(
            operation_mode=operation_mode,
            temperature=None if temperature is None else str(temperature),
            button=button,
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the air volume, keeping the current power state."""
        mode_range = self._mode_range
        if mode_range is None or fan_mode not in mode_range.volumes:
            raise ServiceValidationError(f"Unsupported fan mode: {fan_mode}")
        await self._async_send(air_volume=fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the vertical airflow direction, keeping the power state."""
        mode_range = self._mode_range
        if mode_range is None or swing_mode not in mode_range.directions:
            raise ServiceValidationError(f"Unsupported swing mode: {swing_mode}")
        await self._async_send(air_direction=swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set the horizontal airflow direction, keeping the power state."""
        mode_range = self._mode_range
        if mode_range is None or swing_horizontal_mode not in mode_range.directions_h:
            raise ServiceValidationError(
                f"Unsupported horizontal swing mode: {swing_horizontal_mode}"
            )
        await self._async_send(air_direction_h=swing_horizontal_mode)


class NatureRemoFloorHeaterClimate(NatureRemoClimate):
    """Climate entity backed by a Nature Remo floor heater appliance.

    Floor heaters expose the aircon capability shape under the
    ``floor_heater`` key, but writes must go through the dedicated
    ``floor_heater_settings`` endpoint (``aircon_settings`` is HTTP 500 for
    them, probe-verified on a Corona rfc-a04).
    """

    @property
    def _capability(self) -> Aircon | None:
        """The floor heater's aircon-shaped capability catalog."""
        return self.appliance.floor_heater

    async def _async_write_settings(
        self, *, extra: dict[str, str] | None, payload: dict[str, str]
    ) -> None:
        """Write via floor_heater_settings; the response is a full Appliance.

        Only the keys the endpoint accepts are extracted from the payload
        (floor heater mode ranges have no vol/dir/dirh, so _async_send never
        adds the aircon-only keys, but keep the extraction explicit). The
        response replaces the whole appliance, so a fresh extras catalog —
        including per-mode availability — comes along for free.
        """
        appliance = self.appliance
        new_appliance = await self.coordinator.client.set_floor_heater_settings(
            appliance.id,
            operation_mode=payload.get("operation_mode"),
            temperature=payload.get("temperature"),
            button=payload.get("button"),
            extra=extra,
        )
        self.coordinator.async_update_appliance(new_appliance)
