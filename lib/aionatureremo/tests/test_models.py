"""Tests for model parsing."""

from datetime import UTC, datetime

from aionatureremo import (
    TV,
    Aircon,
    AirconModeRange,
    AirconSettings,
    Appliance,
    Device,
    Light,
    Signal,
    SmartMeter,
)

DEVICE_PAYLOAD = {
    "id": "device-1",
    "name": "Living Remo",
    "temperature_offset": 1,
    "humidity_offset": -2,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2026-07-01T00:00:00Z",
    "mac_address": "ab:cd:ef:12:34:56",
    "bt_mac_address": "ab:cd:ef:12:34:57",
    "serial_number": "1W123456789012",
    "firmware_version": "Remo/1.14.8",
    "newest_events": {
        "te": {"val": 26.4, "created_at": "2026-07-18T07:59:00Z"},
        "hu": {"val": 52, "created_at": "2026-07-18T07:59:00Z"},
        "il": {"val": 123.4, "created_at": "2026-07-18T07:58:00Z"},
        "mo": {"val": 1, "created_at": "2026-07-18T07:50:00Z"},
    },
}


def test_device_from_dict_full() -> None:
    """All fields and events parse."""
    device = Device.from_dict(DEVICE_PAYLOAD)

    assert device.id == "device-1"
    assert device.name == "Living Remo"
    assert device.temperature_offset == 1.0
    assert device.humidity_offset == -2.0
    assert device.firmware_version == "Remo/1.14.8"
    assert device.mac_address == "ab:cd:ef:12:34:56"
    assert device.serial_number == "1W123456789012"
    assert device.events["te"].value == 26.4
    assert device.events["mo"].created_at == datetime(2026, 7, 18, 7, 50, tzinfo=UTC)


def test_device_from_dict_minimal() -> None:
    """A device without events (e.g. Remo E lite) parses with defaults."""
    device = Device.from_dict({"id": "device-2", "name": "Remo E lite"})

    assert device.events == {}
    assert device.temperature_offset == 0.0
    assert device.mac_address is None


AIRCON_PAYLOAD = {
    "range": {
        "modes": {
            "cool": {
                "temp": ["24", "25", "26", "27", "28"],
                "vol": ["1", "2", "3", "auto"],
                "dir": ["1", "2", "swing", "auto"],
                "dirh": ["1", "2", "3", "swing"],
            },
            "dry": {"temp": [], "vol": ["auto"], "dir": [], "dirh": []},
            "auto": {
                "temp": ["-2", "-1", "0", "+1", "+2"],
                "vol": ["auto"],
                "dir": [],
                "dirh": [],
            },
        },
        "fixedButtons": ["power-off"],
    },
    "tempUnit": "c",
}


def test_aircon_from_dict() -> None:
    """Mode ranges, fixed buttons and temp unit parse."""
    aircon = Aircon.from_dict(AIRCON_PAYLOAD)

    assert set(aircon.modes) == {"cool", "dry", "auto"}
    assert aircon.modes["cool"].temperatures == ["24", "25", "26", "27", "28"]
    assert aircon.modes["cool"].directions_h == ["1", "2", "3", "swing"]
    assert aircon.modes["dry"].temperatures == []
    assert aircon.fixed_buttons == ["power-off"]
    assert aircon.temp_unit == "c"


def test_aircon_mode_range_drops_empty_string_entries() -> None:
    """The real API sends dirh: [""] as a "not supported" placeholder.

    Keeping the empty string would make directions_h non-empty and falsely
    enable horizontal swing; it must parse to an empty list instead.
    """
    mode_range = AirconModeRange.from_dict({"dirh": [""], "temp": ["1", ""]})

    assert mode_range.directions_h == []
    assert mode_range.temperatures == ["1"]


def test_aircon_settings_from_dict() -> None:
    """Settings parse, treating null-ish values as empty strings."""
    settings = AirconSettings.from_dict(
        {
            "temp": "26",
            "temp_unit": "c",
            "mode": "cool",
            "vol": "auto",
            "dir": "swing",
            "dirh": "",
            "button": None,
            "updated_at": "2026-07-18T06:00:00Z",
        }
    )

    assert settings.temperature == "26"
    assert settings.mode == "cool"
    assert settings.volume == "auto"
    assert settings.direction == "swing"
    assert settings.direction_h == ""
    assert settings.button == ""
    assert settings.updated_at is not None


def test_tv_from_dict() -> None:
    """TV buttons and input state parse."""
    tv = TV.from_dict(
        {
            "state": {"input": "t"},
            "buttons": [
                {"name": "power", "image": "ico_io", "label": "Power"},
                {"name": "vol-up", "image": "ico_vol_up", "label": "Volume up"},
            ],
        }
    )

    assert tv.state.input == "t"
    assert [b.name for b in tv.buttons] == ["power", "vol-up"]


