"""Fixed passive-sensor layout — for the SeaSentry-style positioning task.

These are NOT physical hardware. Since the project has no real radar-pulse
receivers, we place a handful of fixed points on the map and treat them as
"shore sensors" that would, in a real deployment, record the exact instant a
ship's radar beam sweeps past them (see docs/radar_research.md).

Default layout: start from the four corners of the region's bounding
rectangle (good geometric spread -- low GDOP, per SeaSentry Sec. IV-B), then
for each corner:
  1. Snap to the nearest point on the actual detailed coastline polygon
     (region.bbox -- hundreds of points tracing the real study-area outline,
     not just the crude rectangle). This is what pulls a corner that's far
     out in empty space in toward the real shoreline.
  2. Nudge that point a small safety margin further out, away from the
     water, so it lands clearly on land rather than sitting exactly on the
     boundary line.

This keeps the four sensors spread toward four different sides of the area
(so GDOP stays low, per SeaSentry Sec. IV-B) while hugging the real
coastline shape instead of a crude rectangle.

Usage:
    from core.regions import load_region
    from core.sensors import default_sensor_layout

    region  = load_region("rheinhafen")
    sensors = default_sensor_layout(region)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from shapely.geometry import Point, Polygon as ShapelyPolygon
from shapely.ops import nearest_points

from core.regions import Region

# Same conversion used in core/regions.py for metre <-> degree buffering.
_DEG_PER_METER = 1.0 / 111_000.0


@dataclass
class Sensor:
    """A fixed passive sensor position."""
    sensor_id: str
    lat: float
    lon: float


def _water_polygon(region: Region) -> ShapelyPolygon:
    """The navigable-water polygon as a shapely Polygon (shapely wants x=lon, y=lat)."""
    return ShapelyPolygon([(lon, lat) for (lat, lon) in region.bbox])


def _nearest_boundary_point(point: Tuple[float, float], water_poly: ShapelyPolygon) -> Tuple[float, float]:
    """Closest point on the water polygon's actual boundary (the real,
    detailed coastline shape) to `point`.
    """
    lat, lon = point
    nearest = nearest_points(water_poly.exterior, Point(lon, lat))[0]
    return (nearest.y, nearest.x)   # shapely is (x=lon, y=lat)


def _push_onto_land(
    centroid: Tuple[float, float],
    point: Tuple[float, float],
    water_poly: ShapelyPolygon,
    margin_m: float = 100.0,
) -> Tuple[float, float]:
    """If `point` is inside the water polygon (+ margin), push it directly
    away from `centroid` until it clears the water. Points already on land
    are returned unchanged.
    """
    buffered = water_poly.buffer(margin_m * _DEG_PER_METER)
    lat, lon = point
    c_lat, c_lon = centroid
    d_lat, d_lon = lat - c_lat, lon - c_lon
    if d_lat == 0.0 and d_lon == 0.0:
        d_lat = 1e-6  # degenerate case: point sits exactly on the centroid

    scale = 1.0
    while buffered.contains(Point(lon, lat)) and scale < 6.0:
        scale += 0.1
        lat = c_lat + d_lat * scale
        lon = c_lon + d_lon * scale

    return lat, lon


# Manual overrides: (region_key, sensor_id) -> (lat, lon). Use this to pin a
# specific sensor to an exact spot instead of the auto-computed one -- e.g.
# because the automatic snap-to-coastline landed somewhere worse than a
# simpler placement already was.
_OVERRIDES: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("cuxhaven", "S2"): (53.80306331513907, 9.387116301293418),  # original SE bbox corner
    # ("rheinhafen", "S1"): (48.97935233, 8.26078500),
    # ("rheinhafen", "S4"): (48.97821117, 8.25341433),
    # ("rheinhafen", "S3"): (48.98098500, 8.25861500),
    # ("rheinhafen", "S2"): (48.97646668, 8.25545553),    
}


def default_sensor_layout(region: Region, n: int = 4, land_margin_m: float = 100.0) -> List[Sensor]:
    """Place sensors near the region's bounding-rectangle corners, snapped
    to the real coastline and nudged onto land.
    """
    lats = [p[0] for p in region.bbox]
    lons = [p[1] for p in region.bbox]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    raw_corners = [
        ("S1", lat_min, lon_min),   # south-west
        ("S2", lat_min, lon_max),   # south-east
        ("S3", lat_max, lon_max),   # north-east
        ("S4", lat_max, lon_min),   # north-west
    ]

    water_poly = _water_polygon(region)

    sensors = []
    for sid, lat, lon in raw_corners[:n]:
        override = _OVERRIDES.get((region.key, sid))
        if override:
            sensors.append(Sensor(sensor_id=sid, lat=override[0], lon=override[1]))
            continue

        near_lat, near_lon = _nearest_boundary_point((lat, lon), water_poly)
        lat2, lon2 = _push_onto_land(region.center, (near_lat, near_lon), water_poly, land_margin_m)
        sensors.append(Sensor(sensor_id=sid, lat=lat2, lon=lon2))

    return sensors


# ---------------------------------------------------------------------------
# Quick self-test — run with:  python core/sensors.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from core.regions import load_region

    for key in ("rheinhafen", "cuxhaven"):
        region = load_region(key)
        water_poly = _water_polygon(region)
        sensors = default_sensor_layout(region)
        print(f"\n{key}:")
        for s in sensors:
            in_water = water_poly.contains(Point(s.lon, s.lat))
            flag = "IN WATER!" if in_water else "on land (ok)"
            print(f"  {s.sensor_id}: lat={s.lat:.5f}, lon={s.lon:.5f}  [{flag}]")
