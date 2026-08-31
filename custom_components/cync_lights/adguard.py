"""Minimal AdGuard Home API client for managing the cm.gelighting.com rewrite.

The integration uses this to point cm.gelighting.com at the Home Assistant host
automatically, so physical Cync devices connect to the local server instead of
Cync's cloud — without the user hand-editing AdGuard's rewrite list.

Only the three rewrite endpoints are used:
    GET  /control/rewrite/list
    POST /control/rewrite/add     {"domain", "answer"}
    POST /control/rewrite/delete  {"domain", "answer"}
Authentication is HTTP Basic against the AdGuard admin account.
"""
from __future__ import annotations

import logging
from typing import Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

CYNC_DEVICE_HOST = "cm.gelighting.com"


class AdGuardError(Exception):
    """Raised when an AdGuard API call fails."""


class AdGuardAuthError(AdGuardError):
    """Raised specifically when AdGuard rejects the credentials (HTTP 401)."""


class AdGuardClient:
    """Talks to an AdGuard Home instance's rewrite API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        # Normalize: strip trailing slash so path joins are clean.
        self._base = base_url.rstrip("/")
        self._session = session
        self._auth = aiohttp.BasicAuth(username, password) if username else None

    async def _request(self, method: str, path: str, json: dict | None = None):
        url = f"{self._base}{path}"
        try:
            async with self._session.request(
                method, url, json=json, auth=self._auth, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 401:
                    raise AdGuardAuthError(
                        "AdGuard authentication failed (check username/password)"
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise AdGuardError(f"AdGuard {method} {path} -> HTTP {resp.status}: {text[:200]}")
                if resp.content_type == "application/json":
                    return await resp.json()
                return await resp.text()
        except aiohttp.ClientError as err:
            raise AdGuardError(f"Could not reach AdGuard at {self._base}: {err}") from err

    async def async_test_connection(self) -> None:
        """Raise AdGuardError if the instance isn't reachable/authorized."""
        await self._request("GET", "/control/rewrite/list")

    async def async_list_rewrites(self) -> list[dict]:
        result = await self._request("GET", "/control/rewrite/list")
        return result if isinstance(result, list) else []

    async def async_get_cync_answer(self) -> Optional[str]:
        """Return the current rewrite target for the Cync host, if any."""
        for entry in await self.async_list_rewrites():
            if entry.get("domain") == CYNC_DEVICE_HOST:
                return entry.get("answer")
        return None

    async def async_set_cync_rewrite(self, host_ip: str) -> None:
        """Point cm.gelighting.com at host_ip, replacing any stale entry.

        Idempotent: if the correct rewrite already exists, does nothing; if a
        different one exists, removes it first.
        """
        current = await self.async_get_cync_answer()
        if current == host_ip:
            _LOGGER.debug("AdGuard rewrite already points %s -> %s", CYNC_DEVICE_HOST, host_ip)
            return
        if current is not None:
            await self._request(
                "POST",
                "/control/rewrite/delete",
                json={"domain": CYNC_DEVICE_HOST, "answer": current},
            )
            _LOGGER.debug("Removed stale AdGuard rewrite %s -> %s", CYNC_DEVICE_HOST, current)

        await self._request(
            "POST",
            "/control/rewrite/add",
            json={"domain": CYNC_DEVICE_HOST, "answer": host_ip},
        )
        _LOGGER.info("AdGuard rewrite set: %s -> %s", CYNC_DEVICE_HOST, host_ip)

    async def async_clear_cync_rewrite(self) -> None:
        """Remove the Cync rewrite so devices go back to the real cloud."""
        current = await self.async_get_cync_answer()
        if current is None:
            return
        await self._request(
            "POST",
            "/control/rewrite/delete",
            json={"domain": CYNC_DEVICE_HOST, "answer": current},
        )
        _LOGGER.info("AdGuard rewrite cleared for %s", CYNC_DEVICE_HOST)
