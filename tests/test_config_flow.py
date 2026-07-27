"""Tests for the Nature Remo config flow."""

from unittest.mock import AsyncMock

import pytest
from aionatureremo import NatureRemoAuthError, NatureRemoConnectionError, User
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN


async def test_user_flow_success(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """The happy path creates an entry titled with the account nickname."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "test-token"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alice"
    assert result["data"] == {CONF_API_TOKEN: "test-token"}
    assert result["result"].unique_id == "user-1"


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (NatureRemoAuthError(401, "bad token"), "invalid_auth"),
        (NatureRemoConnectionError("refused"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    side_effect: Exception,
    error: str,
) -> None:
    """Each failure shows an error and the flow can still finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_client.get_user.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "bad-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.get_user.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "test-token"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_aborts_on_duplicate_account(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same Nature account cannot be added twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "test-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """Reauth replaces the token on the existing entry."""
    result = await init_integration.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert init_integration.data[CONF_API_TOKEN] == "new-token"


async def test_reauth_flow_shows_error_on_invalid_token(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """An invalid token during reauth surfaces an error, not a crash."""
    result = await init_integration.start_reauth_flow(hass)

    mock_client.get_user.side_effect = NatureRemoAuthError(401, "bad token")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "bad-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_wrong_account(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """A token for a different Nature account is rejected."""
    result = await init_integration.start_reauth_flow(hass)

    mock_client.get_user.return_value = User(id="user-2", nickname="Bob")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "other-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert init_integration.data[CONF_API_TOKEN] == "test-token"


async def test_reconfigure_flow_shows_error_on_invalid_token(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """An invalid token during reconfigure surfaces an error, not a crash."""
    result = await init_integration.start_reconfigure_flow(hass)

    mock_client.get_user.side_effect = NatureRemoAuthError(401, "bad token")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "bad-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    init_integration: MockConfigEntry,
) -> None:
    """Reconfigure swaps the token for the same account."""
    result = await init_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "rotated-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data[CONF_API_TOKEN] == "rotated-token"
