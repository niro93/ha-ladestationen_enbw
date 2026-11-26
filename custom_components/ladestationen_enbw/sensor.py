"""Sensors for EnBW charging stations."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATION_ID,
    CONF_STATION_LATITUDE,
    CONF_STATION_LONGITUDE,
    CONF_STATION_NAME,
    DOMAIN,
)
from .helpers import CONNECTOR_TYPES, charge_points_for_type

PLUG_TYPE_NAMES = {
    "CCS": "CCS",
    "TYPE2": "Typ 2",
    "CHADEMO": "CHAdeMO",
}
PLUG_TYPE_ICONS = {
    "CCS": "mdi:ev-plug-ccs2",
    "TYPE2": "mdi:ev-plug-type2",
    "CHADEMO": "mdi:ev-plug-chademo",
}
COUNT_TYPES = ("total", "available")
COUNT_NAMES = {
    "total": "Ladepunkte gesamt",
    "available": "Ladepunkte frei",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up connector-type counters and per-charge-point status sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    station_id = str(entry.data[CONF_STATION_ID])
    latitude = entry.data.get(
        CONF_STATION_LATITUDE, entry.data.get(CONF_LATITUDE)
    )
    longitude = entry.data.get(
        CONF_STATION_LONGITUDE, entry.data.get(CONF_LONGITUDE)
    )
    if latitude is not None and longitude is not None:
        entities.append(
            EnbwStationLocationSensor(entry, latitude, longitude)
        )
    present_types = set()
    for plug_type in CONNECTOR_TYPES:
        points = charge_points_for_type(coordinator.data, plug_type)
        if not points:
            continue
        present_types.add(plug_type)
        entities.extend(
            EnbwCountSensor(coordinator, entry, plug_type, count_type)
            for count_type in COUNT_TYPES
        )
        entities.extend(
            EnbwChargePointSensor(coordinator, entry, point, index, plug_type)
            for index, point in enumerate(points, start=1)
        )

    # Remove entities from an earlier setup when a connector type is no longer
    # present at this station (for example, old zero-valued Type 2 counters).
    registry = er.async_get(hass)
    absent_prefixes = tuple(
        f"{station_id}_{plug_type.lower()}_"
        for plug_type in CONNECTOR_TYPES
        if plug_type not in present_types
    )
    obsolete_unique_ids = {
        f"{station_id}_{plug_type.lower()}_occupied"
        for plug_type in present_types
    }
    if absent_prefixes or obsolete_unique_ids:
        for registered_entity in list(registry.entities.values()):
            if (
                registered_entity.config_entry_id == entry.entry_id
                and registered_entity.domain == "sensor"
                and (
                    registered_entity.unique_id.startswith(absent_prefixes)
                    or registered_entity.unique_id in obsolete_unique_ids
                )
            ):
                registry.async_remove(registered_entity.entity_id)
    async_add_entities(entities)


class EnbwStationLocationSensor(SensorEntity):
    """Expose station coordinates for Home Assistant maps."""

    _attr_has_entity_name = True
    _attr_translation_key = "station_location"
    _attr_icon = "mdi:map-marker"

    def __init__(self, entry, latitude, longitude) -> None:
        self._latitude = float(latitude)
        self._longitude = float(longitude)
        self._attr_unique_id = f"{entry.data[CONF_STATION_ID]}_location"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_STATION_ID])},
            "name": entry.data[CONF_STATION_NAME],
            "manufacturer": "EnBW",
        }

    @property
    def native_value(self) -> str:
        """Return a simple location state without a count summary."""
        return "Standort"

    @property
    def extra_state_attributes(self) -> dict:
        """Provide only the coordinates needed by the map card."""
        return {"latitude": self._latitude, "longitude": self._longitude}


class EnbwCountSensor(CoordinatorEntity, SensorEntity):
    """Count charge points by connector type and status."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, plug_type: str, count_type: str) -> None:
        super().__init__(coordinator)
        self._plug_type = plug_type
        self._count_type = count_type
        self._attr_icon = PLUG_TYPE_ICONS[plug_type]
        self._attr_name = f"{PLUG_TYPE_NAMES[plug_type]} {COUNT_NAMES[count_type]}"
        self._attr_unique_id = (
            f"{entry.data[CONF_STATION_ID]}_{plug_type.lower()}_{count_type}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_STATION_ID])},
            "name": entry.data[CONF_STATION_NAME],
            "manufacturer": "EnBW",
        }

    @property
    def native_value(self) -> int:
        """Return the current count for this type and status."""
        points = charge_points_for_type(self.coordinator.data, self._plug_type)
        if self._count_type == "total":
            return len(points)
        status = "AVAILABLE" if self._count_type == "available" else "OCCUPIED"
        return sum(point.get("status") == status for point in points)

class EnbwChargePointSensor(CoordinatorEntity, SensorEntity):
    """Status sensor for one charge point with supported connector types."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "charge_point_status"
    _attr_options = ["occupied", "available", "unknown", "out_of_service", "blocked"]

    def __init__(self, coordinator, entry, point, index: int, plug_type: str) -> None:
        super().__init__(coordinator)
        self._index = index
        self._evse_id = point.get("evseId")
        self._plug_type = plug_type
        self._attr_unique_id = (
            f"{entry.data[CONF_STATION_ID]}_{plug_type.lower()}_{self._evse_id or index}"
        )
        self._attr_icon = PLUG_TYPE_ICONS[plug_type]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_STATION_ID])},
            "name": entry.data[CONF_STATION_NAME],
            "manufacturer": "EnBW",
        }

    @property
    def translation_placeholders(self) -> dict[str, str]:
        """Return localized connector labels for the entity name."""
        return {
            "index": str(self._index),
            "plug_type": PLUG_TYPE_NAMES[self._plug_type],
        }

    def _point(self):
        points = charge_points_for_type(self.coordinator.data, self._plug_type)
        if self._evse_id:
            return next((item for item in points if item.get("evseId") == self._evse_id), None)
        return points[self._index - 1] if len(points) >= self._index else None

    @property
    def native_value(self) -> str:
        """Return the translated status key for the enum sensor."""
        point = self._point()
        status = point.get("status", "UNKNOWN") if point else "UNKNOWN"
        return {
            "OCCUPIED": "occupied",
            "AVAILABLE": "available",
            "UNKNOWN": "unknown",
            "OUT_OF_SERVICE": "out_of_service",
            "BLOCKED": "blocked",
        }.get(status, "unknown")

