"""Config flow for the Nature Remo integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aionatureremo import NatureRemoAuthError, NatureRemoClient, NatureRemoError, User
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_TOKEN_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_TOKEN): str})
TOKEN_URL_PLACEHOLDERS = {"token_url": "https://home.nature.global/"}


class NatureRemoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Nature Remo config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def _async_validate(self, token: str, errors: dict[str, str]) -> User | None:
        """Validate the token, filling errors on failure."""
        client = NatureRemoClient(token, async_get_clientsession(self.hass))
        try:
            return await client.get_user()
        except NatureRemoAuthError:
            errors["base"] = "invalid_auth"
        except NatureRemoError as err:
            # cannot_connect covers 429s and transient network trouble; keep a
            # trace so the cause is diagnosable from the log.
            _LOGGER.debug("Token validation failed: %s", err)
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating the access token")
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the personal access token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user = await self._async_validate(user_input[CONF_API_TOKEN], errors)
            if user is not None:
                await self.async_set_unique_id(user.id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user.nickname, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
            description_placeholders=TOKEN_URL_PLACEHOLDERS,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after an authentication failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a replacement token for the same account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user = await self._async_validate(user_input[CONF_API_TOKEN], errors)
            if user is not None:
                await self.async_set_unique_id(user.id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
            description_placeholders=TOKEN_URL_PLACEHOLDERS,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user replace the token from the UI."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user = await self._async_validate(user_input[CONF_API_TOKEN], errors)
            if user is not None:
                await self.async_set_unique_id(user.id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
        )
