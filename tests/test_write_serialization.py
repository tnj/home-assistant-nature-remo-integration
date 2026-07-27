"""Tests for the per-appliance serialization of settings writes."""

import asyncio
from unittest.mock import AsyncMock, call

from aionatureremo import AirconSettings
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate import HVACMode
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import bedroom_aircon_settings

APPLIANCE_ID = "appliance-ac-2"
CLIMATE_ENTITY = "climate.bedroom_ac"
SWITCH_ENTITY = "switch.bedroom_ac_powerful"
TIME_ENTITY = "time.bedroom_ac_night_set_mode"

# Only ever reached when the hand-off under test regressed: in a passing run
# both events are set by the writers themselves, so nothing waits on a clock.
HANDOFF_TIMEOUT = 10


async def _wait(event: asyncio.Event) -> None:
    """Await an event, failing the test instead of hanging on a regression."""
    async with asyncio.timeout(HANDOFF_TIMEOUT):
        await event.wait()


async def test_extras_write_waits_for_the_in_flight_climate_write(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A concurrent extras write builds its payload on the climate response.

    Every settings payload embeds the FULL extras dict — extras omitted from
    a write are cleared server-side — so two platforms writing the same
    appliance must not interleave. Here the climate write's response reveals
    a sleep timer the last poll never saw; the switch write that was already
    queued has to merge it in. Without the per-appliance write lock (or with
    the appliance read hoisted out of it) the switch would build its payload
    from the pre-write snapshot and silently wipe new_sleep.
    """
    coordinator = init_integration.runtime_data
    lock = coordinator.async_write_lock(APPLIANCE_ID)
    original_acquire = lock.acquire
    queued_behind_climate = asyncio.Event()

    async def _tracking_acquire() -> bool:
        # Set only when a second writer arrives while the first still holds
        # the lock, which is exactly the race under test.
        if lock.locked():
            queued_behind_climate.set()
        return await original_acquire()

    lock.acquire = _tracking_acquire  # type: ignore[method-assign]

    climate_write_started = asyncio.Event()
    release_climate_write = asyncio.Event()
    climate_response = bedroom_aircon_settings(
        button="power-off", extra={"powerful": "off", "new_sleep": "22:00"}
    )
    switch_response = bedroom_aircon_settings(
        button="power-off", extra={"powerful": "on", "new_sleep": "22:00"}
    )

    async def _blocking_first_write(
        appliance_id: str, **kwargs: object
    ) -> AirconSettings:
        if mock_client.set_aircon_settings.call_count == 1:
            climate_write_started.set()
            await release_climate_write.wait()
            return climate_response
        return switch_response

    mock_client.set_aircon_settings.side_effect = _blocking_first_write

    climate_task = hass.async_create_task(
        hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: CLIMATE_ENTITY},
            blocking=True,
        )
    )
    switch_task = None
    try:
        await _wait(climate_write_started)
        switch_task = hass.async_create_task(
            hass.services.async_call(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: SWITCH_ENTITY},
                blocking=True,
            )
        )
        await _wait(queued_behind_climate)
        # The switch is parked on the lock: it has issued no API call of its
        # own while the climate write is still in flight.
        assert mock_client.set_aircon_settings.call_count == 1
        assert not switch_task.done()
    finally:
        # Never leave the mocked write blocked: a regression has to surface as
        # a failed assertion, not as a hung test run.
        release_climate_write.set()

    await climate_task
    assert switch_task is not None
    await switch_task
    await hass.async_block_till_done()

    assert mock_client.set_aircon_settings.call_count == 2
    climate_call, switch_call = mock_client.set_aircon_settings.call_args_list
    # The climate write saw only what the last poll reported.
    assert climate_call.kwargs["button"] == "power-off"
    assert climate_call.kwargs["extra"] == {"powerful": "off"}
    # The switch write saw the climate response: the power button it left
    # behind and the sleep timer it revealed, plus its own new value.
    assert switch_call == call(
        APPLIANCE_ID,
        button="power-off",
        extra={"powerful": "on", "new_sleep": "22:00"},
    )

    switch_state = hass.states.get(SWITCH_ENTITY)
    assert switch_state is not None
    assert switch_state.state == STATE_ON
    climate_state = hass.states.get(CLIMATE_ENTITY)
    assert climate_state is not None
    assert climate_state.state == HVACMode.OFF
    # The revealed extra survived both writes rather than being cleared.
    time_state = hass.states.get(TIME_ENTITY)
    assert time_state is not None
    assert time_state.state == "22:00:00"
