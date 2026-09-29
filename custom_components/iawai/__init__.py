
"""Set up the IAWAI Water integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

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

    # Fetch the initial data before creating entities.
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator for the sensor platform to access.
    hass.data.setdefault("iawai", {})
    hass.data["iawai"][entry.entry_id] = coordinator

    # Set up the sensor platform.
    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload IAWAI Water."""
    if not await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    ):
        return False

    hass.data["iawai"].pop(entry.entry_id)

    if not hass.data["iawai"]:
        hass.data.pop("iawai")

    return True
