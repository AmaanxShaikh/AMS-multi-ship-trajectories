"""Scenario data model.

The UI collects user inputs into these dataclasses, and exports them as a
scenario JSON. No simulation is performed here — running the physics is a
later milestone owned by the backend (supervisor will guide that integration).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List
import json


@dataclass
class Waypoint:
    """A single (latitude, longitude) point on a ship's intended route."""

    lat: float
    lon: float


@dataclass
class Ship:
    """One ship in a scenario, as configured by the user.

    Only the fields a user can actually set in the UI live here. Hydrodynamic
    coefficients, rudder gains etc. belong to the physics backend.
    """

    ship_id: str
    mmsi: int
    length_m: float = 100.0
    beam_m: float = 15.0
    draught_m: float = 5.0
    initial_speed_mps: float = 5.0
    initial_heading_deg: float = 0.0
    waypoints: List[Waypoint] = field(default_factory=list)
    radar_rotation_s: float = 0.0     # 0 disables radar
    color: str = "#1f77b4"
    start_time_s: float = 0.0         # seconds after t=0 when this ship enters the scene


@dataclass
class Scenario:
    """A complete user-defined scenario, ready to hand off to the physics backend.

    `encounter_type` records which of the supervisor's named scenarios the user
    is building (crossing / overtaking / head-on / harbor traffic / custom). It
    is metadata only at the UI stage — the backend will use it later to set up
    the multi-ship scenario manager and synchronise updates.
    """

    name: str
    region: str                       # "rheinhafen" or "cuxhaven"
    encounter_type: str = "custom"    # crossing | overtaking | head_on | harbor_traffic | custom
    ships: List[Ship] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# Encounter scenarios the supervisor named in the kickoff (front-end picks
# one; backend will later interpret it to configure the scenario manager).
ENCOUNTER_TYPES: List[tuple[str, str, str]] = [
    ("custom",          "Custom",          "Free-form scenario — no preset constraints."),
    ("crossing",        "Crossing",        "Two ships on intersecting courses."),
    ("overtaking",      "Overtaking",      "A faster ship overtakes a slower one in the same lane."),
    ("head_on",         "Head-on",         "Two ships approaching from opposite directions."),
    ("harbor_traffic",  "Harbor traffic",  "Mixed incoming/outgoing traffic in port approaches."),
]


DEFAULT_SHIP_COLORS = [
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd",
    "#ff7f0e", "#17becf", "#e377c2", "#8c564b",
]


def next_color(index: int) -> str:
    return DEFAULT_SHIP_COLORS[index % len(DEFAULT_SHIP_COLORS)]
