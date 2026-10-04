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
    OVERLAP_DAYS,
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
    # Statistics helpers
    # ------------------------------------------------------------------

    async def _async_get_seed(self) -> tuple[float, date | None]:
        """Return (seed_sum, last_date) from the HA statistics DB.

        The overlap window means we always re-fetch and re-inject the
        last OVERLAP_DAYS days on every run. To avoid double-counting,
        we need the cumulative sum from the entry JUST BEFORE the
        overlap window starts — not from the latest entry.

        Example with OVERLAP_DAYS=2 and last_date=2026-09-30:
            overlap_start = 2026-09-28 00:00
            seed_sum = cumulative total at 2026-09-27 (last hour before window)
            fetch    = 2026-09-28 → today (2 days re-fetched + any new days)
            inject   = those readings on top of seed_sum

        This means any late-arriving hours within the overlap window
        are always caught and upserted correctly.

        Returns (0.0, None) on a fresh install.
        """
        recorder = get_instance(self.hass)

        # Step 1 — find the most recent DB entry to get last_date.
        last = await recorder.async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            STAT_ID,
            False,
            {"sum", "start"},
        )

        if not last or STAT_ID not in last or not last[STAT_ID]:
            _LOGGER.debug(
                "No existing statistics for %s — full history fetch required",
                STAT_ID,
            )
            return 0.0, None

        entry = last[STAT_ID][0]
        last_ts = entry.get("start")

        if not last_ts:
            return 0.0, None

        local_tz = ZoneInfo(TIME_ZONE)
        last_date = datetime.fromtimestamp(last_ts, tz=local_tz).date()

        # Step 2 — find the cumulative sum from just before the overlap
        # window starts. This is the fixed baseline for rebuilding the window.
        overlap_start = datetime.combine(
            last_date - timedelta(days=OVERLAP_DAYS),
            time.min,
            tzinfo=local_tz,
        )

        # Look back up to 3 days before overlap_start to find the last
        # recorded sum. A 1-hour window risks returning empty on data gaps;
        # a 3-day window is robust against any realistic gap in the series.
        result = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            overlap_start - timedelta(days=3),
            overlap_start,
            {STAT_ID},
            "hour",
            None,
            {"sum"},
        )

        entries = result.get(STAT_ID, [])
        seed_sum = float(entries[-1]["sum"]) if entries else 0.0

        _LOGGER.debug(
            "Last DB entry: %s | Overlap window starts: %s | Seed sum: %.1f L",
            last_date,
            overlap_start.date(),
            seed_sum,
        )
        return seed_sum, last_date

    def _publish_water_statistics(
        self,
        readings: list[tuple[int, float]],
        seed_sum: float,
    ) -> None:
        """Inject hourly water readings directly into HA statistics.

        Each reading is backdated to its actual Unix timestamp so the
        Water dashboard shows correct hourly bars even though data
        arrives with a ~24h lag from IAWAI.

        async_add_external_statistics performs upserts — safe to
        re-inject readings that already exist in the DB.

        seed_sum is the cumulative total from just before the overlap
        window. Readings are accumulated on top of it so the running
        total is correct without double-counting.
        """
        if not readings:
            _LOGGER.debug("No new readings to publish")
            return

        local_tz = ZoneInfo(TIME_ZONE)
        stats: list[StatisticData] = []
        running_sum = seed_sum

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
            "Injected %d hourly water statistics (%.1f L → %.1f L cumulative)",
            len(stats),
            seed_sum,
            running_sum,
        )

    # ------------------------------------------------------------------
    # Core update loop
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Fetch new readings, inject statistics, return sensor values."""

        # Seed from the DB.
        # seed_sum  — cumulative total just before the overlap window.
        # last_date — date of the most recent DB entry.
        # On first run both are zero/None → full history is fetched.
        seed_sum, last_date = await self._async_get_seed()

        # Fetch from OVERLAP_DAYS before last_date so late-arriving
        # hourly data within a partially published day is always caught.
        # On first run (last_date=None) fetches full history.
        since: date | None = None
        if last_date is not None:
            since = last_date - timedelta(days=OVERLAP_DAYS)

        _LOGGER.debug(
            "Fetching since %s (last_date=%s, overlap=%d days)",
            since, last_date, OVERLAP_DAYS,
        )

        # Resolve yesterday's boundaries once, before the API call.
        # We need these both for the fresh-data sum and as a fallback.
        local_tz = ZoneInfo(TIME_ZONE)
        today = datetime.now(local_tz).date()
        yesterday = today - timedelta(days=1)
        yesterday_start_ts = int(
            datetime.combine(yesterday, time.min, tzinfo=local_tz).timestamp()
        )
        today_start_ts = int(
            datetime.combine(today, time.min, tzinfo=local_tz).timestamp()
        )

        try:
            new_readings, new_total = (
                await self.client.fetch_cumulative_total(since=since)
            )

        except IAWAIAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                f"IAWAI credentials are no longer valid: {err}"
            ) from err

        except IAWAIError as err:
            raise UpdateFailed(
                f"Error communicating with IAWAI: {err}"
            ) from err

        # Inject readings starting from seed_sum. The overlap window
        # means some of these upsert existing entries — that is safe
        # and corrects any previously incomplete hours.
        self._publish_water_statistics(new_readings, seed_sum=seed_sum)

        # Cumulative total for the sensor = seed_sum + new_total.
        cumulative_litres = seed_sum + new_total

        # ── Yesterday's total ────────────────────────────────────────────
        #
        # Prefer summing directly from the freshly fetched readings.
        # async_add_external_statistics() only *queues* writes; querying
        # the DB on the same run races against uncommitted data and
        # produces a one-cycle lag (the bug this fixes).
        #
        # Fall back to the DB only when yesterday falls entirely outside
        # the fetch window — possible after a long outage but not in
        # normal hourly operation.
        yesterday_in_window = since is None or since <= yesterday
        if yesterday_in_window:
            yesterday_litres = sum(
                litres
                for ts, litres in new_readings
                if yesterday_start_ts <= ts < today_start_ts
            )
        else:
            # Rare fallback: yesterday predates our fetch window.
            yesterday_start_dt = datetime.combine(
                yesterday, time.min, tzinfo=local_tz
            )
            today_start_dt = datetime.combine(today, time.min, tzinfo=local_tz)
            recorder = get_instance(self.hass)
            result = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                yesterday_start_dt,
                today_start_dt,
                {STAT_ID},
                "hour",
                None,
                {"state"},
            )
            yesterday_litres = sum(
                entry.get("state") or 0.0
                for entry in result.get(STAT_ID, [])
            )
            _LOGGER.debug(
                "Yesterday (%s) from DB fallback: %.1f L", yesterday, yesterday_litres
            )

        _LOGGER.debug(
            "Cumulative total: %.1f L | Yesterday (%s): %.1f L | "
            "Processed: %d readings | Since: %s",
            cumulative_litres,
            yesterday,
            yesterday_litres,
            len(new_readings),
            since,
        )

        return {
            "yesterday_litres": yesterday_litres,
            "cumulative_litres": cumulative_litres,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
