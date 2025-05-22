"""API for fetching WetterOnline data."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import html
from typing import Any, Final
from zoneinfo import ZoneInfo
import json
import re

from aiohttp import ClientSession
import bs4

MIDNIGHT: Final = datetime.min.time()
HTTP_HEADERS: dict[str, str] = {
    "Accept-Encoding": "gzip",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
}


@dataclass
class WetterOnlineData:
    """Data from WetterOnline."""

    current_observations: dict[str, Any]
    daily_forecast: list[dict[str, Any]]
    hourly_forecast: list[dict[str, Any]]


class WetterOnline:
    """Main class to perform WetterOnline requests."""

    def __init__(self, session: ClientSession, url: str) -> None:  # noqa: D107
        self._session = session
        url = url.lstrip("/")
        self.complete_url = f"https://www.wetteronline.de/{url}"

    async def async_get_weather(self) -> WetterOnlineData:
        """Fetch data from WetterOnline."""
        async with self._session.get(
            self.complete_url, headers=HTTP_HEADERS, allow_redirects=False
        ) as resp:
            raw_html = html.unescape(await resp.text())
            weather_utils = WeatherUtils(raw_html)
            return WetterOnlineData(
                current_observations=weather_utils.current_observations(),
                daily_forecast=weather_utils.daily_forecast(),
                hourly_forecast=weather_utils.hourly_forecast(),
            )


class WeatherUtils:
    """Logic for extraction weather data from raw html."""

    def __init__(self, raw_html=None) -> None:  # noqa: D107
        self.timezone = None
        self.soup = bs4.BeautifulSoup(raw_html, "lxml")

    def current_observations(self) -> dict[str, Any]:
        """Return the current observations 4 day forecast of the given `url`."""

        temperature = (
            self.soup.find("div", {"id": "nowcast-card-temperature"})
            .find("div", {"class": "value"})
            .text
        )
        temperature = int(temperature)
        current_observations = {"temperature": temperature}

        current_observations_raw = (
            self.soup.find("div", {"id": "product_display"}).find("script").text
        )

        def clean(arg):
            return arg.strip().strip(",").strip('"')

        for line in current_observations_raw.split("\n"):
            line = line.strip()
            if "timeZone" in line:
                timezone = line.split("=")[1].strip()
                timezone = timezone.strip('";')
                self.timezone = ZoneInfo(timezone)
            if not line or line.startswith("WO") or line == "};":
                continue

            [key, value] = map(clean, line.split(":"))
            current_observations[key] = value

        return current_observations

    def hourly_forecast(self) -> list[dict[str, Any]]:
        """Return the hourly forecast of the given `url` for today and tomorrow."""

        today = datetime.combine(datetime.now(), MIDNIGHT, self.timezone)
        tomorrow = today + timedelta(days=1)

        scripts = self.soup.find("div", {"id": "hourly-container"}).find_all("script")
        forecast: list[dict[str, Any]] = []

        replace_keys = {
            "windGusts": "windGustsBft",
            "windDirection": "windDirectionLong",
            "windDirectionShortSector": "windDirection",
        }
        for script in scripts:
            # 1) JS-Text isolieren
            js_block = str(script).split("({")[1].split("})")[0]

            hourly_data_raw: list[str] = []
            # 2) Jetzt auf js_block iterieren
            for entry in js_block.split("\n"):
                if ":" not in entry:
                    continue

                key, value = entry.split(":", 1)
                key = replace_keys.get(key.strip(), key.strip())
                value = value.strip().rstrip(",;")

                if value not in {"true", "false", "null"} and not re.fullmatch(
                    r"-?\d+(?:[.,]\d+)?", value
                ):
                    value = json.dumps(value.strip('"'))   # Strings quoten

                hourly_data_raw.append(f'"{key}": {value}')

            hourly_json = "{" + ", ".join(hourly_data_raw) + "}"
            hourly_data = json.loads(hourly_json)
            hourly_data.pop("docrootVersion", None)

            daySynonym = hourly_data["daySynonym"]
            match daySynonym:
                case "heute":
                    forecast_day = today
                case "morgen":
                    forecast_day = tomorrow
                case _:
                    raise ValueError(
                        f"daySynonym {daySynonym} is different than 'heute' and 'morgen'"
                    )

            hour = hourly_data.pop("hour")
            hourly_data["datetime"] = forecast_day.replace(hour=hour)

            forecast.append(hourly_data)

        return forecast

    def daily_forecast(self) -> list[dict[str, Any]]:
        """Return the full 4 day forecast of the given `url`."""

        ## get dates first
        forecast: list[dict[str, Any]] = []

        forecast_date = None
        for i in self.soup.find("table", {"id": "daterow"}).find_all("th"):
            if forecast_date is None:
                date = i.find("span").text
                if "," in list(date):
                    date = date.split(", ")[1]
                date += str(datetime.now().year)
                forecast_date = datetime.strptime(date, "%d.%m.%Y")
                forecast_date = datetime.combine(forecast_date, MIDNIGHT, self.timezone)
            else:
                forecast_date = forecast_date + timedelta(days=1)
            forecast.append({"datetime": forecast_date})

        weather_table = self.soup.find("table", {"id": "weather"})
        # max temp
        tags = list(
            weather_table.find("tr", {"class": "Maximum Temperature"}).find_all("div")
        )
        for i, tag in enumerate(tags):
            tag_span = tag.find_all("span")[1]
            forecast[i]["maxTemperature"] = int(str(tag_span.text).rstrip("°"))

        # min temp
        tags = list(
            weather_table.find("tr", {"class": "Minimum Temperature"}).find_all("div")
        )
        for i, tag in enumerate(tags):
            tag_span = tag.find_all("span")[1]
            forecast[i]["minTemperature"] = int(str(tag_span.text).rstrip("°"))

        # sun hours
        tags = list(weather_table.find("tr", {"id": "sun_teaser"}).find_all("span"))
        for i, tag in enumerate(tags):
            forecast[i]["sunHours"] = int(str(tag.text).lstrip().rstrip(" Std.\n"))

        # precipitation probability
        tags = list(
            weather_table.find("tr", {"id": "precipitation_teaser"}).find_all("span")
        )
        for i, tag in enumerate(tags):
            forecast[i]["precipitationProbability"] = int(
                str(tag.text).lstrip().rstrip(" %\n")
            )

        return forecast
