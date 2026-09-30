"""API client for the IAWAI Water integration."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import logging

import aiohttp

from .const import (
    API_AGGREGATION,
    API_BASE_URL,
    API_INTERVAL_SECONDS,
    LOGIN_PATH,
    REQUEST_TIMEOUT,
    TIME_ZONE,
    WATER_DATA_PATH,
)

_LOGGER = logging.getLogger(__name__)


class IAWAIError(Exception):
    """Base exception for IAWAI API errors."""


class IAWAIAuthenticationError(IAWAIError):
    """Raised when authentication fails."""


class IAWAIClient:
    """Client for the IAWAI/Oplex API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        account_id: str,
        site_id: str,
        meter_group_id: str,
        meter_id: str,
    ) -> None:
        """Initialise the API client."""
        self.session = session
        self.username = username
        self.password = password

        self.meter_path = WATER_DATA_PATH.format(
            account_id=account_id,
            site_id=site_id,
            meter_group_id=meter_group_id,
            meter_id=meter_id,
        )

        self._token: str | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """Obtain a fresh bearer token."""
        try:
            async with self.session.post(
                API_BASE_URL + LOGIN_PATH,
                json={
                    "Username": self.username,
                    "Password": self.password,
                },
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise IAWAIAuthenticationError(
                        "IAWAI rejected the supplied credentials."
                    )

                response.raise_for_status()
                result = await response.json()

        except aiohttp.ClientError as err:
            raise IAWAIError(
                f"Unable to connect to IAWAI: {err}"
            ) from err

        token = result.get("token")

        if not token:
            raise IAWAIAuthenticationError(
                "IAWAI login response did not contain a token."
            )

        self._token = token
        _LOGGER.debug("Successfully authenticated with IAWAI")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_fetch(
        self,
        headers: dict,
        payload: dict,
    ) -> dict:
        """Single POST to the meter endpoint; raises on HTTP error."""
        async with self.session.post(
            API_BASE_URL + self.meter_path,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()
            return await response.json()

    def _build_headers(self) -> dict:
        """Return auth headers using the current token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Timezone": TIME_ZONE,
        }

    @staticmethod
    def _parse_readings(result: dict) -> list[tuple[int, float]]:
        """Extract (unix_timestamp, litres) tuples from an API response.

        Oplex has returned both:
            [{"parsedValue": 23}]
        and:
            [23.0]
        for the inner ``value`` list, so both shapes are handled.
        """
        readings: list[tuple[int, float]] = []

        for item in result.get("data", []):
            values = item.get("value", [])

            if not values:
                continue

            first = values[0]

            if isinstance(first, dict):
                value = first.get("parsedValue")
            else:
                value = first

            if value is None:
                continue

            timestamp = int(item["unixTime"])
            litres = float(value)
            readings.append((timestamp, litres))

        return readings

    # ------------------------------------------------------------------
    # Public fetch methods
    # ------------------------------------------------------------------

    async def fetch_readings(
        self,
        start: int,
        end: int,
    ) -> list[tuple[int, float]]:
        """Fetch hourly water consumption readings between two Unix timestamps.

        Handles a single token-expiry retry transparently.
        """
        if self._token is None:
            await self.authenticate()

        headers = self._build_headers()
        payload = {
            "From": start,
            "To": end,
            "Interval": API_INTERVAL_SECONDS,
            "Agg": API_AGGREGATION,
        }

        try:
            try:
                result = await self._do_fetch(headers, payload)

            except aiohttp.ClientResponseError as err:
                if err.status != 401:
                    raise

                _LOGGER.debug("IAWAI token expired; re-authenticating")
                await self.authenticate()
                headers = self._build_headers()
                result = await self._do_fetch(headers, payload)

        except aiohttp.ClientError as err:
            raise IAWAIError(
                f"Unable to retrieve IAWAI water data: {err}"
            ) from err

        return self._parse_readings(result)

    async def fetch_yesterday(self) -> list[tuple[int, float]]:
        """Fetch yesterday's hourly readings using local day boundaries."""
        local_tz = ZoneInfo(TIME_ZONE)
        today = datetime.now(local_tz).date()
        yesterday = today - timedelta(days=1)

        start = int(
            datetime.combine(yesterday, time.min, tzinfo=local_tz).timestamp()
        )
        end = int(
            datetime.combine(today, time.min, tzinfo=local_tz).timestamp()
        )

        return await self.fetch_readings(start, end)
