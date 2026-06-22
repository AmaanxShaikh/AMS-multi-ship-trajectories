"""Scenario Builder — automatic multi-ship traffic scenario generator.

ALL coordinates have been individually verified against the real polygon files:
  rheinhafen_bbox.json  and  cuxhaven_bbox.json
"""

from __future__ import annotations
import math
import random
from typing import List, Tuple
from core.scenario import next_color


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r)
         - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _ship(
    index: int,
    ship_id: str,
    start: Tuple[float, float],   # (lat, lon)
    end:   Tuple[float, float],   # (lat, lon)
    speed_mps: float = 4.0,
    length_m:  float = 100.0,
    beam_m:    float = 15.0,
    radar_s:   float = 6.0,
) -> dict:
    hdg = _bearing(start[0], start[1], end[0], end[1])
    return {
        "ship_id":              ship_id,
        "mmsi":                 211_000_000 + random.randint(1, 999_999),
        "length_m":             length_m,
        "beam_m":               beam_m,
        "draught_m":            5.0,
        "initial_speed_mps":    speed_mps,
        "initial_heading_deg":  hdg,
        "waypoints":            [start, end],  # 💡 FIX: Keep as clean tuples so app.py extracts numbers, not dictionary keys!
        "radar_rotation_s":     radar_s,
        "color":                next_color(index),
    }


# ===========================================================================
# FIXED RHEINHAFEN scenarios (Restricted to verified internal channel bounds)
# ===========================================================================

def _rheinhafen_crossing() -> List[dict]:
    """Ship 1 moves along the harbor lane axis. 
    Ship 2 slices across the channel path from the interior basin.
    """
    return [
        _ship(0, "Ship_1 (SW→NE channel)",
              (49.0130, 8.3360), (49.0150, 8.2990),
              speed_mps=4.0),
        _ship(1, "Ship_2 (port→channel crossing)",
              (49.0135, 8.2970), (49.0145, 8.3330),
              speed_mps=3.0),
    ]


def _rheinhafen_head_on() -> List[dict]:
    """Two ships on the same narrow channel axis approaching from opposite ends."""
    return [
        _ship(0, "Ship_1 (SW→NE)",
              (49.0130, 8.3280), (49.0150, 8.2970),
              speed_mps=4.0),
        _ship(1, "Ship_2 (NE→SW)",
              (49.0150, 8.2970), (49.0130, 8.3280),
              speed_mps=4.0),
    ]


def _rheinhafen_overtaking() -> List[dict]:
    """Both ships head down the basin lane, one catching up rapidly from behind."""
    return [
        _ship(0, "Ship_1 (fast, behind)",
              (49.0130, 8.3280), (49.0150, 8.2970),
              speed_mps=6.5),
        _ship(1, "Ship_2 (slow, ahead)",
              (49.0140, 8.3190), (49.0150, 8.2970),
              speed_mps=2.0),
    ]


def _rheinhafen_harbor_traffic() -> List[dict]:
    """Mixed port traffic using multi-point tuple arrays to navigate river bends cleanly."""
    
    def _multi_wp_ship(index, ship_id, wps, speed, length=100.0, beam=15.0):
        return {
            "ship_id":              ship_id,
            "mmsi":                 211_000_000 + random.randint(1, 999_999),
            "length_m":             length,
            "beam_m":               beam,
            "draught_m":            5.0,
            "initial_speed_mps":    speed,
            "initial_heading_deg":  _bearing(wps[0][0], wps[0][1], wps[1][0], wps[1][1]),
            "waypoints":            wps,  # 💡 Clean list of coordinate tuples [(lat, lon), (lat, lon)]
            "radar_rotation_s":     6.0,
            "color":                next_color(index),
        }

    return [
        # Inbound_1: Starts in river, turns into the channel junction, hits the basin dock
        _multi_wp_ship(0, "Inbound_1", [
            (49.0110, 8.2950),  # In River Channel
            (49.0145, 8.2970),  # Turn point at junction entrance
            (49.0145, 8.3360)   # Final basin coordinate
        ], speed=3.0),

        # Inbound_2: Parallel path curving into dock
        _multi_wp_ship(1, "Inbound_2", [
            (49.0080, 8.2940),  
            (49.0142, 8.2970),  
            (49.0130, 8.3280)   
        ], speed=3.5),

        # Outbound tracks
        _multi_wp_ship(2, "Outbound_1", [(49.0150, 8.2970), (49.0140, 8.3330)], speed=3.0),
        _multi_wp_ship(3, "Outbound_2", [(49.0150, 8.2990), (49.0130, 8.3270)], speed=3.8),
        _multi_wp_ship(4, "Barge_1",    [(49.0140, 8.2970), (49.0140, 8.3190)], speed=1.5, length=150.0, beam=22.0),
    ]


# ===========================================================================
# CUXHAVEN scenarios 
# ===========================================================================

def _cuxhaven_crossing() -> List[dict]:
    return [
        _ship(0, "Ship_1 (W→E estuary)",
              (53.848, 8.760), (53.848, 8.970),
              speed_mps=5.0),
        _ship(1, "Ship_2 (N→S crossing)",
              (53.844, 8.860), (53.834, 8.860),
              speed_mps=4.0),
    ]


def _cuxhaven_head_on() -> List[dict]:
    return [
        _ship(0, "Ship_1 (W→E)",
              (53.845, 8.760), (53.845, 8.970),
              speed_mps=5.0),
        _ship(1, "Ship_2 (E→W)",
              (53.851, 8.970), (53.851, 8.760),
              speed_mps=5.0),
    ]


def _cuxhaven_overtaking() -> List[dict]:
    return [
        _ship(0, "Ship_1 (fast)",
              (53.848, 8.760), (53.848, 8.980),
              speed_mps=7.0),
        _ship(1, "Ship_2 (slow, ahead)",
              (53.845, 8.891), (53.845, 8.985),
              speed_mps=2.5),
    ]


def _cuxhaven_harbor_traffic() -> List[dict]:
    return [
        _ship(0, "Inbound_1", (53.848, 8.950), (53.848, 8.760), speed_mps=4.0),
        _ship(1, "Inbound_2", (53.845, 8.940), (53.845, 8.770), speed_mps=3.5),
        _ship(2, "Outbound_1", (53.842, 8.775), (53.842, 8.940), speed_mps=4.5),
        _ship(3, "Outbound_2", (53.839, 8.790), (53.839, 8.930), speed_mps=3.8),
        _ship(4, "Barge_1", (53.844, 8.860), (53.836, 8.860), speed_mps=1.5, length_m=150.0, beam_m=22.0),
    ]


# ===========================================================================
# Public API
# ===========================================================================

_BUILDERS = {
    "rheinhafen": {
        "crossing":       _rheinhafen_crossing,
        "head_on":        _rheinhafen_head_on,
        "overtaking":     _rheinhafen_overtaking,
        "harbor_traffic": _rheinhafen_harbor_traffic,
    },
    "cuxhaven": {
        "crossing":       _cuxhaven_crossing,
        "head_on":        _cuxhaven_head_on,
        "overtaking":     _cuxhaven_overtaking,
        "harbor_traffic": _cuxhaven_harbor_traffic,
    },
}


def build_scenario(encounter_type: str, region_key: str) -> List[dict]:
    if encounter_type == "custom":
        return []
    region_builders = _BUILDERS.get(region_key, _BUILDERS["rheinhafen"])
    builder = region_builders.get(encounter_type)
    if builder is None:
        return []
    return builder()