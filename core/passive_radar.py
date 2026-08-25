"""Passive sensor timestamp simulation — SeaSentry-style peak-time recording.

This is the "get the timestamp of the beam hitting the sensor" piece
(see docs/radar_research.md, Sections 2 and 4).

Concept (the "lighthouse" analogy): a ship's radar beam sweeps in a full
circle every `rotation_period_s` seconds, pointing at 0 deg (north) at
t=0. A fixed sensor on shore only "sees" the beam for an instant, once per
rotation, whenever the beam's angle matches the true bearing from the ship
to that sensor. This module finds every one of those instants, for every
(ship, sensor) pair, across the whole trajectory — then adds a small random
timing error to mimic real (imperfect) sensor hardware.

Usage:
    from core.trajectory import build_trajectories
    from core.regions import load_region
    from core.sensors import default_sensor_layout
    from core.passive_radar import simulate_passive_detections, detections_to_json

    region  = load_region("rheinhafen")
    sensors = default_sensor_layout(region)
    trajs   = build_trajectories(scenario_dict)
    result  = simulate_passive_detections(trajs, sensors, rotation_periods={"Ship_1": 6.0})
    detections_to_json(result, "detections.json")
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict, dataclass
from typing import Dict, List

from core.radar import _bearing
from core.sensors import Sensor
from core.trajectory import ShipTrajectory, TrajectoryPoint, position_at_time


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    """One 'beam passed this sensor' event."""
    ship_id:    str
    sensor_id:  str
    sweep:      int       # rotation index (0-based)
    true_t:     float     # exact crossing time, seconds since scenario start
    measured_t: float     # true_t + injected timing noise


# ---------------------------------------------------------------------------
# Adapter: physics-engine trajectory dict -> ShipTrajectory
# ---------------------------------------------------------------------------

def trajectory_from_dict(ship: dict) -> ShipTrajectory:
    """Build a ShipTrajectory from one ship entry of a simulation result dict.

    Works with the output of core.physics.scenario_with_physics() (the real
    MMG physics engine the Streamlit app uses) as well as
    core.trajectory.scenario_with_trajectories() -- both produce ships shaped
    like {"ship_id", "mmsi", "color", "trajectory": [{"t","lat","lon",
    "heading","speed_mps"}, ...]}. This module's functions expect a
    ShipTrajectory object (attribute access, e.g. p.lat), not raw dicts, so
    this converts one to the other without duplicating the trajectory math.
    """
    traj = ShipTrajectory(
        ship_id = ship["ship_id"],
        mmsi    = int(ship.get("mmsi", 0)),
        color   = ship.get("color", "#1f77b4"),
    )
    for p in ship.get("trajectory", []):
        traj.points.append(TrajectoryPoint(
            t         = float(p["t"]),
            lat       = float(p["lat"]),
            lon       = float(p["lon"]),
            heading   = float(p["heading"]),
            speed_mps = float(p["speed_mps"]),
        ))
    return traj


# ---------------------------------------------------------------------------
# Step 3: peak-time finder
# ---------------------------------------------------------------------------

def find_peak_times(
    traj: ShipTrajectory,
    sensor: Sensor,
    rotation_period_s: float,
    max_iter: int = 3,
) -> List[float]:
    """Find every time the ship's beam sweeps past `sensor`.

    The beam points at 0 deg (north) at the start of each rotation
    (t = k * rotation_period_s) and sweeps a full 360 deg over the
    rotation period. Within rotation k, the beam points at bearing
    theta at time:

        t = k * rotation_period_s + (theta / 360) * rotation_period_s

    We want the `t` where `theta` equals the true bearing from the ship
    to the sensor -- but that bearing itself depends on the ship's
    position, which depends on `t`. Since the ship barely moves in the
    few seconds it takes the beam to sweep back around, a few rounds of
    "guess t, recompute bearing at that t, refine t" converges quickly
    (fixed-point iteration).

    Returns one timestamp per rotation, for as long as the trajectory
    lasts (empty list if the trajectory has zero duration).
    """
    if not traj.points or rotation_period_s <= 0:
        return []

    end_t = traj.points[-1].t
    if end_t <= 0:
        return []

    peak_times: List[float] = []
    n_rotations = int(end_t // rotation_period_s) + 1

    for k in range(n_rotations):
        t_guess = k * rotation_period_s
        for _ in range(max_iter):
            p = position_at_time(traj, min(t_guess, end_t))
            bearing = _bearing(p.lat, p.lon, sensor.lat, sensor.lon)
            t_guess = k * rotation_period_s + (bearing / 360.0) * rotation_period_s

        if t_guess <= end_t:
            peak_times.append(round(t_guess, 4))

    return peak_times


# ---------------------------------------------------------------------------
# Step 4: timing noise
# ---------------------------------------------------------------------------

def add_timing_noise(
    peak_times: List[float],
    sigma_s: float = 0.001,
    rng: random.Random | None = None,
) -> List[float]:
    """Add Gaussian timing noise (default sigma=1ms, per the SeaSentry paper)."""
    rng = rng or random
    return [round(t + rng.gauss(0.0, sigma_s), 6) for t in peak_times]


# ---------------------------------------------------------------------------
# Step 5: run across all ships/sensors and assemble the output
# ---------------------------------------------------------------------------

def simulate_passive_detections(
    trajectories: List[ShipTrajectory],
    sensors: List[Sensor],
    rotation_periods: Dict[str, float],
    noise_sigma_s: float = 0.001,
    seed: int | None = None,
) -> dict:
    """Run the peak-time finder for every (ship, sensor) pair.

    `rotation_periods` maps ship_id -> radar rotation period in seconds
    (this is the scenario's existing `radar_rotation_s` field). Ships
    missing from this dict are skipped.

    Returns a dict matching the schema in docs/radar_research.md:
        {"sensors": [...], "detections": [...]}
    """
    rng = random.Random(seed)
    detections: List[Detection] = []

    for traj in trajectories:
        p_e = rotation_periods.get(traj.ship_id)
        if not p_e:
            continue

        for sensor in sensors:
            true_times = find_peak_times(traj, sensor, p_e)
            measured_times = add_timing_noise(true_times, noise_sigma_s, rng)

            for sweep, (true_t, measured_t) in enumerate(zip(true_times, measured_times)):
                detections.append(Detection(
                    ship_id    = traj.ship_id,
                    sensor_id  = sensor.sensor_id,
                    sweep      = sweep,
                    true_t     = true_t,
                    measured_t = measured_t,
                ))

    return {
        "sensors": [asdict(s) for s in sensors],
        "detections": [asdict(d) for d in detections],
    }


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def detections_to_json(result: dict, path: str, indent: int = 2) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=indent)


def detections_to_csv(result: dict, path: str) -> None:
    """Write the flat detections table (sensor positions are not included --
    keep those in the companion JSON, or a separate sensors.csv, if needed)."""
    fieldnames = ["ship_id", "sensor_id", "sweep", "true_t", "measured_t"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result["detections"])


# ---------------------------------------------------------------------------
# Quick self-test — run with:  python core/passive_radar.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from core.trajectory import _move

    # --- Sanity check against the hand-worked example from the discussion:
    # p_e = 6s, sensor at bearing 140 deg from a STATIONARY ship
    # => expect peak time ~= (140 / 360) * 6 = 2.333s
    print("=== Hand-worked sanity check ===")

    ship_lat, ship_lon = 49.040, 8.303
    sensor_lat, sensor_lon = _move(ship_lat, ship_lon, bearing_deg=140.0, distance_m=2000.0)
    sensor = Sensor(sensor_id="TEST", lat=sensor_lat, lon=sensor_lon)

    stationary_traj = ShipTrajectory(ship_id="TestShip", mmsi=1, color="#000000")
    from core.trajectory import TrajectoryPoint
    # A ship that "doesn't move" for 30 seconds (5 rotations at p_e=6s)
    for t in range(0, 31):
        stationary_traj.points.append(
            TrajectoryPoint(t=float(t), lat=ship_lat, lon=ship_lon, heading=0.0, speed_mps=0.0)
        )

    peak_times = find_peak_times(stationary_traj, sensor, rotation_period_s=6.0)
    print(f"Expected ~2.333, 8.333, 14.333, 20.333, 26.333 ...")
    print(f"Got: {peak_times}")

    expected_first = 140.0 / 360.0 * 6.0
    assert abs(peak_times[0] - expected_first) < 0.01, "Peak time does not match hand calculation!"
    print("PASS: first peak time matches hand-worked example.\n")

    # --- Full pipeline test on a real scenario ---
    print("=== Full pipeline test ===")
    from core.trajectory import build_trajectories
    from core.regions import load_region
    from core.sensors import default_sensor_layout

    test_scenario = {
        "name": "passive_radar_test",
        "region": "rheinhafen",
        "encounter_type": "custom",
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
        ],
    }

    region = load_region("rheinhafen")
    sensors = default_sensor_layout(region)
    trajs = build_trajectories(test_scenario)
    rotation_periods = {s["ship_id"]: s["radar_rotation_s"] for s in test_scenario["ships"]}

    result = simulate_passive_detections(trajs, sensors, rotation_periods, seed=42)

    print(f"Sensors: {len(result['sensors'])}")
    print(f"Detections: {len(result['detections'])}")
    print("\nFirst 5 detections:")
    for d in result["detections"][:5]:
        print(f"  {d}")

    detections_to_json(result, "passive_detections_test.json")
    detections_to_csv(result, "passive_detections_test.csv")
    print("\nWrote passive_detections_test.json and .csv")
