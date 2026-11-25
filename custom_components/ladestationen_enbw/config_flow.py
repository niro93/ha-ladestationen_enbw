"""Config flow for EnBW charging stations."""

from __future__ import annotations

import math

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    EnbwApi,
    EnbwApiError,
    EnbwAuthError,
    EnbwGeocodingError,
)
from .const import (
    CONF_API_KEY,
    CONF_ADDRESS,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_LATITUDE,
    CONF_STATION_LONGITUDE,
    CONF_STATION_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SEARCH_RADIUS_KM,
)
from .shared import async_load_settings, async_save_settings


class EnbwConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one station per entry."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Search for nearby stations."""
        errors = {}
        settings = await async_load_settings(self.hass)
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        legacy_entry = next(
            (
                entry
                for entry in existing_entries
                if entry.options.get(CONF_API_KEY) or entry.data.get(CONF_API_KEY)
            ),
            None,
        )
        shared_api_key = settings.get(CONF_API_KEY) or (
            (legacy_entry.options.get(CONF_API_KEY) or legacy_entry.data.get(CONF_API_KEY))
            if legacy_entry
            else None
        )
        shared_interval = settings.get(CONF_SCAN_INTERVAL) or (
            legacy_entry.options.get(
                CONF_SCAN_INTERVAL,
                legacy_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
            if legacy_entry
            else DEFAULT_SCAN_INTERVAL
        )
        if user_input:
            api_key = (user_input.get(CONF_API_KEY) or shared_api_key or "").strip()
            if not api_key:
                errors["base"] = "invalid_auth"
            else:
                api = EnbwApi(async_get_clientsession(self.hass), api_key)
                try:
                    latitude, longitude = await api.geocode_address(user_input[CONF_ADDRESS])
                    self._latitude = latitude
                    self._longitude = longitude
                    stations = await api.nearby(
                        latitude, longitude, SEARCH_RADIUS_KM
                    )
                    stations = [item for item in stations if item.get("stationId")]
                    stations_with_distance = []
                    for station in stations:
                        try:
                            distance = _distance_km(
                                latitude,
                                longitude,
                                float(station["lat"]),
                                float(station["lon"]),
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
                        if distance <= SEARCH_RADIUS_KM:
                            stations_with_distance.append((distance, station))
                    stations_with_distance.sort(key=lambda item: item[0])
                    self._stations = [station for _, station in stations_with_distance]
                    self._options = {
                        **user_input,
                        CONF_API_KEY: api_key,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, shared_interval
                        ),
                    }
                    if not self._stations:
                        errors["base"] = "no_stations"
                    else:
                        return await self.async_step_station()
                except EnbwGeocodingError:
                    errors["base"] = "cannot_geocode"
                except EnbwAuthError:
                    errors["base"] = "invalid_auth"
                except EnbwApiError:
                    errors["base"] = "cannot_connect"

        schema_fields = {
            vol.Required(CONF_ADDRESS): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
        }
        if not shared_api_key:
            schema_fields[vol.Required(CONF_API_KEY)] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
            schema_fields[
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=30,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            )
        schema = vol.Schema(schema_fields)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_station(self, user_input=None):
        """Select one station from nearby results."""
        stations = self._stations

        def station_label(item):
            address = item.get("shortAddress") or item.get("address") or item.get("name") or "EnBW-Ladestation"
            operator = item.get("operator")
            return f"{operator} · {address}" if operator else address

        options = {
            str(item["stationId"]): station_label(item)
            for item in stations
        }
        if user_input:
            station_id = user_input[CONF_STATION_ID]
            station = next(item for item in stations if str(item["stationId"]) == station_id)
            name = station_label(station)
            await self.async_set_unique_id(station_id)
            self._abort_if_unique_id_configured()
            await async_save_settings(
                self.hass,
                {
                    CONF_API_KEY: self._options[CONF_API_KEY],
                    CONF_SCAN_INTERVAL: self._options[CONF_SCAN_INTERVAL],
                },
            )
            return self.async_create_entry(
                title=name,
                data={
                    CONF_STATION_ID: station_id,
                    CONF_STATION_NAME: name,
                    CONF_ADDRESS: self._options[CONF_ADDRESS],
                    CONF_LATITUDE: self._latitude,
                    CONF_LONGITUDE: self._longitude,
                    CONF_STATION_LATITUDE: float(station["lat"]),
                    CONF_STATION_LONGITUDE: float(station["lon"]),
                },
            )
        if not options:
            return self.async_abort(reason="no_stations")
        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": station_id, "label": label}
                                for station_id, label in options.items()
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return EnbwOptionsFlow(config_entry)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance between coordinates using the haversine formula."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))

class EnbwOptionsFlow(config_entries.OptionsFlow):
    """Manage integration-wide API key and polling interval."""

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Update shared settings used by every station entry."""
        errors = {}
        settings = await async_load_settings(self.hass)
        current_api_key = settings.get(CONF_API_KEY) or (
            self._config_entry.options.get(CONF_API_KEY)
            or self._config_entry.data.get(CONF_API_KEY)
        )
        current_interval = settings.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
        )
        current_interval = max(
            MIN_SCAN_INTERVAL,
            min(MAX_SCAN_INTERVAL, int(current_interval)),
        )
        if user_input is not None:
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            if not api_key:
                api_key = current_api_key
            if not api_key:
                errors["base"] = "invalid_auth"
            elif user_input.get(CONF_API_KEY):
                api = EnbwApi(
                    async_get_clientsession(self.hass), api_key
                )
                try:
                    await api.station(str(self._config_entry.data[CONF_STATION_ID]))
                except EnbwAuthError:
                    errors["base"] = "invalid_auth"
                except EnbwApiError:
                    errors["base"] = "cannot_connect"

            if not errors:
                updated_options = {
                    CONF_API_KEY: api_key,
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                }
                await async_save_settings(
                    self.hass, updated_options
                )
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.entry_id != self._config_entry.entry_id:
                        self.hass.config_entries.async_update_entry(
                            entry,
                            options={**entry.options, **updated_options},
                        )
                return self.async_create_entry(title="", data=updated_options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_KEY, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=30,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    )
                }
            ),
            errors=errors,
        )
