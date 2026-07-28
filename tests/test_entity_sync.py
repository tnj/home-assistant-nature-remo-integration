"""Tests for the shared dynamic add/remove entity manager (entity.py)."""

import logging
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import Appliance, Device
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN, STALE_POLLS_BEFORE_REMOVAL
from tests.conftest import async_poll

SPEED_UNIQUE_ID = "appliance-ir-1_signal_signal-2"
SPEED_ENTITY = "button.fan_speed"

METER_ID = "appliance-meter-1"
POWER_UNIQUE_ID = f"{METER_ID}_instantaneous_power"
POWER_ENTITY = "sensor.smart_meter_power"
EPC_INSTANTANEOUS_POWER = 231

HUMIDITY_UNIQUE_ID = "device-remo3-1_humidity"
HUMIDITY_OFFSET_UNIQUE_ID = "device-remo3-1_humidity_offset"


@pytest.fixture(autouse=True)
def _grace_period_assumption() -> None:
    """Assert the grace period constant matches what these tests assume."""
    assert STALE_POLLS_BEFORE_REMOVAL == 3


def _without_speed_signal(appliances: list[Appliance]) -> list[Appliance]:
    """Return the fixture account with the fan's "Speed" IR signal deleted."""
    return [
        replace(
            appliance,
            signals=[signal for signal in appliance.signals if signal.id != "signal-2"],
        )
        if appliance.id == "appliance-ir-1"
        else appliance
        for appliance in appliances
    ]


def _without_meter_property(appliances: list[Appliance], epc: int) -> list[Appliance]:
    """Return the fixture account with one ECHONET property off the meter."""
    modified = []
    for appliance in appliances:
        if appliance.id == METER_ID and appliance.smart_meter is not None:
            smart_meter = replace(
                appliance.smart_meter,
                properties=[
                    prop for prop in appliance.smart_meter.properties if prop.epc != epc
                ],
            )
            modified.append(replace(appliance, smart_meter=smart_meter))
        else:
            modified.append(appliance)
    return modified


def _without_device_event(devices: list[Device], key: str) -> list[Device]:
    """Return the fixture account with one event off the living-room Remo."""
    return [
        replace(
            device,
            events={
                event_key: event
                for event_key, event in device.events.items()
                if event_key != key
            },
        )
        if device.id == "device-remo3-1"
        else device
        for device in devices
    ]


def _speed_entity_id(hass: HomeAssistant) -> str | None:
    """Return the registry entity_id of the fan's "Speed" button, if it still exists."""
    return er.async_get(hass).async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, SPEED_UNIQUE_ID
    )


async def test_deleted_signal_removed_after_three_missing_polls(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A signal deleted in the Nature app takes its button entity with it.

    Without removal the button stays available and errors on every press;
    with it, the entity only goes after the full grace period so a single
    truncated response cannot destroy the user's customizations.
    """
    assert hass.states.get(SPEED_ENTITY) is not None

    mock_client.get_appliances.return_value = _without_speed_signal(appliances)
    await async_poll(hass)
    assert _speed_entity_id(hass) is not None
    await async_poll(hass)
    assert _speed_entity_id(hass) is not None

    await async_poll(hass)
    assert _speed_entity_id(hass) is None
    assert hass.states.get(SPEED_ENTITY) is None
    # Its sibling signal is untouched.
    assert hass.states.get("button.fan_power") is not None


async def test_removal_is_logged(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Deleting a registry entry leaves a trace in the log.

    Nothing else records it — HA core logs entity creation but not removal —
    so a wrongful eviction would otherwise be indistinguishable from an entity
    that was never created, and the live verification of the grace period
    would have nothing to watch.
    """
    caplog.set_level(logging.INFO, logger="custom_components.nature_remo")
    mock_client.get_appliances.return_value = _without_speed_signal(appliances)

    await async_poll(hass, STALE_POLLS_BEFORE_REMOVAL)

    assert _speed_entity_id(hass) is None
    assert SPEED_ENTITY in caplog.text
    assert SPEED_UNIQUE_ID in caplog.text
    assert "3 consecutive polls" in caplog.text


async def test_smart_meter_property_dropout_keeps_its_sensor(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A missing ECHONET property is a dropout, not a deletion.

    Smart-meter sensors are created only while their property is in the
    payload, so without separating that creation gate from the removal gate a
    transient EPC dropout (meter pairing hiccup, cloud-side omission) would
    delete the registry entry — taking the user's customizations and the
    energy dashboard's link to the entity with it — while the meter itself is
    still very much there.
    """
    entity_registry = er.async_get(hass)
    assert hass.states.get(POWER_ENTITY).state == "520"

    mock_client.get_appliances.return_value = _without_meter_property(
        appliances, EPC_INSTANTANEOUS_POWER
    )
    await async_poll(hass, STALE_POLLS_BEFORE_REMOVAL + 1)

    assert (
        entity_registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, POWER_UNIQUE_ID)
        is not None
    )
    assert hass.states.get(POWER_ENTITY).state == STATE_UNKNOWN

    # The reading returns to the same entity rather than to a fresh one.
    mock_client.get_appliances.return_value = appliances
    await async_poll(hass)
    assert hass.states.get(POWER_ENTITY).state == "520"


async def test_smart_meter_removal_still_takes_its_sensors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Retaining readings must not keep a deleted meter's sensors alive."""
    entity_registry = er.async_get(hass)
    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != METER_ID
    ]

    await async_poll(hass, STALE_POLLS_BEFORE_REMOVAL)

    assert (
        entity_registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, POWER_UNIQUE_ID)
        is None
    )
    assert hass.states.get(POWER_ENTITY) is None


