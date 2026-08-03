"""Tests for the Nature Remo coordinator."""

import asyncio
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aionatureremo import (
    Appliance,
    NatureRemoAuthError,
    NatureRemoConnectionError,
    NatureRemoRateLimitError,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.coordinator import NatureRemoCoordinator


@pytest.fixture
def coordinator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> NatureRemoCoordinator:
    """Build a coordinator wired to the mocked client."""
    mock_config_entry.add_to_hass(hass)
    return NatureRemoCoordinator(hass, mock_config_entry, mock_client)


async def test_update_success(coordinator: NatureRemoCoordinator) -> None:
    """A successful update indexes devices and appliances by id."""
    data = await coordinator._async_update_data()

    assert set(data.devices) == {"device-remo3-1", "device-mini-1", "device-remoe-1"}
    assert set(data.appliances) == {
        "appliance-ac-1",
        "appliance-ac-2",
        "appliance-tv-1",
        "appliance-light-1",
        "appliance-ir-1",
        "appliance-meter-1",
        "appliance-floorheater-1",
        "appliance-projector-1",
    }


async def test_auth_error_raises_config_entry_auth_failed(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """A 401 from the API triggers reauth."""
    mock_client.get_devices.side_effect = NatureRemoAuthError(401, "bad token")

    with pytest.raises(ConfigEntryAuthFailed) as exc_info:
        await coordinator._async_update_data()
    assert exc_info.value.translation_key == "auth_failed"


async def test_rate_limit_raises_update_failed_with_reset(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """A 429 names when requests are accepted again and defers the next poll."""
    reset = int(dt_util.utcnow().timestamp()) + 120
    mock_client.get_appliances.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=reset
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()
    assert exc_info.value.translation_key == "update_rate_limited"
    assert exc_info.value.translation_placeholders is not None
    reported = exc_info.value.translation_placeholders["reset"]
    assert datetime.fromisoformat(reported) == dt_util.utc_from_timestamp(reset)
    assert exc_info.value.retry_after is not None
    assert 0 < exc_info.value.retry_after <= 120


async def test_rate_limit_with_a_past_reset_keeps_the_normal_interval(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """A reset already behind us must not schedule an immediate retry.

    ``retry_after`` becomes the next update interval verbatim, so a zero
    or negative delay would poll in a tight loop.
    """
    mock_client.get_appliances.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=1752825600
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()
    assert exc_info.value.translation_key == "update_rate_limited"
    assert exc_info.value.retry_after is None


async def test_rate_limit_without_reset_raises_update_failed(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """A 429 with no reset header degrades to a plain update failure.

    "resets at epoch None" must never reach the UI; without a known reset
    the rate-limit error is just another failed poll.
    """
    mock_client.get_appliances.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=None
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()
    assert exc_info.value.translation_key == "update_failed"
    assert exc_info.value.translation_placeholders == {"error": "HTTP 429: limited"}


async def test_connection_error_raises_update_failed(
    coordinator: NatureRemoCoordinator, mock_client: AsyncMock
) -> None:
    """Network trouble becomes UpdateFailed."""
    mock_client.get_devices.side_effect = NatureRemoConnectionError("refused")

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()
    assert exc_info.value.translation_key == "update_failed"
    assert exc_info.value.translation_placeholders == {"error": "refused"}


async def test_optimistic_updates(coordinator: NatureRemoCoordinator) -> None:
    """async_update_appliance/device replace items and push new data."""
    coordinator.async_set_updated_data(await coordinator._async_update_data())

    appliance = replace(
        coordinator.data.appliances["appliance-ac-1"], nickname="Renamed AC"
    )
    coordinator.async_update_appliance(appliance)
    assert coordinator.data.appliances["appliance-ac-1"].nickname == "Renamed AC"

    device = replace(coordinator.data.devices["device-remo3-1"], name="Renamed Remo")
    coordinator.async_update_device(device)
    assert coordinator.data.devices["device-remo3-1"].name == "Renamed Remo"


# Only ever reached when the merge under test regressed: in a passing run the
# fetch is released by the test itself, so nothing waits on a clock.
FETCH_TIMEOUT = 10


def block_appliance_fetch(
    mock_client: AsyncMock, result: list[Appliance]
) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold get_appliances open until released, signalling when it started."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def _blocking_get_appliances() -> list[Appliance]:
        started.set()
        await release.wait()
        return result

    mock_client.get_appliances.side_effect = _blocking_get_appliances
    return started, release


async def test_push_during_a_fetch_is_not_reverted_by_the_poll(
    hass: HomeAssistant,
    coordinator: NatureRemoCoordinator,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A write landing mid-poll survives the fetch that started before it.

    HA assigns coordinator.data from the in-flight fetch's result
    unconditionally and an optimistic push cancels the scheduled refresh, not
    a running one: without the merge the pre-write server snapshot would win
    and stay for a full update interval — long enough for the next writer to
    rebuild its payload from the rolled-back extras and wipe the earlier write
    server-side, the exact race the per-appliance write lock closes for
    writers alone.
    """
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    started, release = block_appliance_fetch(mock_client, appliances)

    refresh = hass.async_create_task(coordinator.async_refresh())
    try:
        async with asyncio.timeout(FETCH_TIMEOUT):
            await started.wait()
        coordinator.async_update_appliance(
            replace(coordinator.data.appliances["appliance-ac-1"], nickname="Pushed AC")
        )
        coordinator.async_update_device(
            replace(coordinator.data.devices["device-remo3-1"], name="Pushed Remo")
        )
    finally:
        # Never leave the fetch blocked: a regression must surface as a failed
        # assertion, not as a hung test run.
        release.set()
    await refresh

    assert coordinator.data.appliances["appliance-ac-1"].nickname == "Pushed AC"
    assert coordinator.data.devices["device-remo3-1"].name == "Pushed Remo"
    # Everything the writes did not touch still comes from the fetch.
    assert coordinator.data.appliances["appliance-ac-2"].nickname == "Bedroom AC"
    assert coordinator.data.devices["device-mini-1"].name == "Bedroom Remo mini"


async def test_push_before_a_fetch_is_replaced_by_server_data(
    coordinator: NatureRemoCoordinator,
) -> None:
    """Optimistic values are not sticky: a later poll's data wins."""
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    coordinator.async_update_appliance(
        replace(coordinator.data.appliances["appliance-ac-1"], nickname="Pushed AC")
    )

    coordinator.async_set_updated_data(await coordinator._async_update_data())

    assert coordinator.data.appliances["appliance-ac-1"].nickname == "Living AC"


async def test_push_during_a_fetch_does_not_resurrect_a_deleted_appliance(
    hass: HomeAssistant,
    coordinator: NatureRemoCoordinator,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """An id the fetch stopped reporting stays gone despite a mid-fetch push.

    Otherwise a command response would keep an appliance deleted in the Nature
    app alive forever and its entities would never reach the removal grace.
    """
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    started, release = block_appliance_fetch(
        mock_client,
        [appliance for appliance in appliances if appliance.id != "appliance-ac-1"],
    )

    refresh = hass.async_create_task(coordinator.async_refresh())
    try:
        async with asyncio.timeout(FETCH_TIMEOUT):
            await started.wait()
        coordinator.async_update_appliance(
            replace(coordinator.data.appliances["appliance-ac-1"], nickname="Pushed AC")
        )
    finally:
        release.set()
    await refresh

    assert "appliance-ac-1" not in coordinator.data.appliances
