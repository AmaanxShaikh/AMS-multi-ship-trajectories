"""Radar Simulator — Task 3 of the project brief.

"Simulate maritime radar measurements based on physical models."

A maritime radar rotates at a fixed period (radar_rotation_s).  Each time the
antenna sweeps past a target it records:
  • range   — slant distance from radar origin to target (metres)
  • azimuth — bearing from radar origin to target (degrees true, 0 = North)
  • RCS     — radar cross-section proxy (function of ship size)

The radar origin is fixed at the center of the working area.  For each ship,
we step through its trajectory at multiples of radar_rotation_s and record
what the radar would see at that instant.

Output is a list of RadarReturn dataclass instances — one per (ship, sweep).
These are also embedded in the trajectory JSON under each ship as
"radar_returns": [...].

Usage:
    from core.radar import simulate_radar, radar_returns_to_df
    from core.trajectory import build_trajectories

    trajs   = build_trajectories(scenario_dict)
    returns = simulate_radar(trajs, radar_origin=(49.040, 8.303), radar_rotation_s=6.0)
    df      = radar_returns_to_df(returns)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_M = 6_371_000.0


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing in degrees (0 = North, clockwise)."""
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ---------------------------------------------------------------------------
# Radar cross-section (RCS) proxy
# ---------------------------------------------------------------------------

def _rcs_proxy(length_m: float, beam_m: float) -> float:
    """Simple RCS estimate: proportional to ship broadside area (m²).

    In a real radar model this would use the aspect angle and surface
    reflectivity.  Here we use a geometric proxy that is sufficient for
    visualisation and scenario evaluation.
    """
    broadside_area = length_m * beam_m          # m²
    return round(10 * math.log10(broadside_area + 1), 2)   # dBm²


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RadarReturn:
    """A single radar detection of one ship at one sweep."""
    ship_id:    str
    sweep:      int       # sweep index (0-based)
    t:          float     # simulation time in seconds
    lat:        float     # ship latitude at detection
    lon:        float     # ship longitude at detection
    range_m:    float     # distance from radar origin (metres)
    azimuth:    float     # bearing from radar origin (degrees true)
    rcs_dbm2:   float     # radar cross-section proxy (dBm²)
    heading:    float     # ship heading at detection
    speed_mps:  float     # ship speed at detection
    color:      str       # for visualisation


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def simulate_radar(
    trajectories: list,               # List[ShipTrajectory] from trajectory.py
    radar_origin: Tuple[float, float],  # (lat, lon) of radar station
    radar_rotation_s: float = 6.0,
    ship_lengths: dict | None = None,   # {ship_id: length_m}
    ship_beams:   dict | None = None,   # {ship_id: beam_m}
) -> List[RadarReturn]:
    """Generate radar returns for all ships across all sweeps.

    Parameters
    ----------
    trajectories      : output of build_trajectories()
    radar_origin      : (lat, lon) of the radar antenna
    radar_rotation_s  : seconds per full antenna rotation
    ship_lengths      : optional dict mapping ship_id → length_m (default 100)
    ship_beams        : optional dict mapping ship_id → beam_m   (default 15)
    """
    if ship_lengths is None:
        ship_lengths = {}
    if ship_beams is None:
        ship_beams = {}

    origin_lat, origin_lon = radar_origin
    returns: List[RadarReturn] = []

    for traj in trajectories:
        pts      = traj.points
        if not pts:
            continue

        length_m = ship_lengths.get(traj.ship_id, 100.0)
        beam_m   = ship_beams.get(traj.ship_id, 15.0)
        rcs      = _rcs_proxy(length_m, beam_m)

        # Step through trajectory at radar rotation intervals
        step = max(1, int(round(radar_rotation_s)))   # dt=1s → 1 pt per second
        sweep_idx = 0
        for i in range(0, len(pts), step):
            p = pts[i]
            range_m  = _haversine(origin_lat, origin_lon, p.lat, p.lon)
            azimuth  = _bearing(origin_lat, origin_lon, p.lat, p.lon)
            returns.append(RadarReturn(
                ship_id   = traj.ship_id,
                sweep     = sweep_idx,
                t         = p.t,
                lat       = p.lat,
                lon       = p.lon,
                range_m   = round(range_m, 1),
                azimuth   = round(azimuth, 2),
                rcs_dbm2  = rcs,
                heading   = p.heading,
                speed_mps = p.speed_mps,
                color     = traj.color,
            ))
            sweep_idx += 1

    return returns


