"""Tests for model parsing."""

from datetime import UTC, datetime

from aionatureremo import Device

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
