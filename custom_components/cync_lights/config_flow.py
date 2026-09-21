"""Config flow for the Cync Lights integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_OTP,
    CONF_ASSUME_AVAILABLE,
    CONF_ENABLE_LOCAL,
    CONF_HOST_IP,
    CONF_MANAGE_ADGUARD,
    CONF_ADGUARD_URL,
    CONF_ADGUARD_USERNAME,
    CONF_ADGUARD_PASSWORD,
    CONF_ENABLE_DNS,
    CONF_DNS_UPSTREAM,
    DEFAULT_DNS_UPSTREAM,
)
from .adguard import AdGuardClient, AdGuardError, AdGuardAuthError
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "CyncLightsOptionsFlow":
        return CyncLightsOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._username: str | None = None
        self._password: str | None = None
        self._auth: Auth | None = None
        self._session: aiohttp.ClientSession | None = None
        # Set when we are re-authenticating or reconfiguring an existing entry
        # rather than creating a brand new one.
        self._reauth_entry: config_entries.ConfigEntry | None = None
        # True when the flow was started by the user via "Reconfigure" (an
        # on-demand re-login) rather than an automatic reauth.
        self._is_reconfigure: bool = False

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
                return await self._async_finish(user)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA,
                {CONF_USERNAME: self._username} if self._username else None,
            ),
            errors=errors,
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
                return await self._async_finish(user)

        return self.async_show_form(
            step_id="otp", data_schema=STEP_OTP_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Triggered by ConfigEntryAuthFailed — start reauth for this entry."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._username = entry_data.get(CONF_USERNAME)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauthentication with the user (re-entering credentials)."""
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
                _LOGGER.exception("Unexpected error during Cync reauth")
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish(user)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA,
                {CONF_USERNAME: self._username} if self._username else None,
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """User-initiated re-login, available on demand from the entry's menu.

        Unlike reauth - which only fires when the stored credentials are
        rejected - this lets the user force a fresh login and reload the entry
        at any time, without deleting and re-adding the integration. A full
        fresh login re-establishes the Cync cloud session and re-probes
        devices, which can recover the "healthy connection but devices
        unavailable" state (a stale account session) that a background token
        refresh alone does not fix.
        """
        self._is_reconfigure = True
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
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
                _LOGGER.exception("Unexpected error during Cync reconfigure")
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish(user)

        if self._username is None and self._reauth_entry is not None:
            self._username = self._reauth_entry.data.get(CONF_USERNAME)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA,
                {CONF_USERNAME: self._username} if self._username else None,
            ),
            errors=errors,
        )

    async def _async_finish(self, user) -> FlowResult:
        """Create a new entry, or update the existing one on reauth."""
        token_data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            "access_token": user.access_token,
            "refresh_token": user.refresh_token,
            "authorize": user.authorize,
            "user_id": user.user_id,
            "expires_at": user.expires_at,
        }

        # Prevent two entries for the same account (also handles reauth match).
        await self.async_set_unique_id(str(user.user_id))
        if self._reauth_entry is not None:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data=token_data,
                reason="reconfigure_successful"
                if self._is_reconfigure
                else "reauth_successful",
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._username, data=token_data)


class CyncLightsOptionsFlow(config_entries.OptionsFlow):
    """Options: enable local control and configure AdGuard DNS automation."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single options page for the local-control settings."""
        errors: dict[str, str] = {}
        opts = self.config_entry.options

        if user_input is not None:
            # If AdGuard management is requested, validate the connection before
            # saving so the user gets immediate feedback rather than a silent
            # failure later.
            if user_input.get(CONF_ENABLE_LOCAL) and user_input.get(CONF_MANAGE_ADGUARD):
                if not user_input.get(CONF_ADGUARD_URL):
                    errors["base"] = "adguard_url_required"
                else:
                    session = async_get_clientsession(self.hass)
                    client = AdGuardClient(
                        session,
                        user_input[CONF_ADGUARD_URL],
                        user_input.get(CONF_ADGUARD_USERNAME, ""),
                        user_input.get(CONF_ADGUARD_PASSWORD, ""),
                    )
                    try:
                        await client.async_test_connection()
                    except AdGuardAuthError:
                        errors["base"] = "adguard_auth"
                    except AdGuardError:
                        errors["base"] = "adguard_cannot_connect"

            if user_input.get(CONF_ENABLE_LOCAL) and not user_input.get(CONF_HOST_IP):
                errors["base"] = "host_ip_required"

            # The built-in DNS server only helps if the local server is running
            # (it redirects devices to it) and needs HA's IP to answer with.
            if user_input.get(CONF_ENABLE_DNS):
                if not user_input.get(CONF_ENABLE_LOCAL):
                    errors["base"] = "dns_needs_local"
                elif not user_input.get(CONF_HOST_IP):
                    errors["base"] = "host_ip_required"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ASSUME_AVAILABLE,
                    default=opts.get(CONF_ASSUME_AVAILABLE, False),
                ): bool,
                vol.Required(
                    CONF_ENABLE_LOCAL,
                    default=opts.get(CONF_ENABLE_LOCAL, False),
                ): bool,
                vol.Optional(
                    CONF_HOST_IP,
                    default=opts.get(CONF_HOST_IP, ""),
                ): str,
                vol.Required(
                    CONF_ENABLE_DNS,
                    default=opts.get(CONF_ENABLE_DNS, False),
                ): bool,
                vol.Optional(
                    CONF_DNS_UPSTREAM,
                    default=opts.get(CONF_DNS_UPSTREAM, DEFAULT_DNS_UPSTREAM),
                ): str,
                vol.Required(
                    CONF_MANAGE_ADGUARD,
                    default=opts.get(CONF_MANAGE_ADGUARD, False),
                ): bool,
                vol.Optional(
                    CONF_ADGUARD_URL,
                    default=opts.get(CONF_ADGUARD_URL, "http://homeassistant.local:3000"),
                ): str,
                vol.Optional(
                    CONF_ADGUARD_USERNAME,
                    default=opts.get(CONF_ADGUARD_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_ADGUARD_PASSWORD,
                    default=opts.get(CONF_ADGUARD_PASSWORD, ""),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
