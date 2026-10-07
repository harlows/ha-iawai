
"""Set up the IAWAI Water integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import POLL_HOURS, POLL_MINUTE
from .coordinator import IAWAIDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up IAWAI Water from a config entry."""
    coordinator = IAWAIDataUpdateCoordinator(
        hass,
        dict(entry.data),
    )

    # Fetch all historical data before creating entities.
    # Note: first run makes multiple API calls (one per CHUNK_DAYS window
    # from HISTORY_START to yesterday) so may take 10–30 seconds.
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator on the entry — modern HA pattern (2024.x+).
    entry.runtime_data = coordinator

    # @callback ensures this runs on the event loop, not a thread executor,
    # making async_create_task safe to call (required in Python 3.14+).
    @callback
    def _schedule_refresh(_now) -> None:
        hass.async_create_task(coordinator.async_refresh())

    # Poll at 10:30 and 22:30 NZ local time, aligned to IAWAI's two
    # daily publish batches. Unsubscribed automatically on unload.
    entry.async_on_unload(
        async_track_time_change(
            hass,
            _schedule_refresh,
            hour=list(POLL_HOURS),
            minute=POLL_MINUTE,
            second=0,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload IAWAI Water."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
