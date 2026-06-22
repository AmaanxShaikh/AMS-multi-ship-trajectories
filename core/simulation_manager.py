"""Multi-ship simulation orchestrator.

Walks all ships' pre-computed trajectories (from core.physics.scenario_with_physics)
on a shared simulation clock, detects encounter events per timestep, and yields
synchronised snapshots for live UI playback.

Public API:
    SimulationManager(result_dict, dt=1.0)
        .step()      -> one snapshot dict {time, ships, events}
        .run()       -> generator of snapshot dicts
        .all_events  -> cumulative list of detected encounters
        .is_done()   -> True when every ship has reached its final point
"""

from __future__ import annotations

import copy
from typing import Dict, Generator, List, Tuple

from core.physics.coordinate_utils import geodesic_distance


# ---------------------------------------------------------------------
# Encounter detection
# ---------------------------------------------------------------------

CPA_THRESHOLD_M = 500.0     # ships closer than this trigger an encounter check
HEAD_ON_DIFF    = 150.0     # heading diff > this => head-on
CROSSING_DIFF   = 30.0      # heading diff > this (and <= HEAD_ON_DIFF) => crossing


def _distance(a: dict, b: dict) -> float:
    return geodesic_distance((a["lat"], a["lon"]), (b["lat"], b["lon"]))


def _relative_heading(h1: float, h2: float) -> float:
    diff = abs(h1 - h2) % 360
    return min(diff, 360 - diff)


def detect_encounter(
    ship_states: List[dict],
    cpa_threshold_m: float = CPA_THRESHOLD_M,
) -> List[dict]:
    """Classify pairwise encounters at a single timestep.

    Categories:
      head_on    — opposing headings within ``CPA_THRESHOLD_M``
      crossing   — heading diff between 30° and 150°
      overtaking — same direction, faster ship behind slower one
      following  — same direction, no speed advantage
    """
    events: List[dict] = []
    for i in range(len(ship_states)):
        for j in range(i + 1, len(ship_states)):
            a, b = ship_states[i], ship_states[j]
            dist = _distance(a, b)
            if dist >= cpa_threshold_m:
                continue

            hdg_diff = _relative_heading(a["heading"], b["heading"])
            if hdg_diff > HEAD_ON_DIFF:
                kind = "head_on"
            elif hdg_diff > CROSSING_DIFF:
                kind = "crossing"
            else:
                if a["speed_mps"] > b["speed_mps"]:
                    kind = "overtaking"
                else:
                    kind = "following"

            events.append({
                "type":       kind,
                "ships":      [a["ship_id"], b["ship_id"]],
                "distance_m": round(dist, 1),
                "hdg_diff":   round(hdg_diff, 1),
            })
    return events


# ---------------------------------------------------------------------
# SimulationManager
# ---------------------------------------------------------------------

