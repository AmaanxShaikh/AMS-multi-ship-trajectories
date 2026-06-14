from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from core.physics.mmg_model import ShipParams, EnvParams, _ShipState, step
from core.physics.coordinate_utils import geodesic_distance


# ---------------------------------------------------------------------
# Encounter detection helpers
# ---------------------------------------------------------------------

def _distance(a: dict, b: dict) -> float:
    return geodesic_distance(
        (a["lat"], a["lon"]),
        (b["lat"], b["lon"])
    )


def _relative_heading(h1: float, h2: float) -> float:
    diff = abs(h1 - h2) % 360
    return min(diff, 360 - diff)


def detect_encounter(ship_states: List[dict], cpa_threshold_m: float = 500):
    """
    Detect simple encounter situations:
      - crossing
      - head-on
      - overtaking (basic heuristic)
    """

    events = []

    for i in range(len(ship_states)):
        for j in range(i + 1, len(ship_states)):

            a = ship_states[i]
            b = ship_states[j]

            dist = _distance(a, b)
            hdg_diff = _relative_heading(a["heading"], b["heading"])

            if dist < cpa_threshold_m:

                if hdg_diff > 150:
                    event = "head_on"
                elif hdg_diff > 30:
                    event = "crossing"
                else:
                    # same direction + close distance
                    if a["speed_mps"] > b["speed_mps"]:
                        event = "overtaking"
                    else:
                        event = "following"

                events.append({
                    "type": event,
                    "ships": [a["ship_id"], b["ship_id"]],
                    "distance_m": dist
                })

    return events


# ---------------------------------------------------------------------
# Simulation Manager
# ---------------------------------------------------------------------

class SimulationManager:
    """
    Central orchestrator:
    - synchronizes all ships in time
    - calls physics step (or fallback trajectory)
    - produces global simulation snapshots
    """

    def __init__(
        self,
        scenario: dict,
        env_params: Optional[EnvParams] = None,
        dt: float = 1.0,
        use_physics: bool = True,
    ):
        self.scenario = copy.deepcopy(scenario)
        self.env = env_params or EnvParams()
        self.dt = dt
        self.use_physics = use_physics

        self.time = 0.0
        self.ships = self._init_ships()

    # ---------------------------------------------------------

    def _init_ships(self):
        ships = []

        for s in self.scenario["ships"]:
            wp = [(w["lat"], w["lon"]) for w in s["waypoints"]]

            state = {
                "ship_id": s["ship_id"],
                "mmsi": s["mmsi"],
                "lat": wp[0][0],
                "lon": wp[0][1],
                "heading": s.get("initial_heading_deg", 0.0),
                "speed_mps": s.get("initial_speed_mps", 0.0),
                "waypoints": wp,
                "wp_index": 1,
                "color": s.get("color", "#1f77b4"),
            }

            ships.append(state)

        return ships

    # ---------------------------------------------------------

    def _update_kinematic(self, ship):
        """Simple constant velocity fallback (your trajectory model)."""

        if ship["wp_index"] >= len(ship["waypoints"]):
            return

        lat, lon = ship["lat"], ship["lon"]
        tgt_lat, tgt_lon = ship["waypoints"][ship["wp_index"]]

        dist = geodesic_distance((lat, lon), (tgt_lat, tgt_lon))

        if dist < 10:  # switch waypoint
            ship["wp_index"] += 1
            return

        # simple movement approximation (not full geodesic step)
        step_size = ship["speed_mps"] * self.dt / 111000.0

        ship["lat"] += step_size * (tgt_lat - lat)
        ship["lon"] += step_size * (tgt_lon - lon)

    # ---------------------------------------------------------

    def _update_physics(self, ship):
        """Call MMG model step (simplified wrapper)."""

        # NOTE: you already implemented full MMG in pipeline.py
        # here we assume pipeline already advances state elsewhere

        # fallback: treat same as kinematic for now
        self._update_kinematic(ship)

    # ---------------------------------------------------------

    def step(self):
        """
        Advance full simulation by one timestep.
        ALL ships updated at same time → synchronization achieved here.
        """

        self.time += self.dt

        snapshot = []

        for ship in self.ships:

            if self.use_physics:
                self._update_physics(ship)
            else:
                self._update_kinematic(ship)

            snapshot.append({
                "ship_id": ship["ship_id"],
                "lat": ship["lat"],
                "lon": ship["lon"],
                "heading": ship["heading"],
                "speed_mps": ship["speed_mps"],
                "t": self.time
            })

        events = detect_encounter(snapshot)

        return {
            "time": self.time,
            "ships": snapshot,
            "events": events
        }

    # ---------------------------------------------------------

    def run(self, max_steps: int = 1000):
        """
        Generator for UI / Streamlit animation.
        """

        for _ in range(max_steps):
            yield self.step()