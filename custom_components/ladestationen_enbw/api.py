"""Async client for EnBW's public charging-station endpoints."""

from __future__ import annotations

import asyncio
import math
import time

import aiohttp

API_BASE = "https://api.emp.emob-enbw.com/emobility-public-api/api/v1"
GEOCODING_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODE_CACHE: dict[str, tuple[float, float]] = {}
_GEOCODE_LOCK = asyncio.Lock()
_LAST_GEOCODE_REQUEST = 0.0


class EnbwApiError(Exception):
    """Error communicating with EnBW."""


class EnbwAuthError(EnbwApiError):
    """The supplied API key was rejected."""


class EnbwGeocodingError(Exception):
    """The address could not be converted to coordinates."""


class EnbwApi:
    """Small API wrapper."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._headers = {
            "User-Agent": "Home Assistant",
            "Accept": "application/json",
            "Origin": "https://www.enbw.com",
            "Referer": "https://www.enbw.com/",
            "Ocp-Apim-Subscription-Key": api_key,
        }

    async def geocode_address(self, address: str) -> tuple[float, float]:
        """Resolve one user-entered address with OpenStreetMap Nominatim."""
        global _LAST_GEOCODE_REQUEST
        cache_key = " ".join(address.casefold().split())
        if not cache_key:
            raise EnbwGeocodingError("Address is empty")
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]

        async with _GEOCODE_LOCK:
            if cache_key in _GEOCODE_CACHE:
                return _GEOCODE_CACHE[cache_key]
            wait_seconds = 1 - (time.monotonic() - _LAST_GEOCODE_REQUEST)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            _LAST_GEOCODE_REQUEST = time.monotonic()
            try:
                async with self._session.get(
                    GEOCODING_URL,
                    params={"q": address, "format": "jsonv2", "limit": 1},
                    headers={
                        "User-Agent": "Home Assistant",
                        "Accept": "application/json",
                        "Accept-Language": "de",
                    },
                    timeout=15,
                ) as response:
                    response.raise_for_status()
                    results = await response.json()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise EnbwGeocodingError("Could not geocode address") from err

        if not isinstance(results, list) or not results:
            raise EnbwGeocodingError("Address not found")
        try:
            latitude = float(results[0]["lat"])
            longitude = float(results[0]["lon"])
        except (KeyError, TypeError, ValueError) as err:
            raise EnbwGeocodingError("Invalid geocoding response") from err

        result = (latitude, longitude)
        _GEOCODE_CACHE[cache_key] = result
        return result

    async def _get(self, url: str):
        try:
            async with self._session.get(url, headers=self._headers, timeout=20) as response:
                if response.status in (401, 403):
                    raise EnbwAuthError
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EnbwApiError("Could not reach EnBW API") from err

    async def station(self, station_id: str) -> dict:
        data = await self._get(f"{API_BASE}/chargestations/{station_id}")
        if not isinstance(data, dict):
            raise EnbwApiError("Unexpected station response")
        return data

    async def nearby(self, latitude: float, longitude: float, radius_km: float) -> list[dict]:
        # The endpoint accepts a bounding box. Expand longitude for latitude.
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / max(111.0 * abs(math.cos(math.radians(latitude))), 1)
        params = (
            f"?fromLat={latitude-lat_delta}&toLat={latitude+lat_delta}"
            f"&fromLon={longitude-lon_delta}&toLon={longitude+lon_delta}"
            "&grouping=false&groupingDivisor=15"
        )
        data = await self._get(f"{API_BASE}/chargestations{params}")
        return data if isinstance(data, list) else []