async def test_device_event_dropout_keeps_its_sensor_and_offset(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    devices: list[Device],
) -> None:
    """A Remo that skips one measurement keeps that measurement's entities.

    Both the humidity sensor and its calibration offset are gated on the `hu`
    event showing up; the offset lives on the hub and is not affected by a
    missing reading at all.
    """
    entity_registry = er.async_get(hass)
    mock_client.get_devices.return_value = _without_device_event(devices, "hu")

    await async_poll(hass, STALE_POLLS_BEFORE_REMOVAL + 1)

    assert (
        entity_registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, HUMIDITY_UNIQUE_ID)
        is not None
    )
    assert hass.states.get("sensor.living_remo_humidity").state == STATE_UNKNOWN
    assert (
        entity_registry.async_get_entity_id(
            NUMBER_DOMAIN, DOMAIN, HUMIDITY_OFFSET_UNIQUE_ID
        )
        is not None
    )
    assert hass.states.get("number.living_remo_humidity_offset").state == "0.0"


async def test_returning_signal_resets_the_grace_period(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Misses must be consecutive: one poll reporting the id clears the streak."""
    missing = _without_speed_signal(appliances)

    mock_client.get_appliances.return_value = missing
    await async_poll(hass, 2)
    mock_client.get_appliances.return_value = appliances
    await async_poll(hass)
    mock_client.get_appliances.return_value = missing
    await async_poll(hass, 2)

    # Two misses before and two after, but never three in a row.
    assert _speed_entity_id(hass) is not None
    assert hass.states.get(SPEED_ENTITY) is not None


async def test_signal_returning_after_removal_is_recreated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """An id that comes back builds a fresh entity instead of staying gone.

    The old add-only sync tracked added ids in a set that never shrank, so a
    signal deleted and re-learned in the app stayed missing until a restart.
    """
    mock_client.get_appliances.return_value = _without_speed_signal(appliances)
    await async_poll(hass, 3)
    assert _speed_entity_id(hass) is None

    mock_client.get_appliances.return_value = appliances
    await async_poll(hass)

    assert _speed_entity_id(hass) is not None
    assert hass.states.get(SPEED_ENTITY) is not None


async def test_appliance_returning_after_device_removal_is_recreated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """An appliance gone long enough loses its device — and comes back whole.

    Removing the device cascades into its entity registry entries, which the
    platform sync never sees as removal candidates; it must still forget the
    ids, or re-adding the appliance would leave it entity-less.
    """
    device_registry = dr.async_get(hass)
    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-ir-1"
    ]
    await async_poll(hass, 3)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is None
    )
    assert _speed_entity_id(hass) is None

    mock_client.get_appliances.return_value = appliances
    await async_poll(hass)

    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )
    assert hass.states.get(SPEED_ENTITY) is not None
    assert hass.states.get("button.fan_power") is not None


async def test_optimistic_updates_do_not_advance_the_grace_period(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Command responses notify listeners but say nothing about missing ids.

    They push data through the same listeners as a poll, so without the
    poll_count guard three commands in a row would evict a live entity.
    """
    coordinator = init_integration.runtime_data
    mock_client.get_appliances.return_value = _without_speed_signal(appliances)
    await async_poll(hass)

    for _ in range(3):
        coordinator.async_update_appliance(
            coordinator.data.appliances["appliance-ac-1"]
        )
        await hass.async_block_till_done()
    assert coordinator.poll_count == 2  # setup + the one poll above

    await async_poll(hass)
    assert _speed_entity_id(hass) is not None
    await async_poll(hass)
    assert _speed_entity_id(hass) is None


async def test_orphan_registry_entry_is_swept(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Entries left by a previous run are removal candidates too.

    Removal candidates come from the entity registry rather than from what
    the running process added, which is what lets orphans predating this
    feature disappear without a manual cleanup.
    """
    mock_config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        BUTTON_DOMAIN,
        DOMAIN,
        "appliance-ir-1_signal_signal-gone",
        config_entry=mock_config_entry,
        suggested_object_id="fan_ghost",
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-ir-1_signal_signal-gone"
        )
        is not None
    )

    # The setup sync counted the first miss; two more polls finish the streak.
    await async_poll(hass, 2)

    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-ir-1_signal_signal-gone"
        )
        is None
    )
    assert hass.states.get(SPEED_ENTITY) is not None
