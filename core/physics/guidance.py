"""core/physics/guidance.py

Line-of-Sight (LOS) path-following controller and waypoint switching logic.

Extracted from the old simulate_motion() function (Trial 16).
Separated here so it can be tested and tuned independently.

The controller computes a rudder angle at each step by combining:
  1. Heading error  — how far the ship's heading deviates from the
                      bearing to the current reference waypoint
  2. Cross-track error (CTE) — lateral distance from the path segment

Both are combined as:
    rudder_angle = (-heading_error + cte_gain * cte) / k

with dynamic clamping based on current speed (from Trial 16).
"""

from __future__ import annotations

import math
from typing import List, Tuple

from core.physics.coordinate_utils import (
    latlon_to_xy,
    bearing as _bearing,
    geodesic_distance,
)

# ---------------------------------------------------------------------------
# Control gains (matching Trial 16 — best performing version)
# ---------------------------------------------------------------------------

K             = 5       # rudder gain divisor (lower = more aggressive)
CTE_GAIN      = 1.5     # cross-track correction weight
MAX_RUDDER    = 35.0    # degrees
RAMP_SECS     = 60      # propeller ramp-up duration, seconds
GOAL_DIST_M   = 20.0    # stop when within this many metres of goal
WP_SWITCH_M   = 30.0    # switch to next waypoint within this distance


# ---------------------------------------------------------------------------
# Cross-track error
# ---------------------------------------------------------------------------

def cross_track_error(pos: Tuple[float, float],
                      seg_a: Tuple[float, float],
                      seg_b: Tuple[float, float]) -> float:
    """Signed CTE in metres from pos to the line segment seg_a→seg_b.

    Positive = left of the track, negative = right.
    Matches the old implementation exactly.
    """
    px, py  = latlon_to_xy(*pos)
    x1, y1  = latlon_to_xy(*seg_a)
    x2, y2  = latlon_to_xy(*seg_b)

    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return 0.0

    u     = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    proj_x = x1 + u * dx
    proj_y = y1 + u * dy
    cte    = math.hypot(px - proj_x, py - proj_y)
    cross  = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    return math.copysign(cte, cross)


# ---------------------------------------------------------------------------
# Heading error
# ---------------------------------------------------------------------------

def heading_error(current_lat: float,
                  current_lon: float,
                  current_psi_rad: float,
                  ref_lat: float,
                  ref_lon: float) -> float:
    """Signed heading error in degrees (positive = need to turn right)."""
    brg           = _bearing((current_lat, current_lon), (ref_lat, ref_lon))
    required_hdg  = (90 - brg) % 360
    current_hdg   = math.degrees(current_psi_rad) % 360
    err           = required_hdg - current_hdg
    if err >  180: err -= 360
    if err < -180: err += 360
    return err


# ---------------------------------------------------------------------------
# Rudder command
# ---------------------------------------------------------------------------

def compute_rudder_angle(hdg_err: float,
                         cte: float,
                         speed_mps: float) -> float:
    """Compute rudder angle in degrees from heading error and CTE.

    Matches the rudder controller in Trial 16 exactly.
    """
    cte_eff     = cte / max(1.0, speed_mps)
    rudder      = (-hdg_err + CTE_GAIN * cte_eff) / K
    rudder      = max(-MAX_RUDDER, min(MAX_RUDDER, rudder))
    dyn_limit   = max(7.0, min(35.0, 7.0 + 12.0 / max(speed_mps, 0.1)))
    return max(-dyn_limit, min(dyn_limit, rudder))


# ---------------------------------------------------------------------------
# Propeller ramp-up target RPM
# ---------------------------------------------------------------------------

def target_rpm(elapsed_s: float, target_n_rpm: float) -> float:
    """Linearly ramp propeller from 0 → target over RAMP_SECS."""
    if elapsed_s <= RAMP_SECS:
        return target_n_rpm * elapsed_s / RAMP_SECS
    return target_n_rpm


# ---------------------------------------------------------------------------
# Waypoint switching
# ---------------------------------------------------------------------------

def should_switch_waypoint(pos: Tuple[float, float],
                            ref: Tuple[float, float],
                            ref_idx: int,
                            path_len: int) -> bool:
    """Return True if the ship should advance to the next waypoint."""
    if ref_idx + 1 >= path_len:
        return False
    return geodesic_distance(pos, ref) < WP_SWITCH_M


# ---------------------------------------------------------------------------
# Thrust factor (reduce thrust during hard turns — from Trial 16)
# ---------------------------------------------------------------------------

def thrust_factor(rudder_angle_deg: float) -> float:
    return 0.5 if abs(rudder_angle_deg) > 20 else 1.0