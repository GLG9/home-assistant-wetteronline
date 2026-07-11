"""Async client and parser for the public WetterOnline website."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Final
from urllib.parse import urlparse

from aiohttp import ClientError, ClientResponseError, ClientSession

BASE_URL: Final = "https://www.wetteronline.de"
SEARCH_URL: Final = "https://search.prod.geo.wo-cloud.com/v1/autosuggest"
HTTP_HEADERS: Final = {
    "Accept": "text/html,application/json",
    "Accept-Encoding": "gzip",
    "User-Agent": "HomeAssistant-WetterOnline/2.0 (+https://github.com/GLG9/home-assistant-wetteronline)",
}


class WetterOnlineError(Exception):
    """Base error."""


class WetterOnlineConnectionError(WetterOnlineError):
    """The service could not be reached."""


class WetterOnlineInvalidLocation(WetterOnlineError):
    """The page is not a WetterOnline location."""


class WetterOnlineParseError(WetterOnlineError):
    """The public page format is not understood."""


@dataclass(slots=True, frozen=True)
class SearchResult:
    """A WetterOnline place search result."""

    key: str
    name: str
    detail: str = ""

    @property
    def label(self) -> str:
        """Return a human-readable label."""
        return f"{self.name} — {self.detail}" if self.detail else self.name


@dataclass(slots=True)
class Location:
    """Resolved WetterOnline location metadata."""

    gid: str
    name: str
    latitude: float
    longitude: float
    altitude: float | None
    timezone: str
    path: str


@dataclass(slots=True)
class WetterOnlineData:
    """Normalized and raw data for one location."""

    location: Location
    current: dict[str, Any]
    hourly: list[dict[str, Any]]
    daily: list[dict[str, Any]]
    pollen: list[dict[str, Any]] = field(default_factory=list)
    warnings: dict[str, Any] | list[Any] = field(default_factory=dict)
    astronomy: list[dict[str, Any]] = field(default_factory=list)
    forecast_texts: list[dict[str, Any]] = field(default_factory=list)
    editorial: dict[str, Any] = field(default_factory=dict)
    water: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now().astimezone())

    def as_dict(self) -> dict[str, Any]:
        """Return diagnostics-safe serializable data."""
        return asdict(self)


class _ScriptParser(HTMLParser):
    """Extract JSON script elements without a third-party DOM parser."""

    def __init__(self) -> None:
        super().__init__()
        self._script_id: str | None = None
        self._buffer: list[str] = []
        self.scripts: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        script_id = dict(attrs).get("id")
        if script_id in {"wo-global-json", "ng-state"}:
            self._script_id = script_id
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._script_id:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script_id:
            self.scripts[self._script_id] = "".join(self._buffer)
            self._script_id = None
            self._buffer = []


def _find_value(state: dict[str, Any], needle: str, default: Any = None) -> Any:
    for key, value in state.items():
        if needle in key:
            return value
    return default


def _parts(parts: list[dict[str, Any]] | None) -> str:
    return "".join(str(item.get("substring", "")) for item in parts or [])


def _clean_rich_text(value: Any) -> Any:
    """Remove WetterOnline's inline presentation tags from public text."""
    if not isinstance(value, str):
        return value
    return re.sub(r"<[^>]+>", "", value).strip()


def normalize_location(value: str) -> str:
    """Normalize a WetterOnline path or URL."""
    value = value.strip()
    if not value:
        raise WetterOnlineInvalidLocation("Empty location")
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        if parsed.netloc not in {"wetteronline.de", "www.wetteronline.de"}:
            raise WetterOnlineInvalidLocation("URL is not hosted by wetteronline.de")
        value = parsed.path
        if parsed.query:
            value += f"?{parsed.query}"
    if value.startswith("wetter/"):
        value = f"/{value}"
    if not value.startswith("/"):
        raise WetterOnlineInvalidLocation("Not a WetterOnline path")
    return value


