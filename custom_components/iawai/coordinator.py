
"""Data coordinator for the IAWAI Water integration."""

from datetime import datetime, time, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import IAWAIAuthenticationError, IAWAIClient, IAWAIError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_METER_GROUP_ID,
    CONF_METER_ID,
    CONF_PASSWORD,
    CONF_SITE_ID,
    CONF_USERNAME,
    NAME,
    TIME_ZONE,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class IAWAIDataUpdateCoordinator(DataUpdateCoordinator):
    """Fetch water consumption data from IAWAI."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
    ) -> None:
        """Initialise the coordinator."""
        session = async_get_clientsession(hass)

        self.client = IAWAIClient(
            session=session,
            username=config[CONF_USERNAME],
            password=config[CONF_PASSWORD],
            account_id=config[CONF_ACCOUNT_ID],
            site_id=config[CONF_SITE_ID],
            meter_group_id=config[CONF_METER_GROUP_ID],
            meter_id=config[CONF_METER_ID],
        )

        super().__init__(
            hass,
            _LOGGER,
            name=NAME,
            update_interval=UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        """Fetch all readings and compute yesterday and cumulative totals."""
        try:
            all_readings, cumulative_litres = (
                await self.client.fetch_cumulative_total()
            )

        except IAWAIAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                f"IAWAI credentials are no longer valid: {err}"
            ) from err

        except IAWAIError as err:
            raise UpdateFailed(
                f"Error communicating with IAWAI: {err}"
            ) from err

        # Isolate yesterday's readings for the daily sensor.
        local_tz = ZoneInfo(TIME_ZONE)
        today = datetime.now(local_tz).date()
        yesterday = today - timedelta(days=1)

        yesterday_start = int(
            datetime.combine(yesterday, time.min, tzinfo=local_tz).timestamp()
        )
        today_start = int(
            datetime.combine(today, time.min, tzinfo=local_tz).timestamp()
        )

        yesterday_readings = [
            (ts, litres)
            for ts, litres in all_readings
            if yesterday_start <= ts < today_start
        ]
        yesterday_litres = sum(litres for _, litres in yesterday_readings)

        _LOGGER.debug(
            "Cumulative total: %.1f L | Yesterday (%s): %.1f L "
            "from %d hourly readings",
            cumulative_litres,
            yesterday,
            yesterday_litres,
            len(yesterday_readings),
        )

        return {
            "all_readings": all_readings,
            "yesterday_readings": yesterday_readings,
            "yesterday_litres": yesterday_litres,
            "cumulative_litres": cumulative_litres,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
