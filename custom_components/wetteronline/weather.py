"""Weather entity for WetterOnline."""

from __future__ import annotations

from typing import Any, cast, override

from homeassistant.components.weather import (
    Forecast,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WetterOnlineConfigEntry
from .const import map_condition
from .coordinator import WeatherOnlineDataUpdateCoordinator, WetterOnlineEntityMixin


def _temperature(value: Any, key: str = "celsius") -> float | None:
    if isinstance(value, dict):
        value = value.get(key)
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _wind(value: dict[str, Any], key: str = "value") -> float | None:
    try:
        return float(value["speed"]["kilometer_per_hour"][key])
    except KeyError, TypeError, ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the weather entity."""
    async_add_entities([WetterOnlineWeather(entry.runtime_data)])


class WetterOnlineWeather(
    WetterOnlineEntityMixin,
    SingleCoordinatorWeatherEntity[WeatherOnlineDataUpdateCoordinator],
):
    """Current conditions and forecasts."""

    _attr_name = None
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_visibility_unit = UnitOfLength.METERS
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(self, coordinator: WeatherOnlineDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.data.location.gid}_weather"
        self._attr_device_info = coordinator.device_info

    @property
    def _current(self) -> dict[str, Any]:
        return self.coordinator.data.current

    @property
    @override
    def condition(self) -> str | None:
        return map_condition(self._current.get("symbol"))

    @property
    @override
    def native_temperature(self) -> float | None:
        return _temperature(self._current.get("air_temperature"))

    @property
    @override
    def native_apparent_temperature(self) -> float | None:
        return _temperature(self._current.get("apparent_temperature"))

    @property
    @override
    def native_dew_point(self) -> float | None:
        return _temperature(self._current.get("dew_point"))

    @property
    @override
    def humidity(self) -> float | None:
        value = self._current.get("humidity")
        return round(float(value) * 100, 1) if value is not None else None

    @property
    @override
    def native_pressure(self) -> float | None:
        return _temperature(self._current.get("air_pressure"), "hpa")

    @property
    @override
    def native_wind_speed(self) -> float | None:
        return _wind(self._current.get("wind") or {})

    @property
    @override
    def native_wind_gust_speed(self) -> float | None:
        return _wind(self._current.get("wind") or {}, "max_gust")

    @property
    @override
    def wind_bearing(self) -> float | None:
        value = (self._current.get("wind") or {}).get("direction")
        return float(value) if value is not None else None

    @property
    @override
    def native_visibility(self) -> float | None:
        for item in self.coordinator.data.hourly:
            value = (item.get("visibility") or {}).get("meter")
            if value is not None:
                return float(value)
        return None

    @callback
    @override
    def _async_forecast_hourly(self) -> list[Forecast]:
        return [self._hourly(item) for item in self.coordinator.data.hourly]

    @callback
    @override
    def _async_forecast_daily(self) -> list[Forecast]:
        return [self._daily(item) for item in self.coordinator.data.daily]

    @staticmethod
    def _hourly(item: dict[str, Any]) -> Forecast:
        precipitation = item.get("precipitation") or {}
        result: dict[str, Any] = {
            "datetime": item["date"],
            "condition": map_condition(item.get("symbol")),
            "native_temperature": _temperature(item.get("air_temperature")),
            "native_apparent_temperature": _temperature(item.get("apparent_temperature")),
            "humidity": round(float(item["humidity"]) * 100, 1)
            if item.get("humidity") is not None
            else None,
            "precipitation_probability": round(float(precipitation.get("probability", 0)) * 100),
            "native_wind_speed": _wind(item.get("wind") or {}),
            "native_wind_gust_speed": _wind(item.get("wind") or {}, "max_gust"),
            "wind_bearing": (item.get("wind") or {}).get("direction"),
        }
        return cast(Forecast, {key: value for key, value in result.items() if value is not None})

    @staticmethod
    def _daily(item: dict[str, Any]) -> Forecast:
        temperature = item.get("air_temperature") or {}
        apparent = item.get("apparent_temperature") or {}
        precipitation = item.get("precipitation") or {}
        uv = item.get("uv_index") or {}
        result: dict[str, Any] = {
            "datetime": item["date"],
            "condition": map_condition(item.get("symbol")),
            "native_temperature": _temperature(temperature.get("max")),
            "native_templow": _temperature(temperature.get("min")),
            "native_apparent_temperature": _temperature(apparent.get("max")),
            "humidity": round(float(item["humidity"]) * 100, 1)
            if item.get("humidity") is not None
            else None,
            "precipitation_probability": round(float(precipitation.get("probability", 0)) * 100),
            "native_wind_speed": _wind(item.get("wind") or {}),
            "native_wind_gust_speed": _wind(item.get("wind") or {}, "max_gust"),
            "wind_bearing": (item.get("wind") or {}).get("direction"),
            "uv_index": uv.get("value"),
        }
        return cast(Forecast, {key: value for key, value in result.items() if value is not None})
