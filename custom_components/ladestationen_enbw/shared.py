"""Persistent integration-wide settings shared by all station entries."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_settings"
DATA_SETTINGS = f"{DOMAIN}_shared_settings"
DATA_STORE = f"{DOMAIN}_settings_store"


def _get_store(hass: HomeAssistant) -> Store:
    """Return the persistent settings store."""
    store = hass.data.get(DATA_STORE)
    if store is None:
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        hass.data[DATA_STORE] = store
    return store


async def async_load_settings(hass: HomeAssistant) -> dict:
    """Load shared settings, using the in-memory copy after the first read."""
    if DATA_SETTINGS not in hass.data:
        hass.data[DATA_SETTINGS] = await _get_store(hass).async_load() or {}
    return hass.data[DATA_SETTINGS]


async def async_save_settings(hass: HomeAssistant, settings: dict) -> None:
    """Persist shared settings and update the in-memory copy."""
    await _get_store(hass).async_save(settings)
    hass.data[DATA_SETTINGS] = settings


async def async_remove_settings(hass: HomeAssistant) -> None:
    """Remove persisted and cached integration-wide settings."""
    await _get_store(hass).async_remove()
    hass.data.pop(DATA_SETTINGS, None)
    hass.data.pop(DATA_STORE, None)
