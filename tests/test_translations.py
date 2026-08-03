"""Consistency checks for exception translations.

Guards the contract between raise sites and strings.json: a key raised in
code but missing from strings.json would render as a raw key path in the
UI, and a message placeholder the code never passes would render literally.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import homeassistant.util.dt as dt_util
import pytest
from aionatureremo import NatureRemoConnectionError, NatureRemoRateLimitError
from homeassistant.exceptions import HomeAssistantError

from custom_components.nature_remo.const import DOMAIN
from custom_components.nature_remo.entity import raise_command_error

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "nature_remo"

# key -> placeholder names the raise sites pass. Update together with the
# raise sites; test_exceptions_match_ledger keeps strings.json honest.
EXCEPTION_LEDGER: dict[str, set[str]] = {
    "appliance_missing": {"name"},
    "auth_failed": set(),
    "command_failed": {"name", "error"},
    "command_failed_rate_limited": {"name", "error", "reset"},
    "extra_write_ignored": {"name", "extra"},
    "offset_not_whole": {"value"},
    "unsupported_fan_mode": {"fan_mode"},
    "unsupported_hvac_mode": {"hvac_mode"},
    "unsupported_swing_horizontal_mode": {"swing_horizontal_mode"},
    "unsupported_swing_mode": {"swing_mode"},
    "update_failed": {"error"},
    "update_rate_limited": {"reset"},
}


def _load(name: str) -> dict[str, Any]:
    with (COMPONENT_DIR / name).open(encoding="utf-8") as file:
        data: dict[str, Any] = json.load(file)
        return data


def _message_placeholders(message: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", message))


def test_exceptions_match_ledger() -> None:
    """strings.json carries exactly the ledger's keys and placeholders."""
    exceptions = _load("strings.json")["exceptions"]
    assert set(exceptions) == set(EXCEPTION_LEDGER)
    for key, entry in exceptions.items():
        assert _message_placeholders(entry["message"]) == EXCEPTION_LEDGER[key], key


def test_en_translation_identical_to_strings() -> None:
    """translations/en.json must stay in sync with strings.json."""
    assert _load("strings.json") == _load("translations/en.json")


def test_ja_exceptions_cover_all_keys() -> None:
    """ja.json translates every exception with the same placeholders."""
    exceptions = _load("strings.json")["exceptions"]
    ja_exceptions = _load("translations/ja.json")["exceptions"]
    assert set(ja_exceptions) == set(exceptions)
    for key, entry in ja_exceptions.items():
        assert _message_placeholders(entry["message"]) == EXCEPTION_LEDGER[key], key


def test_raise_command_error_plain() -> None:
    """A non-429 client error maps to command_failed with name and error."""
    err = NatureRemoConnectionError("boom")
    with pytest.raises(HomeAssistantError) as exc_info:
        raise_command_error("Living AC", err)
    exc = exc_info.value
    assert exc.translation_domain == DOMAIN
    assert exc.translation_key == "command_failed"
    assert exc.translation_placeholders == {"name": "Living AC", "error": "boom"}
    assert exc.__cause__ is err


def test_raise_command_error_rate_limited() -> None:
    """A 429 with a known reset maps to the rate-limited key (spec 5.5).

    The epoch is rendered in local time: a bare epoch means nothing to the
    person reading the notification.
    """
    err = NatureRemoRateLimitError(429, "limited", reset=1752825600)
    with pytest.raises(HomeAssistantError) as exc_info:
        raise_command_error("Living AC", err)
    exc = exc_info.value
    assert exc.translation_key == "command_failed_rate_limited"
    placeholders = exc.translation_placeholders
    assert placeholders is not None
    assert placeholders["name"] == "Living AC"
    assert placeholders["error"] == "HTTP 429: limited"
    assert datetime.fromisoformat(placeholders["reset"]) == dt_util.utc_from_timestamp(
        1752825600
    )


def test_raise_command_error_rate_limited_without_reset() -> None:
    """A 429 whose reset header is missing falls back to the plain key."""
    err = NatureRemoRateLimitError(429, "limited", reset=None)
    with pytest.raises(HomeAssistantError) as exc_info:
        raise_command_error("Living AC", err)
    assert exc_info.value.translation_key == "command_failed"
