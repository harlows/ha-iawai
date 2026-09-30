
"""Sensors for the IAWAI Water integration."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import IAWAIDataUpdateCoordinator


SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="cumulative",
        name="Total water consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        # Powers the HA Water dashboard. Continuously rising
        # lifetime total — HA calculates daily/weekly/monthly
        # deltas from it automatically.
    ),
    SensorEntityDescription(
        key="yesterday",
        name="Yesterday's consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-outline",
        # Glanceable daily total. Resets each day.
        # Not suitable for the Water dashboard — use cumulative.
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IAWAI water sensors from a config entry."""
    coordinator: IAWAIDataUpdateCoordinator = entry.runtime_data

    async_add_entities(
        IAWAIWaterSensor(coordinator, description, entry)
        for description in SENSORS
    )


class IAWAIWaterSensor(
    CoordinatorEntity[IAWAIDataUpdateCoordinator],
    SensorEntity,
):
    """Representation of an IAWAI water consumption sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: IAWAIDataUpdateCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)

        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Oplex",
            model="IAWAI water meter",
        )

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None

        if self.entity_description.key == "cumulative":
            return self.coordinator.data["cumulative_litres"]

        return self.coordinator.data["yesterday_litres"]
