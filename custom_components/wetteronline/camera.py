"""Current and animated WetterOnline radar cameras."""

from __future__ import annotations

import asyncio
import base64
import math
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, override
from urllib.parse import urlencode

from aiohttp import ClientError, ClientSession
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from PIL import Image, ImageDraw

from . import WetterOnlineConfigEntry
from .const import ATTRIBUTION
from .coordinator import WeatherOnlineDataUpdateCoordinator

METADATA_URL = "https://tiles.wo-cloud.com/metadata"
COMPOSITE_URL = "https://tiles.wo-cloud.com/composite"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
HEADERS = {
    "User-Agent": "HomeAssistant-WetterOnline/2.0 (+https://github.com/GLG9/home-assistant-wetteronline)"
}


def _tile(latitude: float, longitude: float, zoom: int = 8) -> tuple[int, int]:
    lat = math.radians(max(min(latitude, 85.0511), -85.0511))
    n = 2**zoom
    return (
        int((longitude + 180.0) / 360.0 * n),
        int((1.0 - math.asinh(math.tan(lat)) / math.pi) / 2.0 * n),
    )


def _layer_path(layer: dict[str, Any]) -> str:
    return f"{layer['ptypPath']}{layer['path']}/{'/'.join(layer['timePath'])}"


class RadarRenderer:
    """Fetch public radar layers and render them over OpenStreetMap."""

    def __init__(self, session: ClientSession, latitude: float, longitude: float) -> None:
        self.session = session
        self.latitude = latitude
        self.longitude = longitude
        self._base: bytes | None = None
        self._current: tuple[datetime, bytes] | None = None
        self._animation: tuple[datetime, bytes] | None = None
        self._lock = asyncio.Lock()
        tile_x, tile_y = _tile(latitude, longitude)
        block_x, block_y = tile_x // 2 * 2, tile_y // 2 * 2
        world_x = (longitude + 180.0) / 360.0 * 256
        lat_rad = math.radians(latitude)
        world_y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * 256
        local_x, local_y = (world_x - block_x) * 256, (world_y - block_y) * 256
        self._left = block_x - 2 if local_x < 384 else block_x
        self._top = block_y - 2 if local_y < 384 else block_y
        marker_x = int((world_x - self._left) * 256)
        marker_y = int((world_y - self._top) * 256)
        self._marker = (marker_x, marker_y)
        self._crop = (marker_x - 384, marker_y - 384, marker_x + 384, marker_y + 384)
        self._origins = [(self._left + dx, self._top + dy) for dy in (0, 2) for dx in (0, 2)]

    async def _metadata(self) -> dict[str, Any]:
        async with self.session.get(
            METADATA_URL,
            params={
                "lg": "wr",
                "newMetadata": "true",
                "period": "periodCurrentLowRes",
                "type": "period",
            },
            headers=HEADERS,
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def _base_map(self) -> bytes:
        if self._base:
            return self._base
        urls = [
            OSM_URL.format(z=8, x=self._left + dx, y=self._top + dy)
            for dy in range(4)
            for dx in range(4)
        ]

        async def fetch(url: str) -> bytes:
            async with self.session.get(url, headers=HEADERS) as response:
                response.raise_for_status()
                return await response.read()

        tiles = await asyncio.gather(*(fetch(url) for url in urls))
        self._base = await asyncio.to_thread(self._compose_base, tiles)
        return self._base

    def _compose_base(self, tiles: list[bytes]) -> bytes:
        canvas = Image.new("RGBA", (1024, 1024))
        for index, raw in enumerate(tiles):
            image = Image.open(BytesIO(raw)).convert("RGBA")
            canvas.alpha_composite(image, ((index % 4) * 256, (index // 4) * 256))
        out = BytesIO()
        canvas.save(out, "PNG")
        return out.getvalue()

    async def _radar_layer(self, timestep: dict[str, Any], x0: int, y0: int) -> bytes:
        x7, y7 = x0 // 4 * 2, y0 // 4 * 2
        layers = timestep.get("layers") or {}
        europe = (layers.get("europe") or {}).get("rain")
        global_layer = (layers.get("global") or {}).get("rain")
        if not europe or not global_layer:
            raise ValueError("No WetterOnline radar layer for this timestep")
        descriptor = (
            f"r|2;;0;1;false|{_layer_path(europe)}/ZL7/522/sprite/{x7}_{y7}.png;"
            f"{_layer_path(global_layer)}/ZL7/522/border/{x7}_{y7}.png"
        )
        params = {
            "format": "webp",
            "k": "0",
            "lg": "wr",
            "tiles": base64.b64encode(descriptor.encode()).decode(),
            "time": timestep["id"],
        }
        async with self.session.get(
            f"{COMPOSITE_URL}?{urlencode(params)}", headers=HEADERS
        ) as response:
            response.raise_for_status()
            return await response.read()

    async def _radar_layers(self, timestep: dict[str, Any]) -> list[bytes]:
        layers = await asyncio.gather(
            *(self._radar_layer(timestep, x, y) for x, y in self._origins),
            return_exceptions=True,
        )
        return [layer if isinstance(layer, bytes) else b"" for layer in layers]

    def _compose_frame(self, base: bytes, radar_layers: list[bytes], label: str) -> Image.Image:
        image = Image.open(BytesIO(base)).convert("RGBA")
        for (x, y), radar in zip(self._origins, radar_layers, strict=True):
            if radar:
                layer = Image.open(BytesIO(radar)).convert("RGBA").resize((512, 512))
                image.alpha_composite(layer, ((x - self._left) * 256, (y - self._top) * 256))
        draw = ImageDraw.Draw(image)
        px, py = self._marker
        draw.ellipse(
            (px - 10, py - 10, px + 10, py + 10),
            fill="#00a7d1",
            outline="white",
            width=3,
        )
        image = image.crop(self._crop)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 738, 768, 768), fill=(0, 0, 0, 175))
        draw.text((10, 746), f"{label} · WetterOnline · © OpenStreetMap", fill="white")
        return image

    async def current(self) -> bytes | None:
        """Return a cached current radar PNG."""
        if self._current and datetime.now(UTC) - self._current[0] < timedelta(minutes=5):
            return self._current[1]
        async with self._lock:
            try:
                metadata, base = await asyncio.gather(self._metadata(), self._base_map())
                step = metadata["timesteps"][metadata["defaultIndex"]]
                radar = await self._radar_layers(step)
                image = await asyncio.to_thread(self._compose_frame, base, radar, step["id"])
                out = BytesIO()
                await asyncio.to_thread(image.convert("RGB").save, out, "PNG")
                self._current = (datetime.now(UTC), out.getvalue())
            except ClientError, TimeoutError, KeyError, ValueError, OSError:
                return self._current[1] if self._current else None
        return self._current[1]

    async def animation(self) -> bytes | None:
        """Return a cached 13-frame radar GIF."""
        if self._animation and datetime.now(UTC) - self._animation[0] < timedelta(minutes=5):
            return self._animation[1]
        async with self._lock:
            try:
                metadata, base = await asyncio.gather(self._metadata(), self._base_map())
                index = int(metadata["defaultIndex"])
                steps = metadata["timesteps"][max(0, index - 6) : index + 7]
                layers = await asyncio.gather(
                    *(self._radar_layers(step) for step in steps), return_exceptions=True
                )
                frames = [
                    await asyncio.to_thread(self._compose_frame, base, layer, step["id"])
                    for step, layer in zip(steps, layers, strict=True)
                    if isinstance(layer, list)
                ]
                if not frames:
                    return self._animation[1] if self._animation else None
                out = BytesIO()
                await asyncio.to_thread(
                    frames[0].convert("P").save,
                    out,
                    "GIF",
                    save_all=True,
                    append_images=[frame.convert("P") for frame in frames[1:]],
                    duration=650,
                    loop=0,
                    optimize=True,
                )
                self._animation = (datetime.now(UTC), out.getvalue())
            except ClientError, TimeoutError, KeyError, ValueError, OSError:
                return self._animation[1] if self._animation else None
        return self._animation[1]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up current and animated radar cameras."""
    coordinator = entry.runtime_data
    location = coordinator.data.location
    renderer = RadarRenderer(async_get_clientsession(hass), location.latitude, location.longitude)
    async_add_entities(
        [
            WetterOnlineRadarCamera(coordinator, renderer, False),
            WetterOnlineRadarCamera(coordinator, renderer, True),
        ]
    )


class WetterOnlineRadarCamera(Camera):
    """A WetterOnline radar still or animation camera."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WeatherOnlineDataUpdateCoordinator,
        renderer: RadarRenderer,
        animated: bool,
    ) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.renderer = renderer
        self.animated = animated
        self._attr_translation_key = "weather_radar_animation" if animated else "weather_radar"
        self._attr_unique_id = (
            f"{coordinator.data.location.gid}_radar_{'animation' if animated else 'current'}"
        )
        self._attr_device_info = coordinator.device_info
        self.content_type = "image/gif" if animated else "image/png"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return await (self.renderer.animation() if self.animated else self.renderer.current())
