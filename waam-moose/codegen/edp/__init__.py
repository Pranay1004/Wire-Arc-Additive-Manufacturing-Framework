"""
Modular FreeFEM .edp code generation package for WAAM simulations.

Provides:
- EDPBuilder: Full multi-physics script builder assembled from modular stages.
- smooth_cp_spike, make_enthalpy_func, make_inverse_enthalpy_func: Thermodynamic math helpers.
"""

from .builder_core import EDPBuilder
from .enthalpy import (
    make_enthalpy_func,
    make_inverse_enthalpy_func,
    smooth_cp_spike,
)
from .defaults import EDPDefaultsMixin
from .validation import EDPValidationMixin
from .materials import EDPMaterialsMixin
from .heat_sources import EDPHeatSourceMixin
from .mesh_setup import EDPMeshMixin
from .mechanical import EDPMechanicalMixin
from .stages import EDPStagesMixin

__all__ = [
    "EDPBuilder",
    "smooth_cp_spike",
    "make_enthalpy_func",
    "make_inverse_enthalpy_func",
    "EDPDefaultsMixin",
    "EDPValidationMixin",
    "EDPMaterialsMixin",
    "EDPHeatSourceMixin",
    "EDPMeshMixin",
    "EDPMechanicalMixin",
    "EDPStagesMixin",
]
