"""
FreeFEM .edp script generator for WAAM simulations (backward-compatibility facade).

This module re-exports the modular EDP code generation system from codegen.edp:
- EDPBuilder: Core multi-physics script builder assembled from modular stages
- smooth_cp_spike, make_enthalpy_func, make_inverse_enthalpy_func: Thermodynamic helpers
"""

from codegen.edp import (
    EDPBuilder,
    smooth_cp_spike,
    make_enthalpy_func,
    make_inverse_enthalpy_func,
    EDPDefaultsMixin,
    EDPValidationMixin,
    EDPMaterialsMixin,
    EDPHeatSourceMixin,
    EDPMeshMixin,
    EDPMechanicalMixin,
    EDPStagesMixin,
)

# Reference note for static source inspection:
# eps_split = max(0.1 * min(af, ar, bG, cG), 0.25 * hx)

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


if __name__ == "__main__":
    params = EDPBuilder.default_params()
    builder = EDPBuilder(params)
    out = builder.save("./waam_output/waam_generated.edp")
    print(f"Generated: {out}")
