"""Climate platform for the Nature Remo integration."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import Any

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    EVENT_HUMIDITY,
    EVENT_TEMPERATURE,
    AirconModeRange,
    NatureRemoError,
)
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_conversion import TemperatureConverter

from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator
from .entity import NatureRemoApplianceEntity, command_error_message

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
    """True when a mode's temp list holds relative offsets, not setpoints."""
    for value in values:
        if value.startswith(("+", "-")):
            return True
        parsed = _parse_float(value)
        if parsed is not None and parsed <= 0:
            return True
    return False


def _coerce_to_allowed(current: str, allowed: list[str]) -> str:
    """Keep current if allowed; else snap to the numerically closest value."""
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
    return allowed[0]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up climate entities for AC appliances."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[NatureRemoClimate] = []
        for appliance_id, appliance in coordinator.data.appliances.items():
            if (
                appliance.type != APPLIANCE_TYPE_AC
                or appliance.aircon is None
                or appliance_id in known
            ):
                continue
            known.add(appliance_id)
            new_entities.append(NatureRemoClimate(coordinator, appliance_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class NatureRemoClimate(NatureRemoApplianceEntity, ClimateEntity):
    """Climate entity backed by a Nature Remo AC appliance."""

    _attr_name = None

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id

    @property
    def _mode_range(self) -> AirconModeRange | None:
        """Return the allowed values for the current operation mode."""
        appliance = self.appliance
        if appliance.aircon is None or appliance.settings is None:
            return None
        return appliance.aircon.modes.get(appliance.settings.mode)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Features depend on what the current mode's ranges offer."""
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if (mode_range := self._mode_range) is None:
            return features
        if mode_range.temperatures:
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
        """OFF plus the modes the AC supports."""
        modes = [HVACMode.OFF]
        if (aircon := self.appliance.aircon) is not None:
            modes.extend(
                NATURE_TO_HVAC[mode] for mode in aircon.modes if mode in NATURE_TO_HVAC
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
        """The set temperature; None for modes without one."""
        settings = self.appliance.settings
        if settings is None:
            return None
        return _parse_float(settings.temperature)

    def _absolute_temperatures(self) -> list[float]:
        """All absolute temperatures the AC accepts across modes.

        HA validates set_temperature against min/max BEFORE the entity can
        switch modes, so the advertised range must span every mode (per-mode
        enforcement happens at send time via _coerce_to_allowed). Relative
        offset lists (auto mode, and on some models dry mode too) are
        excluded; real devices send these without a '+' prefix (e.g.
        ["-5",...,"5"]), so a list is treated as relative when any entry
        starts with '+'/'-' or parses to <= 0 -- no real AC setpoint is at
        or below zero in either Celsius or Fahrenheit.
        """
        aircon = self.appliance.aircon
        if aircon is None:
            return []
        values: set[float] = set()
        for mode_range in aircon.modes.values():
            if _is_relative_temperature_list(mode_range.temperatures):
                continue
            for value in mode_range.temperatures:
                if (parsed := _parse_float(value)) is not None:
                    values.add(parsed)
        return sorted(values)

    @property
    def target_temperature_step(self) -> float | None:
        """Smallest gap between allowed temperatures."""
        values = self._absolute_temperatures()
        steps = [second - first for first, second in pairwise(values) if second > first]
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

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose remote-side extra parameters (e.g. autoclean)."""
        settings = self.appliance.settings
        if settings is None or not settings.extra:
            return None
        return dict(settings.extra)

    async def _async_send(
        self,
        *,
        operation_mode: str | None = None,
        temperature: str | None = None,
        air_volume: str | None = None,
        air_direction: str | None = None,
        air_direction_h: str | None = None,
        button: str = POWER_ON_BUTTON,
    ) -> None:
        """Send the full current settings with the requested overrides."""
        appliance = self.appliance
        settings = appliance.settings
        aircon = appliance.aircon
        mode = operation_mode or (settings.mode if settings else "")
        payload: dict[str, str] = {"button": button}
        if mode:
            payload["operation_mode"] = mode
            mode_range = aircon.modes.get(mode) if aircon else None
            if mode_range is not None:
                current_temp = settings.temperature if settings else ""
                current_vol = settings.volume if settings else ""
                current_dir = settings.direction if settings else ""
                current_dirh = settings.direction_h if settings else ""
                if mode_range.temperatures:
                    payload["temperature"] = _coerce_to_allowed(
                        temperature if temperature is not None else current_temp,
                        mode_range.temperatures,
                    )
                if mode_range.volumes:
                    payload["air_volume"] = _coerce_to_allowed(
                        air_volume if air_volume is not None else current_vol,
                        mode_range.volumes,
                    )
                if mode_range.directions:
                    payload["air_direction"] = _coerce_to_allowed(
                        air_direction if air_direction is not None else current_dir,
                        mode_range.directions,
                    )
                if mode_range.directions_h:
                    payload["air_direction_h"] = _coerce_to_allowed(
                        air_direction_h
                        if air_direction_h is not None
                        else current_dirh,
                        mode_range.directions_h,
                    )
        # settings.extra is remote-side state (e.g. Daikin autoclean) that the
        # physical remote bakes into every transmitted frame — pass it back on
        # every send or the state would be silently dropped.
        extra = (
            dict(settings.extra) if settings is not None and settings.extra else None
        )
        try:
            new_settings = await self.coordinator.client.set_aircon_settings(
                appliance.id, extra=extra, **payload
            )
        except NatureRemoError as err:
            raise HomeAssistantError(
                command_error_message(f"Failed to update {appliance.nickname}", err)
            ) from err
        self.coordinator.async_update_appliance(
            replace(appliance, settings=new_settings)
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode; OFF maps to the power-off button."""
        if hvac_mode == HVACMode.OFF:
            await self._async_send(button=POWER_OFF_BUTTON)
            return
        nature_mode = HVAC_TO_NATURE.get(hvac_mode)
        aircon = self.appliance.aircon
        if nature_mode is None or aircon is None or nature_mode not in aircon.modes:
            raise ServiceValidationError(f"Unsupported HVAC mode: {hvac_mode}")
        await self._async_send(operation_mode=nature_mode)

    async def async_turn_on(self) -> None:
        """Power on, restoring the last settings."""
        await self._async_send()

    async def async_turn_off(self) -> None:
        """Power off, keeping the settings for the next power-on."""
        await self._async_send(button=POWER_OFF_BUTTON)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature (optionally with a mode change)."""
        operation_mode: str | None = None
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            if hvac_mode == HVACMode.OFF:
                await self._async_send(button=POWER_OFF_BUTTON)
                return
            operation_mode = HVAC_TO_NATURE.get(hvac_mode)
        temperature = kwargs.get(ATTR_TEMPERATURE)
        await self._async_send(
            operation_mode=operation_mode,
            temperature=None if temperature is None else str(temperature),
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the air volume."""
        mode_range = self._mode_range
        if mode_range is None or fan_mode not in mode_range.volumes:
            raise ServiceValidationError(f"Unsupported fan mode: {fan_mode}")
        await self._async_send(air_volume=fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the vertical airflow direction."""
        mode_range = self._mode_range
        if mode_range is None or swing_mode not in mode_range.directions:
            raise ServiceValidationError(f"Unsupported swing mode: {swing_mode}")
        await self._async_send(air_direction=swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set the horizontal airflow direction."""
        mode_range = self._mode_range
        if mode_range is None or swing_horizontal_mode not in mode_range.directions_h:
            raise ServiceValidationError(
                f"Unsupported horizontal swing mode: {swing_horizontal_mode}"
            )
        await self._async_send(air_direction_h=swing_horizontal_mode)
