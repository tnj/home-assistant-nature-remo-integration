"""Tests for the Nature Remo climate platform."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import Appliance, Device, NatureRemoRateLimitError
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
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.climate import (
    NatureRemoClimate,
    _coerce_to_allowed,
    _is_relative_temperature_list,
)
from custom_components.nature_remo.coordinator import NatureRemoData
from tests.conftest import aircon_settings

ENTITY = "climate.living_ac"
FH_ENTITY = "climate.floor_heater"
FH_ID = "appliance-floorheater-1"


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


def _ac_settings_replaced(
    appliances: list[Appliance], **overrides: str
) -> list[Appliance]:
    """Return the fixture appliances with the living-room AC's settings overridden."""
    return [
        replace(appliance, settings=replace(appliance.settings, **overrides))
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]


async def _setup_with_ac_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
    **overrides: str,
) -> None:
    """Set up the integration with the living-room AC's settings overridden."""
    mock_client.get_appliances.return_value = _ac_settings_replaced(
        appliances, **overrides
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


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
    # Extras have their own switch/select/time entities; the climate entity
    # does not duplicate them as state attributes.
    assert "autoclean" not in state.attributes


async def test_climate_off_state_from_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Button == power-off reports HVACMode.OFF."""
    await _setup_with_ac_settings(
        hass, mock_config_entry, mock_client, appliances, button="power-off"
    )

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """turn_off sends the full settings plus power-off; turn_on restores."""
    mock_client.set_aircon_settings.return_value = aircon_settings(button="power-off")
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

    mock_client.set_aircon_settings.return_value = aircon_settings()
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
    mock_client.set_aircon_settings.return_value = aircon_settings(temperature="27")
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
    mock_client.set_aircon_settings.return_value = aircon_settings(
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
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """cool(26)→warm snaps the temperature into warm's 18-22 range."""
    mock_client.set_aircon_settings.return_value = aircon_settings(
        mode="warm", temperature="22"
    )
    # A mode change triggers a coordinator refresh (extras availability is
    # per-mode and aircon_settings returns no catalog); serve the
    # post-change server truth so the refresh doesn't roll the state back.
    mock_client.get_appliances.return_value = [
        replace(a, settings=replace(a.settings, mode="warm", temperature="22"))
        if a.id == "appliance-ac-1"
        else a
        for a in appliances
    ]
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
    assert mock_client.get_appliances.call_count == 2  # setup + catalog refresh
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.HEAT


async def test_climate_set_fan_and_swing_modes(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Fan, vertical swing and horizontal swing map to vol/dir/dirh."""
    mock_client.set_aircon_settings.return_value = aircon_settings(volume="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_volume"] == "2"

    mock_client.set_aircon_settings.return_value = aircon_settings(direction="1")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_MODE: "1"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction"] == "1"

    mock_client.set_aircon_settings.return_value = aircon_settings(direction_h="2")
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
    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
    assert exc_info.value.translation_key == "command_failed_rate_limited"
    assert exc_info.value.translation_placeholders == {
        "name": "Living AC",
        "error": "HTTP 429: limited",
        "reset": "1752825600",
    }


async def test_climate_set_hvac_mode_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_hvac_mode OFF sends the power-off button."""
    mock_client.set_aircon_settings.return_value = aircon_settings(button="power-off")
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
    mock_client.set_aircon_settings.return_value = aircon_settings(button="power-off")
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


async def test_climate_set_temperature_while_off_stays_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A temperature change on a powered-off AC must not switch it on.

    Every settings write carries a button field, so sending the power-on
    button ("") by default would turn the AC on behind the user's back.
    """
    await _setup_with_ac_settings(
        hass, mock_config_entry, mock_client, appliances, button="power-off"
    )

    mock_client.set_aircon_settings.return_value = aircon_settings(
        temperature="27", button="power-off"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 27},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["button"] == "power-off"
    assert kwargs["temperature"] == "27"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_set_fan_mode_while_off_stays_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Fan/swing changes on a powered-off AC keep the power-off button too."""
    await _setup_with_ac_settings(
        hass, mock_config_entry, mock_client, appliances, button="power-off"
    )

    mock_client.set_aircon_settings.return_value = aircon_settings(
        volume="2", button="power-off"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "2"},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["button"] == "power-off"
    assert kwargs["air_volume"] == "2"


async def test_climate_turn_on_while_off_sends_power_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """turn_on overrides the preserved button with the power-on one."""
    await _setup_with_ac_settings(
        hass, mock_config_entry, mock_client, appliances, button="power-off"
    )

    mock_client.set_aircon_settings.return_value = aircon_settings()
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["button"] == ""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL


async def test_climate_mode_change_omits_unparseable_temperature(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A stored temperature nothing can snap to is left out of the payload.

    The cloud then restores its own remembered value for the target mode
    instead of the entity guessing one.
    """
    await _setup_with_ac_settings(
        hass, mock_config_entry, mock_client, appliances, temperature=""
    )

    mock_client.set_aircon_settings.return_value = aircon_settings(
        mode="warm", temperature="20"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["button"] == ""
    assert "temperature" not in kwargs


async def test_climate_set_temperature_rejects_unsupported_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature validates hvac_mode exactly like set_hvac_mode does.

    HA core only validates hvac_mode for set_hvac_mode; dropping it here
    would silently set the temperature in the CURRENT mode instead.
    """
    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: ENTITY,
                ATTR_TEMPERATURE: 26,
                ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
            },
            blocking=True,
        )
    assert exc_info.value.translation_key == "unsupported_hvac_mode"
    assert exc_info.value.translation_placeholders == {"hvac_mode": "heat_cool"}
    mock_client.set_aircon_settings.assert_not_called()


def test_coerce_to_allowed_skips_unparseable() -> None:
    """Non-numeric candidates are skipped; unmatchable values yield None."""
    # "low" cannot be parsed and is skipped; 27 snaps to the nearest number.
    assert _coerce_to_allowed("27", ["low", "26", "28"]) == "26"
    # Nothing to snap to: the caller omits the field so the cloud keeps its
    # own remembered value instead of the entity inventing one.
    assert _coerce_to_allowed("30", ["low", "high"]) is None
    assert _coerce_to_allowed("", ["26", "28"]) is None


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # No prefix anywhere: only the "<= 0" rule can classify these. Real
        # ACs send relative lists unsigned, and no setpoint sits at or below
        # zero in either Celsius or Fahrenheit.
        (["0", "1", "2"], True),
        (["1", "2", "0"], True),
        # Signed lists are caught by the prefix rule before any parsing.
        (["-5", "-4", "-3"], True),
        (["+1", "+2", "+3"], True),
        # Absolute setpoint lists: neither rule fires.
        (["18", "19", "20"], False),
        (["24", "25", "26", "27", "28"], False),
        (["66.2", "68"], False),  # Fahrenheit setpoints stay absolute
        # Nothing to classify: an empty or wholly unparseable list is not
        # relative (supported_features then falls back to the emptiness check).
        ([], False),
        (["low", "high"], False),
    ],
)
def test_is_relative_temperature_list(values: list[str], expected: bool) -> None:
    """Relative lists are detected by a '+'/'-' prefix OR a value <= 0."""
    assert _is_relative_temperature_list(values) is expected


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

    with pytest.raises(ServiceValidationError) as exc_info:
        await entity.async_set_hvac_mode(HVACMode.HEAT_COOL)
    assert exc_info.value.translation_key == "unsupported_hvac_mode"
    with pytest.raises(ServiceValidationError) as exc_info:
        await entity.async_set_fan_mode("bogus")
    assert exc_info.value.translation_key == "unsupported_fan_mode"
    with pytest.raises(ServiceValidationError) as exc_info:
        await entity.async_set_swing_mode("bogus")
    assert exc_info.value.translation_key == "unsupported_swing_mode"
    with pytest.raises(ServiceValidationError) as exc_info:
        await entity.async_set_swing_horizontal_mode("bogus")
    assert exc_info.value.translation_key == "unsupported_swing_horizontal_mode"


