"""core/physics/mmg_model.py

MMG (Manoeuvring Mathematical Group) ship motion model.

Extracted and cleaned from the old physics-based model
(Trial 16 / code-with-all-forces.py). All physics equations are
identical to the original; this module just organises them cleanly
so they can be imported by the multi-ship pipeline.

3-DOF equations of motion:
  surge  u  (forward velocity, m/s)
  sway   v  (lateral velocity, m/s)
  yaw    r  (yaw rate, rad/s)

Forces included:
  • Propeller thrust   (Wageningen B-series KT quadratic fit)
  • Hull drag
  • Rudder forces      (lift + drag, ±35° limit)
  • Wind forces        (Fujiwara-style, uses live API or manual override)
  • Current forces     (drag-based, configurable)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Parameter dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ShipParams:
    """Physical parameters for one ship instance.

    Defaults match the 6 500-tonne vessel used in the old Trial 16.
    Each ship in a multi-ship scenario gets its own independent ShipParams.
    """
    # --- initial state (set per ship) ---
    initial_lat:        float = 49.020
    initial_lon:        float = 8.300
    initial_heading_deg: float = 0.0

    # --- mass / inertia ---
    mass:   float = 6_500_000.0   # kg
    Iz:     float = 4e8            # yaw moment of inertia, kg·m²

    # --- propeller ---
    D:              float = 3.0    # propeller diameter, m
    target_n_rpm:   float = 180.0  # target shaft RPM
    tp:             float = 0.15   # thrust deduction factor
    w:              float = 0.15   # wake fraction

    # --- rudder ---
    AR:  float = 15.0   # rudder area, m²
    xR:  float = 60.0   # rudder distance from CG, m

    # --- hull drag ---
    S:   float = 4000.0   # wetted surface area, m²
    CD:  float = 0.002    # hull drag coefficient

    # --- water ---
    rho_water: float = 1000.0   # kg/m³


@dataclass
class EnvParams:
    """Environmental forcing parameters (wind + current).

    These are exposed as sidebar controls in app.py so users can
    set conditions before running a simulation.
    """
    # Wind (set via sidebar or live API)
    wind_speed_mps:   float = 0.0    # m/s
    wind_dir_deg:     float = 0.0    # FROM which direction (° true N)

    # Current
    current_speed_mps: float = 0.7   # m/s  (default from Trial 16)
    current_dir_deg:   float = 200.0  # FROM which direction

    # Wind force areas / coefficients (Fujiwara-style)
    A_surge_wind: float = 75.0
    A_sway_wind:  float = 225.0
    CD_wind:      float = 0.6
    rho_air:      float = 1.225

    # Current force areas / coefficients
    A_surge_current: float = 25.0
    A_sway_current:  float = 75.0
    CD_current:      float = 0.6


# ---------------------------------------------------------------------------
# Internal mutable simulation state (one per ship per run)
# ---------------------------------------------------------------------------

class _ShipState:
    """Mutable integration state for one ship during simulation."""

    def __init__(self, params: ShipParams):
        self.rho_water = params.rho_water

        # Propeller
        self.D            = params.D
        self.target_n_rpm = params.target_n_rpm
        self.n_rpm        = 0.0
        self.n            = 0.0      # rev/s

        # Rudder
        self.AR    = params.AR
        self.xR    = params.xR
        self.delta = 0.0             # radians

        # DOF state
        self.u   = 2.0               # surge velocity, m/s
        self.v   = 0.0               # sway velocity
        self.r   = 0.0               # yaw rate, rad/s
        self.psi = math.radians(params.initial_heading_deg)

        # Position
        self.lat = params.initial_lat
        self.lon = params.initial_lon

        # Derived ship params
        self.mass = params.mass
        self.Iz   = params.Iz
        self.tp   = params.tp
        self.w    = params.w
        self.S    = params.S
        self.CD   = params.CD

        self.dt = 1.0   # time step, s


# ---------------------------------------------------------------------------
# Force functions (pure, no side effects — identical to old code)
# ---------------------------------------------------------------------------

def _calculate_J(state: _ShipState) -> float:
    denom = state.n * state.D
    if denom == 0:
        return 0.0
    return min(state.u * (1 - state.w) / denom, 5.0)


def _KT_of_J(J: float) -> float:
    a, b, c = 1.333, -0.8, -0.0667
    KT = a * J**2 + b * J + c
    if math.isnan(KT) or math.isinf(KT):
        return 0.0
    return max(0.1, min(KT, 0.4))


def propeller_force(state: _ShipState) -> float:
    """Surge propeller thrust XP (N)."""
    J  = _calculate_J(state)
    KT = _KT_of_J(J)
    TP = state.rho_water * state.n**2 * state.D**4 * KT
    return (1 - state.tp) * TP


def drag_force(state: _ShipState) -> float:
    """Hull drag force (N)."""
    return 0.5 * state.rho_water * state.S * state.CD * state.u**2


def rudder_forces(state: _ShipState) -> Tuple[float, float, float]:
    """Rudder surge XR, sway YR, yaw moment NR (N, N, N·m)."""
    delta = float(np.clip(state.delta, -math.radians(35), math.radians(35)))
    UR    = state.u

    # Lift and drag coefficients
    CL = 6.0 * delta           # lift slope 6 /rad
    CD_r = 0.02 + 2.5 * delta**2

    LR = 0.5 * state.rho_water * state.AR * UR**2 * CL
    DR = 0.5 * state.rho_water * state.AR * UR**2 * CD_r

    XR = -DR * math.cos(delta) + LR * math.sin(delta)
    YR = -DR * math.sin(delta) - LR * math.cos(delta)
    NR = YR * state.xR
    return XR, YR, NR


def wind_forces(state: _ShipState,
                env: EnvParams) -> Tuple[float, float, float]:
    """Wind surge Xw, sway Yw, yaw Nw (N, N, N·m)."""
    vw      = env.wind_speed_mps
    theta_r = math.radians((env.wind_dir_deg + 180) % 360)

    uw      = vw * math.cos(theta_r - state.psi)
    vw_side = vw * math.sin(theta_r - state.psi)

    Xw = 0.5 * env.rho_air * env.CD_wind * env.A_surge_wind * uw      * abs(uw)
    Yw = 0.5 * env.rho_air * env.CD_wind * env.A_sway_wind  * vw_side * abs(vw_side)
    Nw = Yw * state.xR * 0.3
    return Xw, Yw, Nw


def current_forces(state: _ShipState,
                   env: EnvParams) -> Tuple[float, float, float]:
    """Current surge Xc, sway Yc, yaw Nc (N, N, N·m)."""
    Uc      = env.current_speed_mps
    theta_r = math.radians((env.current_dir_deg + 180) % 360)

    uc_s = Uc * math.cos(theta_r - state.psi)
    uc_v = Uc * math.sin(theta_r - state.psi)

    rho  = state.rho_water
    Xc = 0.5 * rho * env.CD_current * env.A_surge_current * uc_s * abs(uc_s)
    Yc = 0.5 * rho * env.CD_current * env.A_sway_current  * uc_v * abs(uc_v)
    Nc = Yc * state.xR * 0.3
    return Xc, Yc, Nc


# ---------------------------------------------------------------------------
# One integration step
# ---------------------------------------------------------------------------

def step(state: _ShipState,
         env: EnvParams,
         rudder_angle_deg: float,
         target_n_rpm: float) -> None:
    """Advance state by one dt using the full MMG equations."""
    state.n_rpm = target_n_rpm
    state.n     = state.n_rpm / 60.0
    state.delta = math.radians(rudder_angle_deg)

    Fp          = propeller_force(state)
    Fd          = drag_force(state)
    XR, YR, NR = rudder_forces(state)
    Xw, Yw, Nw = wind_forces(state, env)
    Xc, Yc, Nc = current_forces(state, env)

    # Surge
    a_surge  = (Fp - Fd + XR + Xw + Xc) / state.mass
    state.u  = float(np.clip(state.u + a_surge * state.dt, 0.0, 12.0))

    # Sway
    a_sway  = (YR + Yw + Yc) / state.mass
    state.v += a_sway * state.dt

    # Yaw
    r_dot    = (NR + Nw + Nc) / state.Iz
    state.r += r_dot * state.dt
    state.r  = float(np.clip(state.r, -0.4, 0.4))
    state.r *= 0.85                        # damping (from Trial 16)
    state.psi += state.r * state.dt

    # Position update (geodesic, matches old code)
    from core.physics.coordinate_utils import move_geodesic
    dx = (state.u * math.cos(state.psi) - state.v * math.sin(state.psi)) * state.dt
    dy = (state.u * math.sin(state.psi) + state.v * math.cos(state.psi)) * state.dt
    dist    = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dx, dy))
    state.lat, state.lon = move_geodesic(state.lat, state.lon, bearing, dist)