# WetterOnline for Home Assistant

Unofficial Home Assistant integration for the freely accessible location pages on
[WetterOnline](https://www.wetteronline.de/). No account or API key is required.

## Features

- UI setup using a city, postal code, WetterOnline path, or complete URL
- Multiple locations and reconfiguration from Devices & Services
- Current conditions plus 49-hour and 14-day forecasts
- Sensors for temperature, apparent temperature, dew point, pressure, humidity,
  wind, gusts, visibility, precipitation, UV, sunshine, smog and raw weather symbols
- Pollen, warnings, sun/moon, forecast text, editorial and nearby water data
- Current and animated, location-centred WetterOnline rain radar cameras
- Diagnostics and migration from the original 1.x config entry format

WetterOnline does not publish a supported public API. The integration reads the
structured JSON embedded in the public website and may require maintenance after
site changes. It polls every 15 minutes and does not access membership-only data.

## Installation

Install as a HACS custom repository or copy `custom_components/wetteronline` to the
matching directory in your Home Assistant configuration, restart Home Assistant,
then choose **Settings → Devices & services → Add integration → WetterOnline**.

Enter `Berlin`, `10115`, `/wetter/berlin`, or a complete WetterOnline location URL.
When a search is ambiguous, Home Assistant displays the matching locations.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run pytest
```

The radar uses WetterOnline precipitation layers over © OpenStreetMap contributors.
All weather data is attributed to WetterOnline.

## License

MIT — see [LICENSE](LICENSE).