class SimulationManager:
    """Synchronise multiple pre-computed ship trajectories on a shared clock.

    Input is the dict returned by ``core.physics.scenario_with_physics()`` —
    each ship already has a full ``trajectory`` list.  The manager walks all
    trajectories in lockstep, one entry per ``step()`` call, and runs encounter
    detection on the joint snapshot.
    """

    def __init__(
        self,
        result_dict: dict,
        dt: float = 1.0,
        cpa_threshold_m: float = CPA_THRESHOLD_M,
    ):
        self.dt = float(dt)
        self.cpa_threshold_m = float(cpa_threshold_m)
        self.time = 0.0
        self.all_events: List[dict] = []

        self.ships: List[Dict] = []
        for s in result_dict.get("ships", []):
            self.ships.append({
                "ship_id":      s["ship_id"],
                "color":        s.get("color", "#1f77b4"),
                "trajectory":   s.get("trajectory", []),
                "start_time_s": float(s.get("start_time_s", 0.0)),
            })
        # Each ship's "alive" window on the shared clock.
        for s in self.ships:
            traj_dur = (len(s["trajectory"]) - 1) * self.dt if s["trajectory"] else 0.0
            s["end_time_s"] = s["start_time_s"] + traj_dur
        self.max_steps = max(
            (len(s["trajectory"]) for s in self.ships),
            default=0,
        )

    # -----------------------------------------------------------------

    def _current_snapshot(self) -> List[dict]:
        """Only includes ships that are 'alive' at the current shared-clock time.

        A ship is alive between its ``start_time_s`` and the end of its own
        trajectory (``start_time_s + trajectory_duration``). Outside that
        window it is invisible to the encounter detector, so two paths that
        cross on the map are NOT flagged unless both ships are actually
        present at the same moment.
        """
        snap: List[dict] = []
        for ship in self.ships:
            traj = ship["trajectory"]
            if not traj:
                continue
            if self.time < ship["start_time_s"]:
                continue                                   # hasn't entered yet
            if self.time > ship["end_time_s"]:
                continue                                   # already finished
            local_t = self.time - ship["start_time_s"]
            idx = min(int(round(local_t / self.dt)), len(traj) - 1)
            p   = traj[idx]
            snap.append({
                "ship_id":   ship["ship_id"],
                "color":     ship["color"],
                "lat":       p["lat"],
                "lon":       p["lon"],
                "heading":   p["heading"],
                "speed_mps": p["speed_mps"],
                "t":         self.time,
            })
        return snap

    # -----------------------------------------------------------------

    def step(self) -> dict:
        """Advance the simulation by ``dt`` and return one snapshot."""
        snap = self._current_snapshot()
        events = detect_encounter(snap, self.cpa_threshold_m)

        # Deduplicate against the most recent identical event for the same pair
        for ev in events:
            pair_key = tuple(sorted(ev["ships"]))
            last = next(
                (e for e in reversed(self.all_events)
                 if tuple(sorted(e["ships"])) == pair_key),
                None,
            )
            if last is None or last["type"] != ev["type"]:
                ev_record = dict(ev)
                ev_record["t"] = round(self.time, 2)
                self.all_events.append(ev_record)

        self.time += self.dt
        return {"time": round(self.time, 2), "ships": snap, "events": events}

    # -----------------------------------------------------------------

    def is_done(self) -> bool:
        # Done when every ship has finished its own trajectory.
        return all(
            self.time > s["end_time_s"]
            for s in self.ships
            if s["trajectory"]
        )

    # -----------------------------------------------------------------

    def run(self) -> Generator[dict, None, None]:
        """Yield a snapshot per simulated timestep until every ship is finished."""
        while not self.is_done():
            yield self.step()
        # one final snapshot at the terminal state
        yield self.step()

    # -----------------------------------------------------------------

    def summary(self) -> dict:
        """Return a JSON-serialisable summary of the run."""
        by_type: Dict[str, int] = {}
        for ev in self.all_events:
            by_type[ev["type"]] = by_type.get(ev["type"], 0) + 1
        return {
            "duration_s":   round(self.max_steps * self.dt, 2),
            "ship_count":   len(self.ships),
            "events_total": len(self.all_events),
            "events_by_type": by_type,
            "events":       copy.deepcopy(self.all_events),
        }


# ---------------------------------------------------------------------
# Convenience: one-shot encounter analysis without the streaming API
# ---------------------------------------------------------------------

def analyse_encounters(
    result_dict: dict,
    dt: float = 1.0,
    cpa_threshold_m: float = CPA_THRESHOLD_M,
) -> dict:
    """Run a full multi-ship simulation and return the summary dict."""
    mgr = SimulationManager(result_dict, dt=dt, cpa_threshold_m=cpa_threshold_m)
    for _ in mgr.run():
        pass
    return mgr.summary()


# ---------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------

if __name__ == "__main__":
    from core.physics import scenario_with_physics, EnvParams

    test_scenario = {
        "name": "manager_test",
        "region": "rheinhafen",
        "encounter_type": "crossing",
        "ships": [
            {
                "ship_id": "Ship_1", "mmsi": 211000001, "color": "#1f77b4",
                "length_m": 100.0, "beam_m": 15.0,
                "initial_speed_mps": 4.0, "initial_heading_deg": 0.0,
                "radar_rotation_s": 6.0,
                "waypoints": [
                    {"lat": 49.020, "lon": 8.295},
                    {"lat": 49.060, "lon": 8.305},
                ],
            },
            {
                "ship_id": "Ship_2", "mmsi": 211000002, "color": "#d62728",
                "length_m": 80.0, "beam_m": 12.0,
                "initial_speed_mps": 3.5, "initial_heading_deg": 0.0,
                "radar_rotation_s": 6.0,
                "waypoints": [
                    {"lat": 49.040, "lon": 8.270},
                    {"lat": 49.040, "lon": 8.330},
                ],
            },
        ],
    }

    result  = scenario_with_physics(test_scenario, env_params=EnvParams(),
                                    dt=1.0, use_live_wind=False)
    summary = analyse_encounters(result, dt=1.0)
    print(f"\nDuration   : {summary['duration_s']} s")
    print(f"Ships      : {summary['ship_count']}")
    print(f"Encounters : {summary['events_total']}")
    print(f"By type    : {summary['events_by_type']}")
    for ev in summary["events"][:10]:
        print(f"  t={ev['t']:>6.1f}s  {ev['type']:<10s}  "
              f"{ev['ships']}  d={ev['distance_m']:.0f}m")