def radar_returns_to_df(returns: List[RadarReturn]):
    """Convert radar returns to a pandas DataFrame."""
    import pandas as pd
    return pd.DataFrame([asdict(r) for r in returns])


def embed_radar_in_scenario(
    scenario_dict: dict,
    radar_origin: Tuple[float, float],
    radar_rotation_s: float = 6.0,
) -> dict:
    """Add 'radar_returns' list to each ship in the scenario dict.

    Call this after scenario_with_trajectories() to get the full output.

    Example
    -------
    from core.trajectory import scenario_with_trajectories
    from core.radar import embed_radar_in_scenario

    result = scenario_with_trajectories(scenario_dict)
    result = embed_radar_in_scenario(result, radar_origin=(49.040, 8.303))
    """
    import copy
    from core.trajectory import build_trajectories

    result = copy.deepcopy(scenario_dict)
    trajs  = build_trajectories(scenario_dict)

    ship_lengths = {s["ship_id"]: s.get("length_m", 100.0) for s in scenario_dict["ships"]}
    ship_beams   = {s["ship_id"]: s.get("beam_m",   15.0)  for s in scenario_dict["ships"]}

    returns = simulate_radar(
        trajs,
        radar_origin      = radar_origin,
        radar_rotation_s  = radar_rotation_s,
        ship_lengths      = ship_lengths,
        ship_beams        = ship_beams,
    )

    # Group returns by ship_id
    returns_by_ship: dict = {}
    for r in returns:
        returns_by_ship.setdefault(r.ship_id, []).append(asdict(r))

    for ship in result["ships"]:
        ship["radar_returns"] = returns_by_ship.get(ship["ship_id"], [])

    return result


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from core.trajectory import build_trajectories

    test_scenario = {
        "name": "radar_test",
        "region": "rheinhafen",
        "encounter_type": "crossing",
        "ships": [
            {
                "ship_id": "Ship_1", "mmsi": 211000001,
                "color": "#1f77b4", "length_m": 100.0, "beam_m": 15.0,
                "initial_speed_mps": 4.0, "initial_heading_deg": 0.0,
                "radar_rotation_s": 6.0,
                "waypoints": [
                    {"lat": 49.020, "lon": 8.295},
                    {"lat": 49.060, "lon": 8.305},
                ],
            },
            {
                "ship_id": "Ship_2", "mmsi": 211000002,
                "color": "#d62728", "length_m": 80.0, "beam_m": 12.0,
                "initial_speed_mps": 3.5, "initial_heading_deg": 0.0,
                "radar_rotation_s": 6.0,
                "waypoints": [
                    {"lat": 49.040, "lon": 8.270},
                    {"lat": 49.040, "lon": 8.330},
                ],
            },
        ],
    }

    radar_origin = (49.040, 8.303)
    trajs   = build_trajectories(test_scenario)
    returns = simulate_radar(trajs, radar_origin=radar_origin, radar_rotation_s=6.0)

    print(f"\nRadar returns generated: {len(returns)}")
    for r in returns[:5]:
        print(f"  {r.ship_id} | sweep {r.sweep} | t={r.t:.0f}s | "
              f"range={r.range_m:.0f}m | az={r.azimuth:.1f}° | RCS={r.rcs_dbm2}dBm²")
