"""NOAA Fisheries North Atlantic Right Whale Seasonal Management Areas (SMAs).

Sprint D6.97 #49 (2026-05-25) — encode the 10 published SMAs from
50 CFR 224.105 as GeoJSON Features so the /whale-zones map can render
them without depending on an external service.

Authority: 50 CFR 224.105 (Speed restrictions to reduce the threat of
ship collisions with North Atlantic right whales). Boundaries are
published in the rule and supplementary Federal Register notices.
Speed restriction: vessels ≥35 ft (10.7 m) cannot exceed 10 knots
within active SMAs.

For the production version (post-Maersk demo) we'll fetch live polygon
data from NOAA Fisheries' GIS layer at greateratlantic.fisheries.noaa.gov
plus the WhaleAlert API for active DMAs (Dynamic Management Areas).
The current static encoding is for the Maersk demo timeline only.

GeoJSON convention: longitude FIRST in coordinate pairs (per RFC 7946),
which is opposite of how the regulation prints them. Northeast SMAs
are rectangular bounding boxes; Mid-Atlantic and Southeast are 20-nm
radius half-circles centered on each port (approximated as octagons
in this demo encoding).
"""
from __future__ import annotations

from typing import Any


# Northeast SMAs — rectangular, defined by lat/lon corners in 50 CFR 224.105.
_NORTHEAST_SMAS: list[dict[str, Any]] = [
    {
        "id": "cape_cod_bay",
        "name": "Cape Cod Bay SMA",
        "season_start": "01-01",
        "season_end": "05-15",
        "speed_limit_knots": 10,
        "vessel_threshold_ft": 35,
        "polygon": [
            # Rectangle: 41°47'N to 42°08'N, 70°30'W to Cape Cod coast (~70°10'W)
            [-70.50, 41.78],
            [-70.10, 41.78],
            [-70.10, 42.13],
            [-70.50, 42.13],
            [-70.50, 41.78],
        ],
        "description": (
            "Cape Cod Bay seasonal management area. Mandatory 10-knot "
            "speed limit for vessels ≥35 ft during Jan 1 – May 15."
        ),
    },
    {
        "id": "off_race_point",
        "name": "Off Race Point SMA",
        "season_start": "03-01",
        "season_end": "04-30",
        "speed_limit_knots": 10,
        "vessel_threshold_ft": 35,
        "polygon": [
            # Northeast of Cape Cod: 42°08'N to 42°30'N, 70°30'W to 69°40'W
            [-70.50, 42.13],
            [-69.67, 42.13],
            [-69.67, 42.50],
            [-70.50, 42.50],
            [-70.50, 42.13],
        ],
        "description": (
            "Off Race Point SMA. Northeast of Cape Cod. Active "
            "Mar 1 – Apr 30 during right whale northward migration."
        ),
    },
    {
        "id": "great_south_channel",
        "name": "Great South Channel SMA",
        "season_start": "04-01",
        "season_end": "07-31",
        "speed_limit_knots": 10,
        "vessel_threshold_ft": 35,
        "polygon": [
            # East of Cape Cod: 41°00'N to 42°30'N, 69°45'W to 69°05'W
            [-69.75, 41.00],
            [-69.08, 41.00],
            [-69.08, 42.50],
            [-69.75, 42.50],
            [-69.75, 41.00],
        ],
        "description": (
            "Great South Channel SMA. East of Cape Cod, prime spring/"
            "summer right whale feeding ground. Active Apr 1 – Jul 31."
        ),
    },
]


# Mid-Atlantic SMAs — 20-nm half-circles centered on each port mouth,
# approximated as half-circle polygons. The regulation specifies them
# as "all waters within a 20-nautical-mile radius of the COLREGS demarcation
# lines" at each port. For the demo, we encode them as octagonal half-circles.
#
# Active for ALL Mid-Atlantic SMAs: Nov 1 to Apr 30.
def _half_circle_polygon(
    center_lon: float, center_lat: float, radius_nm: float = 20,
) -> list[list[float]]:
    """Build an offshore (eastward-facing) half-circle polygon centered at
    a port. Approximated as a 9-vertex octagon arc from due-north to
    due-south through east, plus closing edge along the longitude line.

    Coordinates returned in GeoJSON [lon, lat] order.
    """
    import math
    nm_per_degree_lat = 60.0
    nm_per_degree_lon = 60.0 * math.cos(math.radians(center_lat))
    deg_lat = radius_nm / nm_per_degree_lat
    deg_lon = radius_nm / nm_per_degree_lon
    # Half-circle from 90° (due north) sweeping east to -90° (due south).
    # 9 points = 22.5° increments across 180°.
    points: list[list[float]] = []
    for i in range(9):
        angle_deg = 90 - i * 22.5
        angle_rad = math.radians(angle_deg)
        lon = center_lon + deg_lon * math.cos(angle_rad)
        lat = center_lat + deg_lat * math.sin(angle_rad)
        points.append([round(lon, 4), round(lat, 4)])
    # Close back to start
    points.append(points[0])
    return points


