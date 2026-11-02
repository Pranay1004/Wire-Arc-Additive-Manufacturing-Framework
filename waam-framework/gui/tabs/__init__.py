#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Tab Modules
Exports all modular tab builders for WAAMApp.
"""

from gui.tabs.viewport_tab import build_viewport_tab, load_viewport_canvas
from gui.tabs.default_case_tab import build_default_case_tab
from gui.tabs.sim_log_tab import build_sim_log_tab
from gui.tabs.geometry_tab import build_geometry_tab
from gui.tabs.process_tab import build_process_tab, update_source_params
from gui.tabs.material_tab import build_material_tab
from gui.tabs.mesh_cad_tab import build_mesh_cad_tab
from gui.tabs.physics_tab import build_physics_tab
from gui.tabs.solver_tab import build_solver_tab
from gui.tabs.openfoam_tab import build_openfoam_tab
from gui.tabs.parametric_tab import build_parametric_tab
from gui.tabs.ultrasonic_tab import build_ultrasonic_tab

__all__ = [
    "build_viewport_tab",
    "load_viewport_canvas",
    "build_default_case_tab",
    "build_sim_log_tab",
    "build_geometry_tab",
    "build_process_tab",
    "update_source_params",
    "build_material_tab",
    "build_mesh_cad_tab",
    "build_physics_tab",
    "build_solver_tab",
    "build_openfoam_tab",
    "build_parametric_tab",
    "build_ultrasonic_tab",
]
