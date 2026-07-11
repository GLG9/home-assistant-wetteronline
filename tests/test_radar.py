"""Radar projection tests."""

from io import BytesIO
from unittest.mock import AsyncMock

from aiohttp import ClientSession
from PIL import Image

from custom_components.wetteronline.camera import RadarRenderer, _tile


def test_web_mercator_tile() -> None:
    x, y = _tile(52.517, 13.4)
    assert (x, y) == (137, 83)


def _base_map() -> bytes:
    out = BytesIO()
    Image.new("RGBA", (1024, 1024), "#dce7ed").save(out, "PNG")
    return out.getvalue()


async def test_current_radar_is_centered_and_cached() -> None:
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"defaultIndex": 0, "timesteps": [{"id": "202607120000"}]}
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            return_value=[b"", b"", b"", b""]
        )

        first = await renderer.current()
        second = await renderer.current()

    assert first == second
    assert renderer._metadata.await_count == 1
    image = Image.open(BytesIO(first))
    assert image.size == (768, 768)
    assert image.getpixel((384, 384)) == (0, 167, 209)


async def test_animation_skips_unavailable_frames() -> None:
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "defaultIndex": 1,
                "timesteps": [{"id": "old"}, {"id": "now"}, {"id": "future"}],
            }
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            side_effect=[ValueError("missing"), [b"", b"", b"", b""], ValueError("missing")]
        )

        animation = await renderer.animation()

    assert animation is not None
    image = Image.open(BytesIO(animation))
    assert image.format == "GIF"
    assert image.n_frames == 1
