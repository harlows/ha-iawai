
"""Data coordinator for the IAWAI Water integration."""

from datetime import date, datetime, time, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfVolume
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
    DOMAIN,
    NAME,
    TIME_ZONE,
)

_LOGGER = logging.getLogger(__name__)

STAT_ID = f"{DOMAIN}:water_consumption"


class IAWAIDataUpdateCoordinator(DataUpdateCoordinator):
    """Fetch water consumption data from IAWAI."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
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
        super().__init__(hass, _LOGGER, name=NAME, update_interval=None)

    async def _async_get_seed(self) -> tuple[float, date | None]:
        """Return (seed_sum, last_date) from the HA statistics DB.

        seed_sum is the cumulative total at the last recorded hour.
        New readings are injected starting from that value.
        Returns (0.0, None) on a fresh install.
        """
        recorder = get_instance(self.hass)

        last = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, STAT_ID, False, {"sum", "start"},
        )
        if not last or STAT_ID not in last or not last[STAT_ID]:
            _LOGGER.debug("No existing statistics for %s — full history fetch required", STAT_ID)
            return 0.0, None

        entry = last[STAT_ID][0]
        if not entry.get("start"):
            return 0.0, None

        local_tz = ZoneInfo(TIME_ZONE)
        last_date = datetime.fromtimestamp(entry["start"], tz=local_tz).date()
        
        # Seed must come from the last recorded hour strictly BEFORE last_date.
        # Query backwards from the start of last_date to find it.
        seed_window_end = datetime.combine(last_date, time.min, tzinfo=local_tz)

        result = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            seed_window_end - timedelta(days=3),   # robust lookback
            seed_window_end,                        # exclusive: up to but not including last_date
            {STAT_ID}, "hour", None, {"sum"},
        )
        entries = result.get(STAT_ID, [])
        seed_sum = float(entries[-1]["sum"]) if entries else 0.0

        _LOGGER.debug(
           "Last DB entry: %s | Seed (last hour before %s): %.1f L",
           last_date, last_date, seed_sum,
        )
        return seed_sum, last_date
        
    def _publish_water_statistics(self, readings: list[tuple[int, float]], seed_sum: float) -> None:
        """Inject hourly water readings directly into HA statistics."""
        if not readings:
            _LOGGER.debug("No new readings to publish")
            return

        local_tz = ZoneInfo(TIME_ZONE)
        stats: list[StatisticData] = []
        running_sum = seed_sum

        for ts, litres in sorted(readings, key=lambda r: r[0]):
            dt = datetime.fromtimestamp(ts, tz=local_tz)
            running_sum += litres
            stats.append(StatisticData(start=dt, state=litres, sum=running_sum))

        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name="IAWAI Water Consumption",
                source=DOMAIN,
                statistic_id=STAT_ID,
                unit_of_measurement=UnitOfVolume.LITERS,
                mean_type=StatisticMeanType.NONE,
                unit_class="volume",
            ),
            stats,
        )
        _LOGGER.debug(
            "Injected %d hourly water statistics (%.1f L → %.1f L cumulative)",
            len(stats), seed_sum, running_sum,
        )

    async def _async_update_data(self) -> dict:
        """Fetch new readings, inject statistics, return sensor values."""
        seed_sum, last_date = await self._async_get_seed()

        since: date | None = last_date

        _LOGGER.debug("Fetching since %s (last_date=%s)", since, last_date)

        local_tz = ZoneInfo(TIME_ZONE)
        today = datetime.now(local_tz).date()
        yesterday = today - timedelta(days=1)
        yesterday_start_ts = int(datetime.combine(yesterday, time.min, tzinfo=local_tz).timestamp())
        today_start_ts = int(datetime.combine(today, time.min, tzinfo=local_tz).timestamp())

        try:
            new_readings, new_total = await self.client.fetch_cumulative_total(since=since)
        except IAWAIAuthenticationError as err:
            raise ConfigEntryAuthFailed(f"IAWAI credentials are no longer valid: {err}") from err
        except IAWAIError as err:
            raise UpdateFailed(f"Error communicating with IAWAI: {err}") from err

        self._publish_water_statistics(new_readings, seed_sum=seed_sum)
        cumulative_litres = seed_sum + new_total

        yesterday_in_window = since is None or since <= yesterday
        if yesterday_in_window:
            yesterday_litres = sum(
                litres for ts, litres in new_readings
                if yesterday_start_ts <= ts < today_start_ts
            )
        else:
            yesterday_start_dt = datetime.combine(yesterday, time.min, tzinfo=local_tz)
            today_start_dt = datetime.combine(today, time.min, tzinfo=local_tz)
            recorder = get_instance(self.hass)
            result = await recorder.async_add_executor_job(
                statistics_during_period, self.hass,
                yesterday_start_dt, today_start_dt,
                {STAT_ID}, "hour", None, {"state"},
            )
            yesterday_litres = sum(
                entry.get("state") or 0.0 for entry in result.get(STAT_ID, [])
            )
            _LOGGER.debug("Yesterday (%s) from DB fallback: %.1f L", yesterday, yesterday_litres)

        _LOGGER.debug(
            "Cumulative total: %.1f L | Yesterday (%s): %.1f L | "
            "Processed: %d readings | Since: %s",
            cumulative_litres, yesterday, yesterday_litres, len(new_readings), since,
        )

        return {
            "yesterday_litres": yesterday_litres,
            "cumulative_litres": cumulative_litres,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
