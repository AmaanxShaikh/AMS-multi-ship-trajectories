"""Constant-velocity trajectory model.

Given a Ship's waypoints, speed, and heading this module:
  1. Interpolates a smooth trajectory at a fixed time step (dt).
  2. Provides a generator that yields per-ship positions so Streamlit can
     update the map every N seconds (matching the ship's radar_rotation_s).
  3. Augments the Scenario JSON with a 'trajectory' list per ship.

Physics model: constant speed + great-circle bearing between consecutive
waypoints.  No hydrodynamics — that is the MMG model which will be wired in
by the supervisor in a later milestone.

Usage (standalone test):
    python core/trajectory.py

Usage (from Streamlit app):
    from core.trajectory import build_trajectories, simulate_step
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Generator, List, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_M = 6_371_000.0          # mean Earth radius in metres
DEFAULT_DT_S    = 1.0                  # simulation time step in seconds


# ---------------------------------------------------------------------------
# Maths helpers
# ---------------------------------------------------------------------------

def _deg2rad(deg: float) -> float:
    return deg * math.pi / 180.0


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing in degrees (0 = North, clockwise) from point 1 to point 2."""
    lat1r, lat2r = _deg2rad(lat1), _deg2rad(lat2)
    dlon = _deg2rad(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r)
         - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360.0) % 360.0


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two (lat, lon) points."""
    lat1r, lat2r = _deg2rad(lat1), _deg2rad(lat2)
    dlat = _deg2rad(lat2 - lat1)
    dlon = _deg2rad(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2)
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _move(lat: float, lon: float, bearing_deg: float, distance_m: float
          ) -> Tuple[float, float]:
    """Return new (lat, lon) after moving `distance_m` metres on `bearing_deg`."""
    lat_r   = _deg2rad(lat)
    lon_r   = _deg2rad(lon)
    bear_r  = _deg2rad(bearing_deg)
    d_over_r = distance_m / EARTH_RADIUS_M

    new_lat = math.asin(
        math.sin(lat_r) * math.cos(d_over_r)
        + math.cos(lat_r) * math.sin(d_over_r) * math.cos(bear_r)
    )
    new_lon = lon_r + math.atan2(
        math.sin(bear_r) * math.sin(d_over_r) * math.cos(lat_r),
        math.cos(d_over_r) - math.sin(lat_r) * math.sin(new_lat)
    )
    return math.degrees(new_lat), math.degrees(new_lon)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryPoint:
    """Position of a ship at a single time step."""
    t:          float   # elapsed simulation time in seconds
    lat:        float
    lon:        float
    heading:    float   # degrees true (0 = North)
    speed_mps:  float


@dataclass
class ShipTrajectory:
    """Complete pre-computed trajectory for one ship."""
    ship_id:    str
    mmsi:       int
    color:      str
    points:     List[TrajectoryPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Core: build trajectory from waypoints
# ---------------------------------------------------------------------------

def build_trajectory(
    ship_id: str,
    mmsi: int,
    color: str,
    waypoints: List[Tuple[float, float]],   # [(lat, lon), ...]
    speed_mps: float,
    initial_heading_deg: float,
    dt: float = DEFAULT_DT_S,
) -> ShipTrajectory:
    """Compute constant-velocity trajectory for one ship.

    The ship travels from waypoint to waypoint at constant speed.
    Heading is recomputed at each waypoint to aim at the next one.
    If only one waypoint is provided the ship holds its initial heading.
    """
    traj = ShipTrajectory(ship_id=ship_id, mmsi=mmsi, color=color)

    if not waypoints:
        return traj

    # Starting conditions
    lat, lon = waypoints[0]
    t        = 0.0
    heading  = initial_heading_deg

    # Record start
    traj.points.append(TrajectoryPoint(t=t, lat=lat, lon=lon,
                                       heading=heading, speed_mps=speed_mps))

    if len(waypoints) == 1:
        # No destination — stay put (placeholder point at t=1)
        traj.points.append(TrajectoryPoint(t=dt, lat=lat, lon=lon,
                                           heading=heading, speed_mps=0.0))
        return traj

    # Walk through each leg
    for wp_idx in range(1, len(waypoints)):
        tgt_lat, tgt_lon = waypoints[wp_idx]
        leg_dist = _distance_m(lat, lon, tgt_lat, tgt_lon)
        heading  = _bearing(lat, lon, tgt_lat, tgt_lon)

        if speed_mps <= 0.0 or leg_dist <= 0.0:
            lat, lon = tgt_lat, tgt_lon
            traj.points.append(TrajectoryPoint(t=t, lat=lat, lon=lon,
                                               heading=heading, speed_mps=0.0))
            continue

        step_dist = speed_mps * dt           # metres covered per time step
        remaining  = leg_dist

        while remaining > step_dist:
            lat, lon   = _move(lat, lon, heading, step_dist)
            t         += dt
            remaining -= step_dist
            traj.points.append(TrajectoryPoint(
                t=round(t, 3), lat=round(lat, 7), lon=round(lon, 7),
                heading=round(heading, 2), speed_mps=speed_mps,
            ))

        # Snap to the waypoint (remaining < one full step)
        frac_t = remaining / speed_mps if speed_mps > 0 else 0.0
        t     += frac_t
        lat, lon = tgt_lat, tgt_lon
        traj.points.append(TrajectoryPoint(
            t=round(t, 3), lat=lat, lon=lon,
            heading=round(heading, 2), speed_mps=speed_mps,
        ))

    return traj


# ---------------------------------------------------------------------------
# Build trajectories for all ships in a scenario dict
# ---------------------------------------------------------------------------

def build_trajectories(
    scenario_dict: dict,
    dt: float = DEFAULT_DT_S,
) -> List[ShipTrajectory]:
    """Given a scenario dict (from Scenario.to_dict()), return trajectories.

    The scenario dict format matches what core/scenario.py produces.
    """
    trajectories: List[ShipTrajectory] = []

    for ship in scenario_dict.get("ships", []):
        raw_wps = ship.get("waypoints", [])
        # waypoints are {"lat": ..., "lon": ...} dicts in the JSON
        waypoints: List[Tuple[float, float]] = [
            (wp["lat"], wp["lon"]) for wp in raw_wps
        ]

        traj = build_trajectory(
            ship_id             = ship["ship_id"],
            mmsi                = ship["mmsi"],
            color               = ship.get("color", "#1f77b4"),
            waypoints           = waypoints,
            speed_mps           = float(ship.get("initial_speed_mps", 5.0)),
            initial_heading_deg = float(ship.get("initial_heading_deg", 0.0)),
            dt                  = dt,
        )
        trajectories.append(traj)

    return trajectories


# ---------------------------------------------------------------------------
# Position-update generator (for live Streamlit simulation)
# ---------------------------------------------------------------------------

def simulate_step(
    trajectories: List[ShipTrajectory],
    radar_rotation_s: float = 6.0,
) -> Generator[List[dict], None, None]:
    """Yield current ship positions every `radar_rotation_s` seconds.

    Each yielded value is a list of dicts, one per ship:
        {"ship_id": str, "lat": float, "lon": float,
         "heading": float, "speed_mps": float, "t": float}

    This is a real-time generator: it sleeps between yields.
    Use inside a Streamlit placeholder:

        placeholder = st.empty()
        for positions in simulate_step(trajectories):
            with placeholder.container():
                st.write(positions)          # or update a map

    The loop ends when all ships have reached their final waypoint.
    """
    # How many trajectory points fall in one radar rotation?
    points_per_tick = max(1, int(round(radar_rotation_s / DEFAULT_DT_S)))

    # Find the longest trajectory
    max_steps = max((len(t.points) for t in trajectories), default=0)

    step = 0
    while step < max_steps:
        snapshot: List[dict] = []
        for traj in trajectories:
            idx = min(step, len(traj.points) - 1)
            p   = traj.points[idx]
            snapshot.append({
                "ship_id":   traj.ship_id,
                "color":     traj.color,
                "lat":       p.lat,
                "lon":       p.lon,
                "heading":   p.heading,
                "speed_mps": p.speed_mps,
                "t":         p.t,
            })
        yield snapshot
        step += points_per_tick
        time.sleep(radar_rotation_s)


# ---------------------------------------------------------------------------
# JSON output: augment scenario dict with trajectories
# ---------------------------------------------------------------------------

def scenario_with_trajectories(
    scenario_dict: dict,
    dt: float = DEFAULT_DT_S,
) -> dict:
    """Return a copy of scenario_dict with 'trajectory' added to each ship.

    The returned dict is JSON-serialisable and can be saved with:
        json.dumps(result, indent=2)
    """
    import copy
    result = copy.deepcopy(scenario_dict)
    trajectories = build_trajectories(scenario_dict, dt=dt)

    traj_map = {t.ship_id: t for t in trajectories}
    for ship in result.get("ships", []):
        traj = traj_map.get(ship["ship_id"])
        if traj:
            ship["trajectory"] = [asdict(p) for p in traj.points]

    return result


# ---------------------------------------------------------------------------
# Quick self-test — run with:  python core/trajectory.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Simulate a simple two-ship crossing scenario in Rheinhafen
    test_scenario = {
        "name": "test_crossing",
        "region": "rheinhafen",
        "encounter_type": "crossing",
        "ships": [
            {
                "ship_id": "Ship_1",
                "mmsi": 211000001,
                "color": "#1f77b4",
                "initial_speed_mps": 3.0,
                "initial_heading_deg": 90.0,
                "radar_rotation_s": 6.0,
                "waypoints": [
                    {"lat": 49.020, "lon": 8.295},
                    {"lat": 49.020, "lon": 8.320},
                ],
            },
            {
                "ship_id": "Ship_2",
                "mmsi": 211000002,
                "color": "#d62728",
                "initial_speed_mps": 2.5,
                "initial_heading_deg": 0.0,
                "radar_rotation_s": 6.0,
                "waypoints": [
                    {"lat": 49.010, "lon": 8.307},
                    {"lat": 49.030, "lon": 8.307},
                ],
            },
        ],
    }

    result = scenario_with_trajectories(test_scenario, dt=1.0)

    for ship in result["ships"]:
        pts = ship["trajectory"]
        print(f"\n{ship['ship_id']}: {len(pts)} trajectory points")
        print(f"  Start : lat={pts[0]['lat']:.5f}, lon={pts[0]['lon']:.5f}, t={pts[0]['t']:.1f}s")
        print(f"  End   : lat={pts[-1]['lat']:.5f}, lon={pts[-1]['lon']:.5f}, t={pts[-1]['t']:.1f}s")
        total_dist = _distance_m(pts[0]['lat'], pts[0]['lon'],
                                  pts[-1]['lat'], pts[-1]['lon'])
        print(f"  Dist  : {total_dist:.0f} m  |  Time: {pts[-1]['t']:.1f} s")

    print("\nFull JSON output:")
    print(json.dumps(result, indent=2)[:1200], "...\n[truncated]")
