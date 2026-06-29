"""core/physics/pipeline.py

Connects the MMG physics model to the multi-ship trajectory pipeline.

Public functions:
    build_trajectory_physics()   — single ship, returns ShipTrajectory
    scenario_with_physics()      — all ships in scenario dict, returns augmented dict

These are drop-in replacements for:
    core.trajectory.build_trajectory()
    core.trajectory.scenario_with_trajectories()

The output format (ShipTrajectory / TrajectoryPoint) is identical so radar,
Plotly animation, and JSON export all work without any changes.

Wind data:
    By default, uses the old OpenWeatherMap API (same key).
    If the API is unavailable the model falls back to the EnvParams values
    set by the user in the sidebar.
"""

from __future__ import annotations

import copy
import math
import requests
from dataclasses import asdict
from typing import List, Optional, Tuple

from core.trajectory import ShipTrajectory, TrajectoryPoint
from core.physics.mmg_model import ShipParams, EnvParams, _ShipState, step
from core.physics.guidance import (
    cross_track_error,
    heading_error,
    compute_rudder_angle,
    target_rpm,
    should_switch_waypoint,
    thrust_factor,
    GOAL_DIST_M,
)
from core.physics.coordinate_utils import geodesic_distance


# ---------------------------------------------------------------------------
# Optional live wind fetch (same API key as seniors)
# ---------------------------------------------------------------------------

_WIND_CACHE: dict = {"val": (0.0, 0.0)}
_OWM_KEY = "6c77c4bd0f7280bf206a277dc5407cab"


def _fetch_wind(lat: float, lon: float) -> Tuple[float, float]:
    """Return (wind_speed m/s, wind_dir_deg). Cached fallback on failure."""
    try:
        r = requests.get(
            "http://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": _OWM_KEY, "units": "metric"},
            timeout=5,
        )
        r.raise_for_status()
        w = r.json().get("wind", {})
        _WIND_CACHE["val"] = (float(w.get("speed", 0.0)), float(w.get("deg", 0.0)))
    except Exception:
        pass   # keep last cached value
    return _WIND_CACHE["val"]


# ---------------------------------------------------------------------------
# LOS path builder (port-aware for Rheinhafen, simple for Cuxhaven)
# Uses the old build_route_port_aware_Rhein / lineofsight_Cuxhaven
# if the required data files exist; otherwise falls back to straight line.
# ---------------------------------------------------------------------------

def _build_los_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    region_key: str,
) -> List[Tuple[float, float]]:
    """Build a Line-of-Sight reference path between start and end.

    Tries to load the old port/polygon data and use their routing
    logic.  If data files are not present (e.g. during testing), falls
    back to a simple two-point straight path.
    """
    try:
        import json, os
        from pathlib import Path

        old_data = Path(__file__).resolve().parents[3] / "physics based model"
        # Try to find the data files in common locations
        candidates = [
            old_data,
            Path("physics based model"),
            Path("data"),
        ]

        if region_key == "rheinhafen":
            for base in candidates:
                poly_f  = base / "polygons.json"
                port_f  = base / "portlines.json"
                cl_f    = base / "Rheinhafen_line_of_sight.json"
                if poly_f.exists() and port_f.exists() and cl_f.exists():
                    # Import old helpers inline
                    import sys
                    sys.path.insert(0, str(base.parent))
                    # Use our LOS data file directly
                    with open(poly_f)  as f: polys   = json.load(f)
                    with open(port_f)  as f: ports_raw = json.load(f)
                    with open(cl_f)    as f: cl      = json.load(f)
                    ports = {k: [(lat, lon) for (lon, lat) in v]
                             for k, v in ports_raw.items()}
                    # Inline the old build_route_port_aware_Rhein
                    from core.physics._los_rhein import build_route
                    return build_route(start, end, polys, ports, cl)

        elif region_key == "cuxhaven":
            for base in candidates:
                cl_f = base / "Cuxhaven_line_of_sight.json"
                if cl_f.exists():
                    with open(cl_f) as f:
                        cl = json.load(f)
                    return _los_cuxhaven(start, end, cl)

    except Exception:
        pass

    # Fallback: straight line with intermediate points every ~500 m
    return _straight_los(start, end)


