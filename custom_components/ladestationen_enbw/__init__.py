"""EnBW charging station integration."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import EnbwApi, EnbwApiError
from .const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_LATITUDE,
    CONF_STATION_LONGITUDE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    PLATFORMS,
    SEARCH_RADIUS_KM,
)
from .shared import async_load_settings, async_remove_settings, async_save_settings

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a station entry."""
    settings = await async_load_settings(hass)
    if not settings.get(CONF_API_KEY):
        # Migrate existing per-entry settings to shared integration settings.
        settings = {
            CONF_API_KEY: entry.options.get(CONF_API_KEY)
            or entry.data.get(CONF_API_KEY),
            CONF_SCAN_INTERVAL: entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
        }
        await async_save_settings(hass, settings)

    api = EnbwApi(async_get_clientsession(hass), settings[CONF_API_KEY])
    interval = max(
        MIN_SCAN_INTERVAL,
        min(MAX_SCAN_INTERVAL, int(settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))),
    )
    if settings.get(CONF_SCAN_INTERVAL) != interval:
        settings = {**settings, CONF_SCAN_INTERVAL: interval}
        await async_save_settings(hass, settings)
    coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name=f"EnBW {entry.data[CONF_STATION_ID]}",
        update_method=lambda: api.station(entry.data[CONF_STATION_ID]),
        update_interval=timedelta(seconds=interval),
    )
    await coordinator.async_config_entry_first_refresh()
    if (
        entry.data.get(CONF_STATION_LATITUDE) is None
        or entry.data.get(CONF_STATION_LONGITUDE) is None
    ):
        coordinates = _coordinates_from_payload(coordinator.data)
        if coordinates is None:
            coordinates = await _async_find_station_coordinates(api, entry)
        if coordinates is None:
            try:
                coordinates = (
                    float(entry.data[CONF_LATITUDE]),
                    float(entry.data[CONF_LONGITUDE]),
                )
            except (KeyError, TypeError, ValueError):
                coordinates = None
        if coordinates is not None:
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_STATION_LATITUDE: coordinates[0],
                    CONF_STATION_LONGITUDE: coordinates[1],
                },
            )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _coordinates_from_payload(payload: dict) -> tuple[float, float] | None:
    """Extract coordinates from an EnBW station response."""
    if not isinstance(payload, dict):
        return None
    for latitude_key, longitude_key in (("lat", "lon"), ("latitude", "longitude")):
        try:
            return float(payload[latitude_key]), float(payload[longitude_key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


async def _async_find_station_coordinates(api: EnbwApi, entry: ConfigEntry):
    """Look up exact coordinates for an existing station entry."""
    try:
        stations = await api.nearby(
            float(entry.data[CONF_LATITUDE]),
            float(entry.data[CONF_LONGITUDE]),
            SEARCH_RADIUS_KM,
        )
    except (EnbwApiError, KeyError, TypeError, ValueError):
        _LOGGER.debug("Could not look up map coordinates for %s", entry.title)
        return None

    station_id = str(entry.data[CONF_STATION_ID])
    station = next(
        (item for item in stations if str(item.get("stationId")) == station_id),
        None,
    )
    return _coordinates_from_payload(station) if station else None


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove shared settings after the final station entry is deleted."""
    if not hass.config_entries.async_entries(DOMAIN):
        await async_remove_settings(hass)
