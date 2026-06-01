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

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
import json


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Region:
    key: str                         # "rheinhafen" or "cuxhaven"
    display_name: str
    los: List[Tuple[float, float]]   # (lat, lon)
    bbox: List[Tuple[float, float]]  # (lat, lon) polygon
    center: Tuple[float, float]      # (lat, lon)
    default_zoom: int


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
    return Region(
        key=key,
        display_name=cfg["display_name"],
        los=los,
        bbox=bbox,
        center=center,
        default_zoom=cfg["default_zoom"],
    )


# Static registry. Add new regions here.
REGION_CONFIG: Dict[str, dict] = {
    "rheinhafen": {
        "display_name": "Rheinhafen (Karlsruhe)",
        "los_file": "rheinhafen_los.json",
        "bbox_file": "rheinhafen_bbox.json",
        "default_zoom": 14,
    },
    "cuxhaven": {
        "display_name": "Cuxhaven (Elbe estuary)",
        "los_file": "cuxhaven_los.json",
        "bbox_file": "cuxhaven_bbox.json",
        "default_zoom": 11,
    },
}


def available_regions() -> List[Tuple[str, str]]:
    """Return (key, display_name) pairs for the UI dropdown."""
    return [(k, v["display_name"]) for k, v in REGION_CONFIG.items()]