_MID_ATLANTIC_PORTS: list[dict[str, Any]] = [
    {
        "id": "ny_nj",
        "name": "New York / New Jersey SMA",
        "center": [-74.05, 40.50],
        "description": (
            "20-nm radius around the New York / New Jersey port complex "
            "(Sandy Hook & Ambrose entrance). 10-knot speed limit "
            "Nov 1 – Apr 30 for vessels ≥35 ft."
        ),
    },
    {
        "id": "delaware_bay",
        "name": "Delaware Bay SMA",
        "center": [-75.10, 38.78],
        "description": (
            "20-nm radius around the Delaware Bay entrance (Cape "
            "Henlopen / Cape May). Active Nov 1 – Apr 30."
        ),
    },
    {
        "id": "chesapeake_bay",
        "name": "Chesapeake Bay SMA",
        "center": [-76.00, 37.00],
        "description": (
            "20-nm radius around the Chesapeake Bay entrance (Cape "
            "Henry / Cape Charles). Active Nov 1 – Apr 30."
        ),
    },
    {
        "id": "morehead_city",
        "name": "Morehead City / Beaufort SMA",
        "center": [-76.66, 34.70],
        "description": (
            "20-nm radius around Morehead City and Beaufort Inlet, NC. "
            "Active Nov 1 – Apr 30."
        ),
    },
    {
        "id": "wilmington",
        "name": "Wilmington SMA",
        "center": [-77.93, 34.00],
        "description": (
            "20-nm radius around Wilmington / Cape Fear, NC. Active "
            "Nov 1 – Apr 30."
        ),
    },
    {
        "id": "charleston",
        "name": "Charleston SMA",
        "center": [-79.95, 32.78],
        "description": (
            "20-nm radius around Charleston Harbor, SC. Active "
            "Nov 1 – Apr 30."
        ),
    },
    {
        "id": "savannah",
        "name": "Savannah / Brunswick SMA",
        "center": [-80.95, 31.95],
        "description": (
            "20-nm radius around the Savannah River entrance and "
            "Brunswick port area, GA. Active Nov 1 – Apr 30."
        ),
    },
]


# Southeast U.S. SMA — calving ground habitat, larger area.
_SOUTHEAST_SMA: dict[str, Any] = {
    "id": "southeast",
    "name": "Southeast U.S. SMA (Calving Ground)",
    "season_start": "11-15",
    "season_end": "04-15",
    "speed_limit_knots": 10,
    "vessel_threshold_ft": 35,
    "polygon": [
        # From Brunswick, GA south to St. Augustine, FL, out to 80°20'W
        [-81.50, 30.50],
        [-80.33, 30.50],
        [-80.33, 31.50],
        [-81.50, 31.50],
        [-81.50, 30.50],
    ],
    "description": (
        "Southeast U.S. seasonal management area. North Atlantic right "
        "whale calving ground off Georgia and northeast Florida. "
        "10-knot speed limit Nov 15 – Apr 15 for vessels ≥35 ft."
    ),
}


def get_sma_features() -> list[dict[str, Any]]:
    """Return all SMAs as a list of GeoJSON Feature dicts."""
    features: list[dict[str, Any]] = []

    for sma in _NORTHEAST_SMAS:
        features.append(_feature_from_polygon_entry(sma))

    for port in _MID_ATLANTIC_PORTS:
        features.append(_feature_from_port_entry(port))

    features.append(_feature_from_polygon_entry(_SOUTHEAST_SMA))

    return features


def _feature_from_polygon_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": entry["id"],
        "geometry": {
            "type": "Polygon",
            "coordinates": [entry["polygon"]],
        },
        "properties": {
            "name": entry["name"],
            "season_start": entry["season_start"],
            "season_end": entry["season_end"],
            "speed_limit_knots": entry["speed_limit_knots"],
            "vessel_threshold_ft": entry["vessel_threshold_ft"],
            "description": entry["description"],
            "authority": "50 CFR 224.105",
            "zone_type": "SMA",
            "mandatory": True,
        },
    }


def _feature_from_port_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": entry["id"],
        "geometry": {
            "type": "Polygon",
            "coordinates": [_half_circle_polygon(entry["center"][0], entry["center"][1])],
        },
        "properties": {
            "name": entry["name"],
            "season_start": "11-01",
            "season_end": "04-30",
            "speed_limit_knots": 10,
            "vessel_threshold_ft": 35,
            "description": entry["description"],
            "authority": "50 CFR 224.105",
            "zone_type": "SMA",
            "mandatory": True,
        },
    }
