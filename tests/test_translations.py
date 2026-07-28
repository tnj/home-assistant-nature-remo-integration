"""Consistency checks for exception translations.

Guards the contract between raise sites and strings.json: a key raised in
code but missing from strings.json would render as a raw key path in the
UI, and a message placeholder the code never passes would render literally.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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
