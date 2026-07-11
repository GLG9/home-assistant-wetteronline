"""Data update coordinator for WetterOnline."""

from __future__ import annotations

import logging
from asyncio import timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, UPDATE_INTERVAL
from .wetteronline_api import WetterOnline, WetterOnlineData, WetterOnlineError

_LOGGER = logging.getLogger(__name__)


class WeatherOnlineDataUpdateCoordinator(DataUpdateCoordinator[WetterOnlineData]):
    """Fetch WetterOnline data shared by all entities for a location."""

    def __init__(self, hass: HomeAssistant, client: WetterOnline) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.client = client

    @property
    def device_info(self) -> DeviceInfo:
        """Return the service device metadata."""
        data = self.data
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, data.location.gid)},
            manufacturer=MANUFACTURER,
            model="Public weather service",
            name=data.location.name,
            configuration_url=self.client.complete_url,
        )

    async def _async_update_data(self) -> WetterOnlineData:
        try:
            async with timeout(20):
                return await self.client.async_get_weather()
        except (WetterOnlineError, TimeoutError) as err:
            raise UpdateFailed(f"Unable to update WetterOnline: {err}") from err


class WetterOnlineEntityMixin:
    """Common entity attributes."""

    _attr_attribution: str | None = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_should_poll = False
