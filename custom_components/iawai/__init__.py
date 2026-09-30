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

    await coordinator.async_config_entry_first_refresh()

    # Store coordinator on the entry — modern HA pattern (2024.x+).
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload IAWAI Water."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
