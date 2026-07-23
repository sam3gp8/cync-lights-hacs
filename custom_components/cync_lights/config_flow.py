"""Config flow for the Cync Lights integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_OTP
from .pycync.auth import Auth, TwoFactorRequiredError, AuthFailedError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_OTP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OTP): str,
    }
)


class CyncLightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cync Lights."""

    VERSION = 1

    def __init__(self) -> None:
        self._username: str | None = None
        self._password: str | None = None
        self._auth: Auth | None = None
        self._session: aiohttp.ClientSession | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial username/password step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._session = async_get_clientsession(self.hass)
            self._auth = Auth(
                self._session, username=self._username, password=self._password
            )

            try:
                user = await self._auth.login()
            except TwoFactorRequiredError:
                return await self.async_step_otp()
            except AuthFailedError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Cync login")
                errors["base"] = "cannot_connect"
            else:
                return self._async_create_entry(user)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the 2FA one-time-password step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input[CONF_OTP]
            try:
                user = await self._auth.login(otp)
            except AuthFailedError:
                errors["base"] = "invalid_otp"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error verifying Cync OTP")
                errors["base"] = "cannot_connect"
            else:
                return self._async_create_entry(user)

        return self.async_show_form(
            step_id="otp", data_schema=STEP_OTP_SCHEMA, errors=errors
        )

    def _async_create_entry(self, user) -> FlowResult:
        """Create the config entry once authentication succeeds."""
        return self.async_create_entry(
            title=self._username,
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                "access_token": user.access_token,
                "refresh_token": user.refresh_token,
                "authorize": user.authorize,
                "user_id": user.user_id,
                "expires_at": user.expires_at,
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication if the stored token becomes invalid."""
        self._username = entry_data.get(CONF_USERNAME)
        return await self.async_step_user()