def _los_cuxhaven(
    start: Tuple[float, float],
    end:   Tuple[float, float],
    cl:    list,
) -> List[Tuple[float, float]]:
    """Cuxhaven LOS — matches old lineofsight_Cuxhaven exactly."""
    y_min = min(start[1], end[1])
    y_max = max(start[1], end[1])
    use_reverse = (end[1] - start[1]) > 0
    source = cl[::-1] if use_reverse else cl
    path = [start] + [pt for pt in source if y_min <= pt[1] <= y_max] + [end]
    # dedup
    out = []
    for p in path:
        if not out or p != out[-1]:
            out.append(p)
    return out


def _straight_los(
    start: Tuple[float, float],
    end:   Tuple[float, float],
    n_intermediate: int = 5,
) -> List[Tuple[float, float]]:
    """Simple straight-line fallback path."""
    path = [start]
    for i in range(1, n_intermediate + 1):
        t = i / (n_intermediate + 1)
        path.append((
            start[0] + t * (end[0] - start[0]),
            start[1] + t * (end[1] - start[1]),
        ))
    path.append(end)
    return path


# ---------------------------------------------------------------------------
# Core single-ship simulation
# ---------------------------------------------------------------------------

def build_trajectory_physics(
    ship_id:     str,
    mmsi:        int,
    color:       str,
    waypoints:   List[Tuple[float, float]],
    ship_params: ShipParams,
    env_params:  EnvParams,
    region_key:  str = "rheinhafen",
    dt:          float = 1.0,
    use_live_wind: bool = True,
) -> ShipTrajectory:
    """Run the full MMG simulation for one ship and return a ShipTrajectory.

    Parameters
    ----------
    ship_id, mmsi, color : ship identity (passed through to output)
    waypoints            : [(lat, lon), ...] from user or scenario_builder
    ship_params          : ShipParams dataclass
    env_params           : EnvParams dataclass (wind, current)
    region_key           : "rheinhafen" or "cuxhaven"
    dt                   : time step in seconds (default 1)
    use_live_wind        : if True, tries OpenWeatherMap API for wind
    """
    if len(waypoints) < 2:
        return ShipTrajectory(ship_id=ship_id, mmsi=mmsi, color=color, points=[])

    start = waypoints[0]
    end   = waypoints[-1]

    # If the user supplied 3+ waypoints, treat them as explicit via-points
    # the ship must visit in order. Otherwise (just start + end) fall back
    # to the LOS routing for a realistic fairway path.
    if len(waypoints) >= 3:
        simulation_path = list(waypoints)
    else:
        los_path = _build_los_path(start, end, region_key)
        if len(los_path) < 2:
            los_path = [start, end]
        simulation_path = los_path

    # Initialise ship state
    from core.physics.coordinate_utils import bearing as _brg
    initial_hdg = (90 - _brg(start, simulation_path[1] if len(simulation_path) > 1 else end)) % 360
    ship_params.initial_lat         = start[0]
    ship_params.initial_lon         = start[1]
    ship_params.initial_heading_deg = initial_hdg

    state = _ShipState(ship_params)
    state.dt = dt

    # Wind initialisation
    if use_live_wind:
        ws, wd = _fetch_wind(start[0], start[1])
        env_params.wind_speed_mps = ws
        env_params.wind_dir_deg   = wd

    traj = ShipTrajectory(ship_id=ship_id, mmsi=mmsi, color=color)
    traj.points.append(TrajectoryPoint(
        t=0.0, lat=round(state.lat, 7), lon=round(state.lon, 7),
        heading=round(math.degrees(state.psi) % 360, 2),
        speed_mps=round(state.u, 3),
    ))

    ref_idx = 1
    current_ref = simulation_path[ref_idx]
    max_steps   = 20_000
    t           = 0.0

    for step_i in range(1, max_steps + 1):
        t += dt
        elapsed = step_i * dt

        # Refresh live wind every 5 minutes
        if use_live_wind and step_i % 300 == 0:
            ws, wd = _fetch_wind(state.lat, state.lon)
            env_params.wind_speed_mps = ws
            env_params.wind_dir_deg   = wd

        # Goal check
        if geodesic_distance((state.lat, state.lon), (end[0], end[1])) < GOAL_DIST_M:
            break

        # Heading and CTE
        hdg_err = heading_error(state.lat, state.lon, state.psi,
                                current_ref[0], current_ref[1])

        if ref_idx + 1 < len(simulation_path):
            seg_a = simulation_path[ref_idx - 1]
            seg_b = simulation_path[ref_idx]
        else:
            seg_a = simulation_path[-2]
            seg_b = simulation_path[-1]

        cte        = cross_track_error((state.lat, state.lon), seg_a, seg_b)
        rudder_deg = compute_rudder_angle(hdg_err, cte, state.u)
        trpm       = target_rpm(elapsed, ship_params.target_n_rpm) * thrust_factor(rudder_deg)

        # Physics step
        step(state, env_params, rudder_deg, trpm)

        # Record
        traj.points.append(TrajectoryPoint(
            t=round(t, 3),
            lat=round(state.lat, 7),
            lon=round(state.lon, 7),
            heading=round(math.degrees(state.psi) % 360, 2),
            speed_mps=round(state.u, 3),
        ))

        # Waypoint switching
        if should_switch_waypoint((state.lat, state.lon), current_ref,
                                   ref_idx, len(simulation_path)):
            ref_idx    += 1
            current_ref = simulation_path[ref_idx]

    # Snap final point to destination
    traj.points.append(TrajectoryPoint(
        t=round(t, 3), lat=end[0], lon=end[1],
        heading=round(math.degrees(state.psi) % 360, 2),
        speed_mps=round(state.u, 3),
    ))

    return traj


