"""core/physics/coordinate_utils.py

Coordinate conversion helpers extracted from the old physics model.
All functions work in (lat, lon) order consistently.
"""

from __future__ import annotations
import math
from typing import Tuple

EARTH_RADIUS_M = 6_371_000.0


def latlon_to_xy(lat: float, lon: float) -> Tuple[float, float]:
    """Convert (lat, lon) to flat-earth (x, y) in metres.

    Uses equirectangular projection centred on the equator.
    Accurate enough for the small areas (Rheinhafen, Cuxhaven).
    Matches the old implementation exactly.
    """
    x = math.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(lat))
    y = math.radians(lat) * EARTH_RADIUS_M
    return x, y


def bearing(pointA: Tuple[float, float],
            pointB: Tuple[float, float]) -> float:
    """True bearing in degrees (0 = North, clockwise) from A to B.

    Args:
        pointA: (lat, lon)
        pointB: (lat, lon)
    """
    lat1, lon1 = map(math.radians, pointA)
    lat2, lon2 = map(math.radians, pointB)
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def move_geodesic(lat: float, lon: float,
                  bearing_deg: float,
                  distance_m: float) -> Tuple[float, float]:
    """Return new (lat, lon) after moving distance_m on bearing_deg.

    Uses geopy if available (matches old code), otherwise falls back
    to a pure-Python haversine implementation so there is no hard dependency.
    """
    try:
        from geopy.distance import geodesic as _geo
        from geopy import Point as _Pt
        dest = _geo(meters=distance_m).destination(_Pt(lat, lon), bearing_deg)
        return dest.latitude, dest.longitude
    except ImportError:
        # Pure-Python fallback (haversine inverse)
        d = distance_m / EARTH_RADIUS_M
        lat_r = math.radians(lat)
        lon_r = math.radians(lon)
        b_r   = math.radians(bearing_deg)
        new_lat = math.asin(
            math.sin(lat_r) * math.cos(d)
            + math.cos(lat_r) * math.sin(d) * math.cos(b_r)
        )
        new_lon = lon_r + math.atan2(
            math.sin(b_r) * math.sin(d) * math.cos(lat_r),
            math.cos(d) - math.sin(lat_r) * math.sin(new_lat),
        )
        return math.degrees(new_lat), math.degrees(new_lon)


def geodesic_distance(a: Tuple[float, float],
                      b: Tuple[float, float]) -> float:
    """Distance in metres between two (lat, lon) points."""
    try:
        from geopy.distance import geodesic as _geo
        return _geo(a, b).meters
    except ImportError:
        lat1, lon1 = map(math.radians, a)
        lat2, lon2 = map(math.radians, b)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))