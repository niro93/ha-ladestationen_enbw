"""Helpers for EnBW charging-station data."""

from __future__ import annotations

from typing import Any

CONNECTOR_TYPES = ("CCS", "TYPE2", "CHADEMO")


def connector_type(connector: dict[str, Any]) -> str | None:
    """Map EnBW connector groups to the types supported by this integration."""
    raw_type = connector.get("chargePlugTypeGroup")
    if not isinstance(raw_type, str):
        return None

    plug_type = raw_type.strip().upper().replace("-", "_").replace(" ", "_")
    if plug_type.startswith("CCS") or plug_type in {"COMBO_2", "COMBO_TYPE_2"}:
        return "CCS"
    if plug_type in {"TYPE2", "TYPE_2", "TYPE_2_AC", "TYPE2_AC"}:
        return "TYPE2"
    if plug_type in {"CHADEMO", "CHA_DE_MO"}:
        return "CHADEMO"
    return None


def charge_points_for_type(
    data: dict[str, Any], plug_type: str
) -> list[dict[str, Any]]:
    """Return charge points that expose the requested connector type."""
    result = []
    for point in data.get("chargePoints", []):
        connectors = [
            connector
            for connector in point.get("connectors", [])
            if connector_type(connector) == plug_type
        ]
        if connectors:
            result.append({**point, "connectors": connectors})
    return result


def charge_point_types(point: dict[str, Any]) -> list[str]:
    """Return all supported connector types on one charge point."""
    return list(
        dict.fromkeys(
            plug_type
            for connector in point.get("connectors", [])
            if (plug_type := connector_type(connector)) is not None
        )
    )
