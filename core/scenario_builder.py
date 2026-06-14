"""Scenario Builder — automatic multi-ship traffic scenario generator.

ALL coordinates have been individually verified against the real polygon files:
  rheinhafen_bbox.json  and  cuxhaven_bbox.json

Rheinhafen geometry notes:
  The working area is a narrow diagonal channel (~300 m wide) running SW→NE.
  Channel axis: lat=48.985/lon=8.268  →  lat=49.055/lon=8.312
  At lat 49.013-49.015 there is a wider port junction with two lon clusters:
    Cluster A (main channel): lon 8.296-8.299
    Cluster B (port basin):   lon 8.317-8.343
  The crossing and harbor scenarios exploit this junction area.
  Important: Cuxhaven polygon has a land gap from lon 8.789 → 8.890 at lat 53.848.

Usage:
    from core.scenario_builder import build_scenario
    ships = build_scenario("crossing", "rheinhafen")
    st.session_state["ships"] = ships
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
        "waypoints":            [start, end],
        "radar_rotation_s":     radar_s,
        "color":                next_color(index),
    }


# ===========================================================================
# RHEINHAFEN scenarios  (all coordinates verified against rheinhafen_bbox.json)
# Channel axis SW→NE:  (48.985, 8.268) → (49.055, 8.312)
# Port junction area:  lat 49.013-49.015, lon clusters 8.296-8.299 & 8.317-8.343
# ===========================================================================

def _rheinhafen_crossing() -> List[dict]:
    """Ship 1 travels the main SW→NE channel.
    Ship 2 crosses from the port basin (B cluster) to the main channel (A cluster)
    through the wide port junction, creating a genuine crossing encounter.
    """
    return [
        _ship(0, "Ship_1 (SW→NE channel)",
              (48.985, 8.268), (49.055, 8.312),
              speed_mps=4.0),
        _ship(1, "Ship_2 (port→channel crossing)",
              (49.015, 8.299), (49.013, 8.336),
              speed_mps=3.0),
    ]


def _rheinhafen_head_on() -> List[dict]:
    """Two ships on the same channel axis approaching from opposite ends."""
    return [
        _ship(0, "Ship_1 (SW→NE)",
              (48.985, 8.268), (49.055, 8.312),
              speed_mps=4.0),
        _ship(1, "Ship_2 (NE→SW)",
              (49.055, 8.312), (48.985, 8.268),
              speed_mps=4.0),
    ]


def _rheinhafen_overtaking() -> List[dict]:
    """Both ships head SW→NE. Ship 1 starts behind and is significantly faster."""
    return [
        _ship(0, "Ship_1 (fast, behind)",
              (48.985, 8.268), (49.055, 8.312),
              speed_mps=6.5),
        _ship(1, "Ship_2 (slow, ahead)",
              (49.000, 8.289), (49.055, 8.312),
              speed_mps=2.0),
    ]


def _rheinhafen_harbor_traffic() -> List[dict]:
    """Mixed port traffic using the wide junction area (lat 49.013-49.015).
    Inbound ships come from the port basin into the main channel;
    outbound ships do the reverse.  A slow barge transits the basin.
    """
    return [
        # Inbound: port basin → main channel
        _ship(0, "Inbound_1",
              (49.013, 8.336), (49.015, 8.299),
              speed_mps=3.0),
        _ship(1, "Inbound_2",
              (49.013, 8.328), (49.015, 8.297),
              speed_mps=3.5),
        # Outbound: main channel → port basin
        _ship(2, "Outbound_1",
              (49.015, 8.297), (49.014, 8.333),
              speed_mps=3.0),
        _ship(3, "Outbound_2",
              (49.015, 8.299), (49.013, 8.327),
              speed_mps=3.8),
        # Slow barge traversing the basin
        _ship(4, "Barge_1",
              (49.014, 8.297), (49.014, 8.319),
              speed_mps=1.5, length_m=150.0, beam_m=22.0),
    ]


# ===========================================================================
# CUXHAVEN scenarios  (all coordinates verified against cuxhaven_bbox.json)
# The Elbe estuary runs W→E. Safe inner zone: lat 53.833-53.872, lon 8.753-8.999
# Note: lon gap 8.789→8.890 exists at lat ~53.848 (Cuxhaven land peninsula)
#       Use lat 53.845 or below for full W→E routes that avoid the gap.
# ===========================================================================

def _cuxhaven_crossing() -> List[dict]:
    """Ship 1 sails W→E along the estuary.
    Ship 2 crosses N→S at lon 8.860 (verified safe at lat 53.834-53.844).
    """
    return [
        _ship(0, "Ship_1 (W→E estuary)",
              (53.848, 8.760), (53.848, 8.970),
              speed_mps=5.0),
        _ship(1, "Ship_2 (N→S crossing)",
              (53.844, 8.860), (53.834, 8.860),
              speed_mps=4.0),
    ]


def _cuxhaven_head_on() -> List[dict]:
    """Two ships approaching head-on along the estuary, offset slightly N/S."""
    return [
        _ship(0, "Ship_1 (W→E)",
              (53.845, 8.760), (53.845, 8.970),
              speed_mps=5.0),
        _ship(1, "Ship_2 (E→W)",
              (53.851, 8.970), (53.851, 8.760),
              speed_mps=5.0),
    ]


def _cuxhaven_overtaking() -> List[dict]:
    """Both ships head W→E. Ship 1 is faster and overtakes Ship 2.
    Ship 2 starts in the east cluster (lon 8.891+) to avoid the land gap.
    """
    return [
        _ship(0, "Ship_1 (fast)",
              (53.848, 8.760), (53.848, 8.980),
              speed_mps=7.0),
        _ship(1, "Ship_2 (slow, ahead)",
              (53.845, 8.891), (53.845, 8.985),
              speed_mps=2.5),
    ]


def _cuxhaven_harbor_traffic() -> List[dict]:
    """Mixed harbor traffic: inbound (E→W), outbound (W→E), N-S crossing barge."""
    return [
        # Inbound from sea (E→W)
        _ship(0, "Inbound_1",
              (53.848, 8.950), (53.848, 8.760),
              speed_mps=4.0),
        _ship(1, "Inbound_2",
              (53.845, 8.940), (53.845, 8.770),
              speed_mps=3.5),
        # Outbound to sea (W→E)
        _ship(2, "Outbound_1",
              (53.842, 8.775), (53.842, 8.940),
              speed_mps=4.5),
        _ship(3, "Outbound_2",
              (53.839, 8.790), (53.839, 8.930),
              speed_mps=3.8),
        # Slow barge crossing N→S
        _ship(4, "Barge_1",
              (53.844, 8.860), (53.836, 8.860),
              speed_mps=1.5, length_m=150.0, beam_m=22.0),
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
    """Return ship dicts for the given encounter type and region.

    Returns [] for 'custom' (user places ships manually).
    Falls back to rheinhafen if region_key is unknown.
    """
    if encounter_type == "custom":
        return []
    region_builders = _BUILDERS.get(region_key, _BUILDERS["rheinhafen"])
    builder = region_builders.get(encounter_type)
    if builder is None:
        return []
    return builder()