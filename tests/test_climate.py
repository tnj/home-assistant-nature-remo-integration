"""Tests for the Nature Remo climate platform."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import AirconSettings, Appliance, Device, NatureRemoRateLimitError
from homeassistant.components.climate import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_SWING_HORIZONTAL_MODE,
    ATTR_SWING_HORIZONTAL_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ATTR_TARGET_TEMP_STEP,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_HORIZONTAL_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.climate.const import DEFAULT_MAX_TEMP, DEFAULT_MIN_TEMP
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.climate import (
    NatureRemoClimate,
    _coerce_to_allowed,
)
from custom_components.nature_remo.coordinator import NatureRemoData

ENTITY = "climate.living_ac"


def _ac_entity(
    appliances: list[Appliance], devices: list[Device], ac: Appliance
) -> NatureRemoClimate:
    """Build a climate entity backed by a replaced AC appliance (no HA setup)."""
    mapped = {a.id: (ac if a.id == "appliance-ac-1" else a) for a in appliances}
    data = NatureRemoData(
        devices={d.id: d for d in devices},
        appliances=mapped,
    )
    coordinator = SimpleNamespace(data=data)
    return NatureRemoClimate(coordinator, "appliance-ac-1")  # type: ignore[arg-type]


def _settings(**overrides: str | None) -> AirconSettings:
    """Build an AirconSettings for mock command responses."""
    values: dict[str, str | None | dict[str, str]] = {
        "temperature": "26",
        "temperature_unit": "c",
        "mode": "cool",
        "volume": "auto",
        "direction": "swing",
        "direction_h": "",
        "button": "",
        "updated_at": None,
        # The real API echoes remote-side extra state in every response.
        "extra": {"autoclean": "on"},
    }
    values.update(overrides)
    return AirconSettings(**values)  # type: ignore[arg-type]


async def test_climate_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The AC exposes dynamic modes, ranges and current readings."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 26.4
    assert state.attributes[ATTR_CURRENT_HUMIDITY] == 52
    assert state.attributes[ATTR_TEMPERATURE] == 26.0
    assert state.attributes[ATTR_FAN_MODE] == "auto"
    assert state.attributes[ATTR_SWING_MODE] == "swing"
    assert set(state.attributes[ATTR_HVAC_MODES]) == {
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    }
    assert state.attributes[ATTR_FAN_MODES] == ["1", "2", "3", "auto"]
    assert state.attributes[ATTR_SWING_MODES] == ["1", "2", "swing", "auto"]
    assert state.attributes[ATTR_SWING_HORIZONTAL_MODES] == ["1", "2", "3", "swing"]
    assert state.attributes[ATTR_MIN_TEMP] == 18.0  # union across absolute modes
    assert state.attributes[ATTR_MAX_TEMP] == 28.0
    assert state.attributes[ATTR_TARGET_TEMP_STEP] == 1.0


async def test_climate_off_state_from_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """button == power-off reports HVACMode.OFF."""
    mock_client.get_appliances.return_value = [
        replace(appliance, settings=replace(appliance.settings, button="power-off"))
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """turn_off sends the full settings plus power-off; turn_on restores."""
    mock_client.set_aircon_settings.return_value = _settings(button="power-off")
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    call = mock_client.set_aircon_settings.call_args
    assert call.args == ("appliance-ac-1",)
    assert call.kwargs["button"] == "power-off"
    assert call.kwargs["operation_mode"] == "cool"
    assert call.kwargs["temperature"] == "26"
    assert call.kwargs["air_volume"] == "auto"
    assert call.kwargs["air_direction"] == "swing"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF  # optimistic update from the response

    mock_client.set_aircon_settings.return_value = _settings()
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["button"] == ""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL


async def test_climate_set_temperature(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature snaps the value into the mode's allowed list."""
    mock_client.set_aircon_settings.return_value = _settings(temperature="27")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 27},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["temperature"] == "27"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_TEMPERATURE] == 27.0


