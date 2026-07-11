"""Warning binary sensor for WetterOnline."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WetterOnlineConfigEntry
from .coordinator import WeatherOnlineDataUpdateCoordinator, WetterOnlineEntityMixin


def _warnings(value: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    for key in ("warnings", "items", "alerts"):
        if isinstance(value.get(key), list):
            return [item for item in value[key] if isinstance(item, dict)]
    return [value] if value else []


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up warning state."""
    async_add_entities([WetterOnlineWarning(entry.runtime_data)])


class WetterOnlineWarning(
    WetterOnlineEntityMixin,
    CoordinatorEntity[WeatherOnlineDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Whether WetterOnline has an active warning for the location."""

    _attr_translation_key = "weather_warning"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: WeatherOnlineDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.data.location.gid}_warning"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return bool(_warnings(self.coordinator.data.warnings))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"warnings": _warnings(self.coordinator.data.warnings)}
