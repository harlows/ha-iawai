"""API client for the IAWAI Water integration."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

import aiohttp

from .const import (
    API_AGGREGATION,
    API_BASE_URL,
    API_INTERVAL_SECONDS,
    LOGIN_PATH,
    REQUEST_TIMEOUT,
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

        _LOGGER.debug(
            "Successfully authenticated with IAWAI"
        )

    async def fetch_readings(
        self,
        start: int,
        end: int,
    ) -> list[tuple[int, float]]:
        """Fetch hourly water consumption readings."""
        if self._token is None:
            await self.authenticate()

        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Timezone": "Pacific/Auckland",
        }

        payload = {
            "From": start,
            "To": end,
            "Interval": API_INTERVAL_SECONDS,
            "Agg": API_AGGREGATION,
        }

        try:
            async with self.session.post(
                API_BASE_URL + self.meter_path,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            ) as response:

                if response.status == 401:
                    _LOGGER.debug(
                        "IAWAI token expired; re-authenticating"
                    )

                    await self.authenticate()

                    headers["Authorization"] = (
                        f"Bearer {self._token}"
                    )

                    async with self.session.post(
                        API_BASE_URL + self.meter_path,
                        headers=headers,
                        json=payload,
                        timeout=REQUEST_TIMEOUT,
                    ) as retry_response:
                        retry_response.raise_for_status()
                        result = await retry_response.json()

                else:
                    response.raise_for_status()
                    result = await response.json()

        except aiohttp.ClientError as err:
            raise IAWAIError(
                f"Unable to retrieve IAWAI water data: {err}"
            ) from err

        readings: list[tuple[int, float]] = []

        for item in result.get("data", []):
            values = item.get("value", [])

            if not values:
                continue

            first = values[0]

            # Oplex has returned both:
            #   [{"parsedValue": 23}]
            # and:
            #   [23.0]
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

    async def fetch_yesterday(self) -> list[tuple[int, float]]:
        """Fetch yesterday's completed hourly readings."""
        now = datetime.now(timezone.utc)

        current_hour = (
            int(now.timestamp()) // API_INTERVAL_SECONDS
        ) * API_INTERVAL_SECONDS

        end = current_hour
        start = end - 86400

        return await self.fetch_readings(start, end)