def test_light_from_dict() -> None:
    """Light buttons and state parse; missing state fields become None."""
    light = Light.from_dict(
        {
            "state": {"brightness": "100", "power": "on", "last_button": "on"},
            "buttons": [{"name": "on", "image": "ico_on", "label": "On"}],
        }
    )

    assert light.state.power == "on"
    assert light.buttons[0].label == "On"

    empty = Light.from_dict({})
    assert empty.state.power is None
    assert empty.buttons == []


def test_signal_from_dict() -> None:
    """IR signals parse."""
    signal = Signal.from_dict({"id": "signal-1", "name": "Power", "image": "ico_io"})

    assert signal.id == "signal-1"
    assert signal.name == "Power"


def _meter(props: list[dict[str, object]]) -> SmartMeter:
    return SmartMeter.from_dict({"echonetlite_properties": props})


SMART_METER_PROPS: list[dict[str, object]] = [
    {
        "name": "coefficient",
        "epc": 211,
        "val": "1",
        "updated_at": "2026-07-18T07:00:00Z",
    },
    {
        "name": "cumulative_electric_energy_effective_digits",
        "epc": 215,
        "val": "6",
    },
    {
        "name": "normal_direction_cumulative_electric_energy",
        "epc": 224,
        "val": "123456",
    },
    {"name": "cumulative_electric_energy_unit", "epc": 225, "val": "1"},
    {
        "name": "reverse_direction_cumulative_electric_energy",
        "epc": 227,
        "val": "1234",
    },
    {"name": "measured_instantaneous", "epc": 231, "val": "520"},
]


def test_smart_meter_energy_math() -> None:
    """kWh = raw x coefficient x unit multiplier; power is raw watts."""
    meter = _meter(SMART_METER_PROPS)

    assert meter.instantaneous_power_w == 520
    assert meter.cumulative_energy_kwh == 12345.6
    assert meter.cumulative_energy_reverse_kwh == 123.4


def test_smart_meter_multiplying_unit_codes() -> None:
    """Unit codes 10-13 multiply (a naive 10^-n formula would be wrong)."""
    meter = _meter(
        [
            {"epc": 224, "val": "5", "name": "normal"},
            {"epc": 225, "val": "11", "name": "unit"},
        ]
    )

    assert meter.cumulative_energy_kwh == 500.0


def test_smart_meter_negative_power() -> None:
    """Instantaneous power is signed (negative = exporting)."""
    meter = _meter([{"epc": 231, "val": "-300", "name": "instant"}])

    assert meter.instantaneous_power_w == -300


def test_smart_meter_missing_unit_returns_none() -> None:
    """Without EPC 225 the cumulative energy cannot be scaled."""
    meter = _meter([{"epc": 224, "val": "123456", "name": "normal"}])

    assert meter.cumulative_energy_kwh is None
    assert meter.cumulative_energy_reverse_kwh is None
    assert meter.instantaneous_power_w is None


def test_smart_meter_coefficient_defaults_to_one() -> None:
    """Missing coefficient (EPC 211) defaults to 1."""
    meter = _meter(
        [
            {"epc": 224, "val": "100", "name": "normal"},
            {"epc": 225, "val": "2", "name": "unit"},
        ]
    )

    assert meter.cumulative_energy_kwh == 1.0


def test_appliance_from_dict_ac() -> None:
    """An AC appliance wires settings, aircon, model and device id."""
    appliance = Appliance.from_dict(
        {
            "id": "appliance-ac-1",
            "type": "AC",
            "nickname": "Living AC",
            "image": "ico_ac_1",
            "device": {"id": "device-1", "name": "Living Remo"},
            "model": {"id": "model-1", "manufacturer": "daikin", "name": "Daikin AC"},
            "settings": {"temp": "26", "mode": "cool", "vol": "auto", "button": ""},
            "aircon": AIRCON_PAYLOAD,
            "signals": [],
        }
    )

    assert appliance.type == "AC"
    assert appliance.device_id == "device-1"
    assert appliance.model is not None
    assert appliance.model.manufacturer == "daikin"
    assert appliance.settings is not None
    assert appliance.settings.mode == "cool"
    assert appliance.aircon is not None
    assert "cool" in appliance.aircon.modes
    assert appliance.tv is None
    assert appliance.smart_meter is None


def test_appliance_from_dict_ir_minimal() -> None:
    """An IR appliance has signals and no sub-objects."""
    appliance = Appliance.from_dict(
        {
            "id": "appliance-ir-1",
            "type": "IR",
            "nickname": "Fan",
            "signals": [{"id": "signal-1", "name": "Power", "image": "ico_io"}],
        }
    )

    assert appliance.device_id is None
    assert appliance.model is None
    assert [s.name for s in appliance.signals] == ["Power"]
