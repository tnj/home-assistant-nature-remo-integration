"""Data models for the Nature Remo Cloud API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp, returning None when absent or invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Rate limit state reported by the API response headers."""

    limit: int | None
    remaining: int | None
    reset: int | None


@dataclass(frozen=True, slots=True)
class User:
    """A Nature account."""

    id: str
    nickname: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        """Build from an API payload."""
        return cls(id=str(data["id"]), nickname=str(data.get("nickname") or ""))


EVENT_TEMPERATURE = "te"
EVENT_HUMIDITY = "hu"
EVENT_ILLUMINATION = "il"
EVENT_MOVEMENT = "mo"


@dataclass(frozen=True, slots=True)
class SensorValue:
    """A single sensor reading from newest_events."""

    value: float
    created_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorValue:
        """Build from an API payload."""
        return cls(
            value=float(data["val"]),
            created_at=_parse_datetime(data.get("created_at")),
        )


@dataclass(frozen=True, slots=True)
class Device:
    """A Nature Remo hardware device."""

    id: str
    name: str
    temperature_offset: float
    humidity_offset: float
    firmware_version: str
    mac_address: str | None
    bt_mac_address: str | None
    serial_number: str | None
    events: dict[str, SensorValue]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Device:
        """Build from an API payload; unknown event keys are kept as-is."""
        raw_events = data.get("newest_events") or {}
        events = {
            key: SensorValue.from_dict(value)
            for key, value in raw_events.items()
            if isinstance(value, dict) and "val" in value
        }
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or ""),
            temperature_offset=float(data.get("temperature_offset") or 0),
            humidity_offset=float(data.get("humidity_offset") or 0),
            firmware_version=str(data.get("firmware_version") or ""),
            mac_address=data.get("mac_address"),
            bt_mac_address=data.get("bt_mac_address"),
            serial_number=data.get("serial_number"),
            events=events,
        )


@dataclass(frozen=True, slots=True)
class ApplianceModel:
    """Metadata about the appliance's remote/model."""

    id: str
    manufacturer: str | None
    remote_name: str | None
    series: str | None
    name: str | None
    image: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplianceModel:
        """Build from an API payload."""
        return cls(
            id=str(data.get("id") or ""),
            manufacturer=data.get("manufacturer"),
            remote_name=data.get("remote_name"),
            series=data.get("series"),
            name=data.get("name"),
            image=data.get("image"),
        )


def _str_list(value: Any) -> list[str]:
    """Coerce an optional list of values into a list of strings."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


@dataclass(frozen=True, slots=True)
class AirconModeRange:
    """Allowed setting values for one AC operation mode."""

    temperatures: list[str]
    volumes: list[str]
    directions: list[str]
    directions_h: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AirconModeRange:
        """Build from an API payload."""
        return cls(
            temperatures=_str_list(data.get("temp")),
            volumes=_str_list(data.get("vol")),
            directions=_str_list(data.get("dir")),
            directions_h=_str_list(data.get("dirh")),
        )


@dataclass(frozen=True, slots=True)
class Aircon:
    """AC capabilities."""

    modes: dict[str, AirconModeRange]
    fixed_buttons: list[str]
    temp_unit: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Aircon:
        """Build from an API payload."""
        range_data = data.get("range") or {}
        modes_data = range_data.get("modes") or {}
        return cls(
            modes={
                str(mode): AirconModeRange.from_dict(mode_range or {})
                for mode, mode_range in modes_data.items()
            },
            fixed_buttons=_str_list(range_data.get("fixedButtons")),
            temp_unit=str(data.get("tempUnit") or ""),
        )


@dataclass(frozen=True, slots=True)
class AirconSettings:
    """Current AC settings; button == "power-off" means the AC is off."""

    temperature: str
    temperature_unit: str
    mode: str
    volume: str
    direction: str
    direction_h: str
    button: str
    updated_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AirconSettings:
        """Build from an API payload."""
        return cls(
            temperature=str(data.get("temp") or ""),
            temperature_unit=str(data.get("temp_unit") or ""),
            mode=str(data.get("mode") or ""),
            volume=str(data.get("vol") or ""),
            direction=str(data.get("dir") or ""),
            direction_h=str(data.get("dirh") or ""),
            button=str(data.get("button") or ""),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass(frozen=True, slots=True)
class ApplianceButton:
    """A named IR button on a TV or LIGHT appliance."""

    name: str
    label: str
    image: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplianceButton:
        """Build from an API payload."""
        return cls(
            name=str(data.get("name") or ""),
            label=str(data.get("label") or ""),
            image=str(data.get("image") or ""),
        )


@dataclass(frozen=True, slots=True)
class TVState:
    """Current TV state."""

    input: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TVState:
        """Build from an API payload."""
        return cls(input=data.get("input"))


@dataclass(frozen=True, slots=True)
class TV:
    """A TV appliance."""

    buttons: list[ApplianceButton]
    state: TVState

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TV:
        """Build from an API payload."""
        return cls(
            buttons=[
                ApplianceButton.from_dict(button)
                for button in data.get("buttons") or []
            ],
            state=TVState.from_dict(data.get("state") or {}),
        )


@dataclass(frozen=True, slots=True)
class LightState:
    """Current light state."""

    brightness: str | None
    power: str | None
    last_button: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightState:
        """Build from an API payload."""
        return cls(
            brightness=data.get("brightness"),
            power=data.get("power"),
            last_button=data.get("last_button"),
        )


@dataclass(frozen=True, slots=True)
class Light:
    """A LIGHT appliance."""

    buttons: list[ApplianceButton]
    state: LightState

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Light:
        """Build from an API payload."""
        return cls(
            buttons=[
                ApplianceButton.from_dict(button)
                for button in data.get("buttons") or []
            ],
            state=LightState.from_dict(data.get("state") or {}),
        )


@dataclass(frozen=True, slots=True)
class Signal:
    """A learned IR signal."""

    id: str
    name: str
    image: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """Build from an API payload."""
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or ""),
            image=str(data.get("image") or ""),
        )
