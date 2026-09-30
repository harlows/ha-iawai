
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

    def _publish_water_statistics(
        self,
        readings: list[tuple[int, float]],
    ) -> None:
        """Inject hourly water readings directly into HA statistics.

        Each reading is backdated to its actual Unix timestamp so the
        Water dashboard shows correct hourly bars even though data
        arrives with a ~24h lag from IAWAI.

        async_add_external_statistics performs upserts — it is safe
        to re-inject readings that already exist in the DB. The
        cumulative sum is always recalculated from zero across all
        readings to ensure consistency.
        """
        if not readings:
            _LOGGER.debug("No readings to publish")
            return

        local_tz = ZoneInfo(TIME_ZONE)
        stats: list[StatisticData] = []
        running_sum = 0.0

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
            "Injected %d hourly water statistics (0.0 L → %.1f L cumulative)",
            len(stats),
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

        # Inject backdated hourly statistics into the HA recorder.
        # This powers the Water dashboard with correct hourly bars.
        # upserts mean re-injecting existing entries is safe.
        self._publish_water_statistics(all_readings)

        # Isolate yesterday's readings for the glanceable daily sensor.
        local_tz = ZoneInfo(TIME_ZONE)
        today = datetime.now(local_tz).date()
        yesterday = today - timedelta(days=1)

        yesterday_start = int(
            datetime.combine(yesterday, time.min, tzinfo=local_tz).timestamp()
        )
        today_start = int(
            datetime.combine(today, time.min, tzinfo=local_tz).timestamp()
        )

        yesterday_litres = sum(
            litres
            for ts, litres in all_readings
            if yesterday_start <= ts < today_start
        )

        _LOGGER.debug(
            "Cumulative total: %.1f L | Yesterday (%s): %.1f L",
            cumulative_litres,
            yesterday,
            yesterday_litres,
        )

        return {
            "yesterday_litres": yesterday_litres,
            "cumulative_litres": cumulative_litres,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