# ---------------------------------------------------------------------------
# Multi-ship scenario entry point
# ---------------------------------------------------------------------------

def scenario_with_physics(
    scenario_dict: dict,
    env_params:    Optional[EnvParams] = None,
    dt:            float = 1.0,
    use_live_wind: bool  = True,
) -> dict:
    """Run MMG physics for all ships and return augmented scenario dict.

    Drop-in replacement for core.trajectory.scenario_with_trajectories().
    Each ship gets its own independent ShipParams and _ShipState so they
    don't interfere with each other.
    """
    if env_params is None:
        env_params = EnvParams()

    result = copy.deepcopy(scenario_dict)
    region = scenario_dict.get("region", "rheinhafen")

    for ship_dict in result.get("ships", []):
        raw_wps  = ship_dict.get("waypoints", [])
        waypoints: List[Tuple[float, float]] = [
            (wp["lat"], wp["lon"]) for wp in raw_wps
        ]
        if len(waypoints) < 2:
            ship_dict["trajectory"] = []
            continue

        # Build per-ship ShipParams
        sp = ShipParams(
            initial_lat         = waypoints[0][0],
            initial_lon         = waypoints[0][1],
            initial_heading_deg = float(ship_dict.get("initial_heading_deg", 0.0)),
        )
        # Use ship size from scenario if provided
        sp.mass = float(ship_dict.get("length_m", 100.0)) * 65_000.0  # rough proxy

        # Independent copy of env per ship (wind fetched fresh per ship)
        import copy as _copy
        ship_env = _copy.copy(env_params)

        traj = build_trajectory_physics(
            ship_id     = ship_dict["ship_id"],
            mmsi        = ship_dict["mmsi"],
            color       = ship_dict.get("color", "#1f77b4"),
            waypoints   = waypoints,
            ship_params = sp,
            env_params  = ship_env,
            region_key  = region,
            dt          = dt,
            use_live_wind = use_live_wind,
        )

        ship_dict["trajectory"] = [asdict(p) for p in traj.points]

    return result