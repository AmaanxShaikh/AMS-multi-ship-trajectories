"""Region metadata loader.

Wraps the line-of-sight (fairway centerline) and bounding-box JSON files that
came from the previous student team's project. Provides them in a single,
consistent `(lat, lon)` order so the front-end doesn't have to think about
GeoJSON's `(lon, lat)` convention.

File formats (as inherited):
  * `*_los.json`  : top-level JSON array of [lat, lon] pairs.
  * `*_bbox.json` : GeoJSON-like {"coordinates": [[lon, lat], ...]} polygon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple
import json

from shapely.geometry import LineString


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# Rough conversion factor: at mid-latitudes 1 degree ~= 111 km.
# Good enough for building a river-corridor buffer for containment checks.
_DEG_PER_METER = 1.0 / 111_000.0


@dataclass
class Region:
    key: str                                     # "rheinhafen" or "cuxhaven"
    display_name: str
    los: List[Tuple[float, float]]               # (lat, lon)
    bbox: List[Tuple[float, float]]              # (lat, lon) working-area polygon
    center: Tuple[float, float]                  # (lat, lon)
    default_zoom: int
    corridor_width_m: float = 150.0              # half-width of the river corridor
    river_corridor: List[Tuple[float, float]] = field(default_factory=list)


def _build_river_corridor(los: List[Tuple[float, float]],
                          width_m: float) -> List[Tuple[float, float]]:
    """Buffer the LOS centerline into a river-corridor polygon.

    LOS is [(lat, lon), ...]; shapely wants (x=lon, y=lat). Buffer by an
    approximate angular distance and return the outer ring as (lat, lon).
    """
    if len(los) < 2:
        return []
    line = LineString([(lon, lat) for (lat, lon) in los])
    buf = line.buffer(width_m * _DEG_PER_METER, cap_style=2, join_style=2)
    if buf.is_empty:
        return []
    ring = buf.exterior if hasattr(buf, "exterior") else buf.geoms[0].exterior
    return [(y, x) for (x, y) in ring.coords]


def _load_los(path: Path) -> List[Tuple[float, float]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # File is already [[lat, lon], ...]. Cast to tuples for immutability.
    return [(float(p[0]), float(p[1])) for p in raw]


def _load_bbox(path: Path) -> List[Tuple[float, float]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    coords = raw["coordinates"]
    # GeoJSON convention is [lon, lat]; flip to (lat, lon) for consistency.
    return [(float(p[1]), float(p[0])) for p in coords]


def _centroid(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    if not points:
        return (0.0, 0.0)
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def load_region(key: str) -> Region:
    """Load a region by its short key."""
    cfg = REGION_CONFIG[key]
    los = _load_los(DATA_DIR / cfg["los_file"])
    bbox = _load_bbox(DATA_DIR / cfg["bbox_file"])
    center = _centroid(bbox) if bbox else _centroid(los)
    corridor_width_m = float(cfg.get("corridor_width_m", 150.0))
    river_corridor = _build_river_corridor(los, corridor_width_m)
    return Region(
        key=key,
        display_name=cfg["display_name"],
        los=los,
        bbox=bbox,
        center=center,
        default_zoom=cfg["default_zoom"],
        corridor_width_m=corridor_width_m,
        river_corridor=river_corridor,
    )


# Static registry. Add new regions here.
# corridor_width_m = half-width of the navigable river corridor around the LOS.
# Rheinhafen is a narrow inland port (~150 m); Cuxhaven is a wide estuary (~500 m).
REGION_CONFIG: Dict[str, dict] = {
    "rheinhafen": {
        "display_name": "Rheinhafen (Karlsruhe)",
        "los_file": "rheinhafen_los.json",
        "bbox_file": "rheinhafen_bbox.json",
        "default_zoom": 14,
        "corridor_width_m": 150.0,
    },
    "cuxhaven": {
        "display_name": "Cuxhaven (Elbe estuary)",
        "los_file": "cuxhaven_los.json",
        "bbox_file": "cuxhaven_bbox.json",
        "default_zoom": 11,
        "corridor_width_m": 500.0,
    },
}


def available_regions() -> List[Tuple[str, str]]:
    """Return (key, display_name) pairs for the UI dropdown."""
    return [(k, v["display_name"]) for k, v in REGION_CONFIG.items()]
