"""Config flow for the Nature Remo integration.

This is a minimal placeholder. Home Assistant requires an importable
``config_flow`` platform for any domain that sets up config entries via
``hass.config_entries.async_setup`` -- this holds regardless of the
``config_flow`` value in ``manifest.json``, and independent of whether any
UI flow step is defined yet. The full user / reauth / reconfigure flow is
implemented in a later task, which replaces this file outright.
"""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class NatureRemoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Placeholder handler; replaced by a later task's full implementation."""