async def test_climate_preserves_extra_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Remote-side extra state (autoclean) is sent back on every command."""
    mock_client.set_aircon_settings.return_value = aircon_settings(button="power-off")
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

    mock_client.set_aircon_settings.return_value = aircon_settings(extra={})
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["extra"] is None


def _floor_heater_response(appliances: list[Appliance], **overrides: str) -> Appliance:
    """Return a full updated Appliance, as floor_heater_settings responses carry."""
    floor_heater = next(a for a in appliances if a.id == FH_ID)
    assert floor_heater.settings is not None
    return replace(floor_heater, settings=replace(floor_heater.settings, **overrides))


async def test_floor_heater_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The floor heater exposes off/auto/heat and warm's absolute temp range."""
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF  # settings.button == "power-off"
    assert set(state.attributes[ATTR_HVAC_MODES]) == {
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.HEAT,
    }
    # Union of absolute mode lists: warm 17-30; auto's relative -2..2 excluded.
    assert state.attributes[ATTR_MIN_TEMP] == 17.0
    assert state.attributes[ATTR_MAX_TEMP] == 30.0
    assert state.attributes[ATTR_TARGET_TEMP_STEP] == 1.0
    # auto is a relative-offset mode: no target temperature is advertised
    # (HA validates set_temperature against the absolute 17-30 bounds, which
    # would make every valid offset unreachable and mangle accepted values).
    assert ATTR_TEMPERATURE not in state.attributes