def parse_weather_page(raw_html: str, path: str) -> WetterOnlineData:
    """Parse embedded structured state from a WetterOnline location page."""
    parser = _ScriptParser()
    parser.feed(raw_html)
    try:
        global_data = json.loads(parser.scripts["wo-global-json"])
        state = json.loads(parser.scripts["ng-state"])
    except (KeyError, json.JSONDecodeError) as err:
        raise WetterOnlineParseError("Structured page data is missing or invalid") from err

    geo = global_data.get("geo") or {}
    shortcast = _find_value(state, "/blending/shortcast/")
    forecast = _find_value(state, "/blending/forecast/")
    if not geo or not isinstance(shortcast, dict) or not isinstance(forecast, dict):
        raise WetterOnlineInvalidLocation("The page does not contain location weather data")

    timezone = global_data.get("timeZone") or global_data.get("timezone") or "Europe/Berlin"
    location = Location(
        gid=str(geo.get("gid", "")),
        name=str(geo.get("locationnameLong") or geo.get("locationname") or geo.get("gid")),
        latitude=float(geo.get("lat", 0)),
        longitude=float(geo.get("lon", 0)),
        altitude=float(geo["alt"]) if geo.get("alt") not in (None, "") else None,
        timezone=str(timezone),
        path=path,
    )
    if not location.gid:
        raise WetterOnlineInvalidLocation("Location id is missing")

    warnings = _find_value(state, "/warnings/", {})
    forecast_texts = list(_find_value(state, "/blending/texts/", []) or [])
    for item in forecast_texts:
        if isinstance(item, dict) and "text" in item:
            item["text"] = _clean_rich_text(item["text"])

    return WetterOnlineData(
        location=location,
        current=dict(shortcast.get("current") or {}),
        hourly=list(shortcast.get("hours") or []),
        daily=list(forecast.get("days") or []),
        pollen=list((_find_value(state, "/pollen/", {}) or {}).get("days") or []),
        warnings=warnings,
        astronomy=list((_find_value(state, "/astro/days/", {}) or {}).get("days") or []),
        forecast_texts=forecast_texts,
        editorial=dict(_find_value(state, "/editorial-pull-notification/", {}) or {}),
        water=dict(_find_value(state, "/app/weather/water", {}) or {}),
    )


class WetterOnline:
    """Fetch public WetterOnline data for one location."""

    def __init__(self, session: ClientSession, location: str) -> None:
        self._session = session
        self.path = normalize_location(location)

    @property
    def complete_url(self) -> str:
        return f"{BASE_URL}{self.path}"

    async def async_get_weather(self) -> WetterOnlineData:
        """Fetch and parse the location page."""
        try:
            async with self._session.get(
                self.complete_url, headers=HTTP_HEADERS, allow_redirects=True
            ) as response:
                response.raise_for_status()
                final_path = response.url.path
                if response.url.query_string:
                    final_path += f"?{response.url.query_string}"
                return parse_weather_page(await response.text(), final_path)
        except WetterOnlineError:
            raise
        except (ClientError, TimeoutError, ClientResponseError) as err:
            raise WetterOnlineConnectionError(str(err)) from err

    @classmethod
    async def async_search(cls, session: ClientSession, query: str) -> list[SearchResult]:
        """Search public WetterOnline place suggestions."""
        try:
            async with session.get(
                SEARCH_URL,
                params={"language": "de", "application": "Web", "region": "DE", "name": query},
                headers=HTTP_HEADERS,
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (ClientError, TimeoutError, ClientResponseError, json.JSONDecodeError) as err:
            raise WetterOnlineConnectionError(str(err)) from err
        return [
            SearchResult(
                key=str(item["geoObjectKey"]),
                name=_parts(item.get("primaryName")),
                detail=", ".join(_parts(part) for part in item.get("secondaryNames", [])),
            )
            for item in payload
            if item.get("geoObjectKey") and item.get("primaryName")
        ]

    @classmethod
    async def async_resolve_search(cls, session: ClientSession, key: str) -> str:
        """Resolve a place key to a canonical weather path."""
        try:
            async with session.get(
                f"{BASE_URL}/search",
                params={
                    "ireq": "true",
                    "pid": "p_search",
                    "geoObjectKey": key,
                    "searchpcid": "pc_city_weather",
                    "searchpid": "p_city_weather",
                },
                headers=HTTP_HEADERS,
            ) as response:
                response.raise_for_status()
                body = await response.text()
        except (ClientError, TimeoutError, ClientResponseError) as err:
            raise WetterOnlineConnectionError(str(err)) from err
        match = re.search(r"URL=(/wetter/[^\"'>]+)|location\.href\s*=\s*'(/wetter/[^']+)'", body)
        if not match:
            raise WetterOnlineInvalidLocation("Search result has no weather page")
        return match.group(1) or match.group(2)
