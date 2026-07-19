"""Tests for model parsing."""

from datetime import UTC, datetime

from aionatureremo import (
    TV,
    Aircon,
    AirconSettings,
    Device,
    Light,
    Signal,
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