async def test_floor_heater_turn_on(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """turn_on powers on via operation_mode and resends the stored extra."""
    mock_client.set_floor_heater_settings.return_value = _floor_heater_response(
        appliances, button=""
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: FH_ENTITY}, blocking=True
    )
    call = mock_client.set_floor_heater_settings.call_args
    assert call.args == (FH_ID,)
    assert call.kwargs["button"] == ""
    assert call.kwargs["operation_mode"] == "auto"
    assert call.kwargs["extra"] == {"save_energy": "off"}
    # Floor heaters never write through aircon_settings (HTTP 500 for them).
    mock_client.set_aircon_settings.assert_not_called()
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == HVACMode.AUTO  # optimistic update from the response


async def test_floor_heater_set_hvac_mode_heat_snaps_temperature(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """auto(0)→warm snaps the temperature into warm's 17-30 list."""
    mock_client.set_floor_heater_settings.return_value = _floor_heater_response(
        appliances, mode="warm", temperature="17", button=""
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: FH_ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_floor_heater_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "17"  # "0" snapped to warm's closest value
    assert kwargs["button"] == ""
    assert kwargs["extra"] == {"save_energy": "off"}
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_TEMPERATURE] == 17.0


async def test_floor_heater_turn_off(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """turn_off sends the power-off button."""
    mock_client.set_floor_heater_settings.return_value = _floor_heater_response(
        appliances, button="power-off"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: FH_ENTITY}, blocking=True
    )
    assert mock_client.set_floor_heater_settings.call_args.kwargs["button"] == (
        "power-off"
    )
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_floor_heater_set_temperature_in_heat_mode(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """In warm mode, set_temperature sends the absolute value."""
    mock_client.set_floor_heater_settings.return_value = _floor_heater_response(
        appliances, mode="warm", temperature="17", button=""
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: FH_ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    mock_client.set_floor_heater_settings.return_value = _floor_heater_response(
        appliances, mode="warm", temperature="25", button=""
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: FH_ENTITY, ATTR_TEMPERATURE: 25},
        blocking=True,
    )
    kwargs = mock_client.set_floor_heater_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "25"
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_TEMPERATURE] == 25.0


async def test_floor_heater_set_temperature_rejected_in_relative_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """In auto (relative offsets), HA rejects set_temperature before the entity.

    No target temperature is advertised there — the -2..2 offsets clash with
    the absolute 17-30 bounds — so core raises instead of the entity
    mangling an accepted absolute value into the nearest offset.
    """
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: FH_ENTITY, ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    mock_client.set_floor_heater_settings.assert_not_called()


async def test_floor_heater_mode_change_refreshes_extras_availability(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """The full-Appliance write response updates extras availability at once.

    floor_heater_settings echoes the whole appliance, so a mode change that
    hides an extra must flip its switch to unavailable immediately — no
    poll, no extra refresh request.
    """
    response = _floor_heater_response(
        appliances, mode="warm", temperature="17", button=""
    )
    assert response.floor_heater is not None
    response = replace(
        response,
        floor_heater=replace(
            response.floor_heater,
            extras=[
                replace(extra, availability="hidden")
                for extra in response.floor_heater.extras
            ],
        ),
    )
    mock_client.set_floor_heater_settings.return_value = response
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: FH_ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    switch_state = hass.states.get("switch.floor_heater_save_energy")
    assert switch_state is not None
    assert switch_state.state == STATE_UNAVAILABLE
