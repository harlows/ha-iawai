
"""Data coordinator for the IAWAI Water integration."""

from datetime import datetime, time, timedelta, timezone
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
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Statistic ID used for the Water dashboard external statistics.
# Must be stable — changing it loses all dashboard history.
STAT_ID = f"{DOMAIN}:water_consumption"


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

    # ------------------------------------------------------------------
    # Statistics injection
    # ------------------------------------------------------------------

    async def _async_get_last_stat_sum(self) -> float:
        """Return the last cumulative sum stored in the HA statistics DB.

        Returns 0.0 on a fresh install (no existing statistics).
        The sum is used as the starting point for new injected entries
        so the cumulative total is never double-counted.
        """
        recorder = get_instance(self.hass)
        last = await recorder.async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            STAT_ID,
            False,
            {"sum"},
        )

        if not last or STAT_ID not in last or not last[STAT_ID]:
            _LOGGER.debug(
                "No existing statistics for %s — starting from 0", STAT_ID
            )
            return 0.0

        last_sum = last[STAT_ID][0].get("sum") or 0.0
        _LOGGER.debug(
            "Seeded cumulative sum from DB: %.1f L", last_sum
        )
        return last_sum

    def _publish_water_statistics(
        self,
        readings: list[tuple[int, float]],
        last_sum: float,
    ) -> None:
        """Inject hourly water readings directly into HA statistics.

        Each reading is backdated to its actual Unix timestamp so the
        Water dashboard shows correct hourly bars even though data
        arrives with a ~24h lag from IAWAI.

        async_add_external_statistics performs upserts — it is safe
        to re-inject readings that already exist in the DB. The
        cumulative sum is recalculated from last_sum each time to
        ensure consistency.
        """
        if not readings:
            _LOGGER.debug("No readings to publish")
            return

        local_tz = ZoneInfo(TIME_ZONE)
        stats: list[StatisticData] = []
        running_sum = last_sum

        for ts, litres in sorted(readings, key=lambda r: r[0]):
            dt = datetime.fromtimestamp(ts, tz=local_tz)
            running_sum += litres
            stats.append(
                StatisticData(
                    start=dt,
                    state=litres,       # value for this individual hour
                    sum=running_sum,    # cumulative total up to this hour
                )
            )

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
            "Injected %d hourly water statistics "
            "(%.1f L → %.1f L cumulative)",
            len(stats),
            last_sum,
            running_sum,
        )

    # ------------------------------------------------------------------
    # Core update loop
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Fetch all readings, inject statistics, return sensor values."""
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

        # ------------------------------------------------------------------
        # Inject backdated hourly statistics into the HA recorder.
        # This powers the Water dashboard with correct hourly bars.
        #
        # We always re-inject all readings because async_add_external_statistics
        # upserts — existing entries are updated, new ones are inserted.
        # The last_sum seed ensures the cumulative total is correct.
        # ------------------------------------------------------------------
        last_sum = await self._async_get_last_stat_sum()

        # On a fresh install last_sum is 0.0 and all readings are injected.
        # On subsequent runs last_sum is the DB total and all_readings
        # contains the full history — upserts handle the overlap safely.
        self._publish_water_statistics(all_readings, last_sum=0.0)

        # ------------------------------------------------------------------
        # Isolate yesterday's readings for the daily glanceable sensor.
        # ------------------------------------------------------------------
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