async def test_climate_set_temperature_with_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature with hvac_mode switches mode in the same command."""
    mock_client.set_aircon_settings.return_value = _settings(
        mode="warm", temperature="20"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 20, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "20"


async def test_climate_set_hvac_mode_coerces_settings(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """cool(26)→warm snaps the temperature into warm's 18-22 range."""
    mock_client.set_aircon_settings.return_value = _settings(
        mode="warm", temperature="22"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "22"  # 26 snapped to warm's max 22
    assert kwargs["button"] == ""
    assert "air_direction_h" not in kwargs  # warm has no dirh range
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.HEAT


async def test_climate_set_fan_and_swing_modes(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Fan, vertical swing and horizontal swing map to vol/dir/dirh."""
    mock_client.set_aircon_settings.return_value = _settings(volume="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_volume"] == "2"

    mock_client.set_aircon_settings.return_value = _settings(direction="1")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_MODE: "1"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction"] == "1"

    mock_client.set_aircon_settings.return_value = _settings(direction_h="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_HORIZONTAL_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_HORIZONTAL_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction_h"] == "2"


async def test_climate_command_failure_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A 429 surfaces as HomeAssistantError including the reset epoch (spec 5.5)."""
    mock_client.set_aircon_settings.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=1752825600
    )
    with pytest.raises(HomeAssistantError, match="Living AC") as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
    assert "1752825600" in str(exc_info.value)


async def test_climate_set_hvac_mode_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_hvac_mode OFF sends the power-off button."""
    mock_client.set_aircon_settings.return_value = _settings(button="power-off")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["button"] == "power-off"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_set_temperature_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature with hvac_mode OFF powers off instead of setting temp."""
    mock_client.set_aircon_settings.return_value = _settings(button="power-off")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 26, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["button"] == "power-off"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


def test_coerce_to_allowed_skips_unparseable() -> None:
    """Non-numeric candidates are skipped; unmatched values fall back."""
    # "low" cannot be parsed and is skipped; 27 snaps to the nearest number.
    assert _coerce_to_allowed("27", ["low", "26", "28"]) == "26"
    # No candidate parses: fall back to the first allowed value.
    assert _coerce_to_allowed("30", ["low", "high"]) == "low"


def test_climate_missing_settings(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """Without settings the entity exposes no mode-dependent capabilities."""
    ac = next(a for a in appliances if a.id == "appliance-ac-1")
    entity = _ac_entity(appliances, devices, replace(ac, settings=None))

    assert entity._mode_range is None
    assert entity.hvac_mode is None
    assert entity.target_temperature is None
    assert entity.fan_modes is None
    assert entity.swing_modes is None
    assert entity.swing_horizontal_modes is None
    assert entity.supported_features == (
        ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )


def test_climate_fahrenheit_unit(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """A Fahrenheit appliance reports the Fahrenheit unit."""
    ac = next(a for a in appliances if a.id == "appliance-ac-1")
    entity = _ac_entity(
        appliances,
        devices,
        replace(ac, settings=replace(ac.settings, temperature_unit="f")),
    )
    assert entity.temperature_unit == UnitOfTemperature.FAHRENHEIT


def test_climate_fahrenheit_current_temperature_converted(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """The `te` reading (always Celsius) is converted for a Fahrenheit AC."""
    ac = next(a for a in appliances if a.id == "appliance-ac-1")
    entity = _ac_entity(
        appliances,
        devices,
        replace(ac, settings=replace(ac.settings, temperature_unit="f")),
    )
    # Fixture device-remo3-1 reports te=26.4 (Celsius); 26.4 C == 79.52 F.
    assert round(entity.current_temperature, 1) == 79.5


def test_climate_relative_temp_lists_without_plus_prefix_are_excluded(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """Real ACs send relative lists with no '+' prefix (e.g. ["-5",...,"5"]).

    min/max must still come only from the absolute cool/warm lists, not from
    auto's signed offsets or dry's zero-anchored offsets.
    """
    ac = next(a for a in appliances if a.id == "appliance-ac-1")
    assert ac.aircon is not None
    modes = dict(ac.aircon.modes)
    modes["auto"] = replace(
        modes["auto"],
        temperatures=["-5", "-4", "-3", "-2", "-1", "0", "1", "2", "3", "4", "5"],
    )
    modes["dry"] = replace(modes["dry"], temperatures=["-2", "-1", "0", "1", "2"])
    entity = _ac_entity(
        appliances, devices, replace(ac, aircon=replace(ac.aircon, modes=modes))
    )

    # warm 18-22 union cool 24-28; auto and dry are relative and excluded.
    assert entity.min_temp == 18.0
    assert entity.max_temp == 28.0


def test_climate_without_aircon_uses_default_limits(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """With no aircon ranges the entity falls back to HA default temp limits."""
    ac = next(a for a in appliances if a.id == "appliance-ac-1")
    entity = _ac_entity(appliances, devices, replace(ac, aircon=None))

    assert entity._absolute_temperatures() == []
    # Falls through to ClimateEntity's default min/max (no per-mode ranges).
    assert entity.min_temp == DEFAULT_MIN_TEMP
    assert entity.max_temp == DEFAULT_MAX_TEMP


def test_climate_current_readings_without_device(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """No bound Remo (or a missing one) yields no current temperature/humidity."""
    ac = next(a for a in appliances if a.id == "appliance-ac-1")

    detached = _ac_entity(appliances, devices, replace(ac, device_id=None))
    assert detached.current_temperature is None
    assert detached.current_humidity is None

    dangling = _ac_entity(appliances, devices, replace(ac, device_id="missing"))
    assert dangling.current_temperature is None
    assert dangling.current_humidity is None


async def test_climate_unsupported_values_raise(
    appliances: list[Appliance], devices: list[Device]
) -> None:
    """Values outside the current mode's allowed ranges are rejected."""
    ac = next(a for a in appliances if a.id == "appliance-ac-1")
    entity = _ac_entity(appliances, devices, ac)

    with pytest.raises(ServiceValidationError):
        await entity.async_set_hvac_mode(HVACMode.HEAT_COOL)
    with pytest.raises(ServiceValidationError):
        await entity.async_set_fan_mode("bogus")
    with pytest.raises(ServiceValidationError):
        await entity.async_set_swing_mode("bogus")
    with pytest.raises(ServiceValidationError):
        await entity.async_set_swing_horizontal_mode("bogus")


async def test_climate_preserves_extra_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Remote-side extra state (autoclean) is exposed and sent on every command."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["autoclean"] == "on"

    mock_client.set_aircon_settings.return_value = _settings(button="power-off")
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["extra"] == {
        "autoclean": "on"
    }


async def test_climate_without_extra_sends_none(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """An AC without extra state sends no extra fields."""
    mock_client.get_appliances.return_value = [
        replace(appliance, settings=replace(appliance.settings, extra={}))
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert "autoclean" not in state.attributes

    mock_client.set_aircon_settings.return_value = _settings(extra={})
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["extra"] is None
