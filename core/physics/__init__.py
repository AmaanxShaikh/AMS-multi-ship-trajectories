"""core/physics — MMG-based ship motion model.

Public API:
    from core.physics import build_trajectory_physics, scenario_with_physics, EnvParams
"""
from core.physics.mmg_model import ShipParams, EnvParams
from core.physics.pipeline import build_trajectory_physics, scenario_with_physics

__all__ = [
    "ShipParams",
    "EnvParams",
    "build_trajectory_physics",
    "scenario_with_physics",
]