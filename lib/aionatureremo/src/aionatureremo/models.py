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
