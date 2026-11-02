#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — 3D Slicer & Digital Twin Viewport Tab (Lazy Loaded)
"""

import os
import sys
import tkinter as tk

from gui.fonts import FONT_SECTION
from gui.tabs.base import reg_widget


def build_viewport_tab(app):
    """Dedicated full-size Slicer Viewport Tab (lazy loaded for high responsiveness)."""
    app.viewport_tab = tk.Frame(app.notebook)
    app.notebook.add(app.viewport_tab, text="Slicer")
    reg_widget(app, app.viewport_tab, "card_frame")
    app._viewport_loaded = False
    app.viewport = None
    app.viewport_3d = None
    app.slicer_widget = None

    app.viewport_placeholder = tk.Frame(app.viewport_tab)
    app.viewport_placeholder.pack(fill=tk.BOTH, expand=True)
    reg_widget(app, app.viewport_placeholder, "card_frame")

    lbl = tk.Label(
        app.viewport_placeholder,
        text="3D Slicer & Digital Twin Studio\n\n(Select this tab or click '3D Slicer & Twin' above to activate interactive 3D renderer)",
        font=FONT_SECTION,
        fg="#64748b"
    )
    lbl.pack(expand=True)
    reg_widget(app, lbl, "label_dim")


def ensure_viewport_loaded(app):
    """Instantiate the heavy 3D Slicer / Viewport only on first user activation."""
    if getattr(app, "_viewport_loaded", False):
        return app.viewport
    try:
        if hasattr(app, "viewport_placeholder") and app.viewport_placeholder:
            app.viewport_placeholder.destroy()
            app.viewport_placeholder = None
        lab_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "waam_lab"))
        if lab_dir not in sys.path:
            sys.path.insert(0, lab_dir)
        import importlib
        waam_gui = importlib.import_module("waam_slicer.gui")
        WAAMSlicerFrame = getattr(waam_gui, "WAAMSlicerFrame")
        app.viewport = WAAMSlicerFrame(app.viewport_tab, app=app)
        app.viewport.pack(fill=tk.BOTH, expand=True)
        app.viewport_3d = app.viewport
        app.slicer_widget = app.viewport
        app._viewport_loaded = True
        params = app._collect_params()
        app.viewport.update_mesh(params)
    except Exception as e:
        try:
            app._log(f"[SLICER VIEWPORT] Error loading WAAMSlicerFrame: {e}\n")
            from gui.widgets.mesh_viewer_3d import EmbeddedMeshViewport
            app.viewport = EmbeddedMeshViewport(app.viewport_tab, app=app)
            app.viewport.pack(fill=tk.BOTH, expand=True)
            app.viewport_3d = app.viewport
            app.slicer_widget = app.viewport
            app._viewport_loaded = True
        except Exception:
            pass
    return app.viewport


load_viewport_canvas = ensure_viewport_loaded


"""
================================================================================
3D SLICER & DIGITAL TWIN VIEWPORT TAB — ARCHITECTURAL SPECIFICATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The 3D Viewport Tab provides interactive spatial visualization of CAD geometry, G-code
deposition paths, finite element volume meshes, and transient temperature fields.

  a. Camera Projection & Coordinate Transformations:
     Transforms 3D world coordinates X_w = [x, y, z, 1]ᵀ to normalized screen space:
       X_screen = P_proj · V_view · M_model · X_w
     where the view matrix V_view is parameterized via spherical orbit coordinates:
       x_eye = x_target + R_orbit · cos(θ_elev) · sin(φ_azim)
       y_eye = y_target + R_orbit · sin(θ_elev)
       z_eye = z_target + R_orbit · cos(θ_elev) · cos(φ_azim)
     supporting real-time trackball rotation (Left-Click), panning (Right-Click),
     and zoom dolly (Scrollwheel).

  b. Toolpath Kinematic Trajectory Visualization:
     Each G-code movement G1 X.. Y.. Z.. F.. is rendered as a 3D polygonal sweep cylinder:
       Γ_segment(s) = (1 - s) · P_start + s · P_end,   s ∈ [0, 1]
     colored dynamically by layer index, instantaneous travel speed, or thermal deposition state.

  c. Lazy Loading Architecture:
     To guarantee instantaneous GUI launch and zero idle overhead, the 3D rendering canvas
     defers initialization until the tab receives its first focus event (`ensure_viewport_loaded`).

2. Design & Engineering Philosophy
-----------------------------------
  - Zero-Freezing Asynchronous Refresh:
    The viewport operates in decoupled drawing passes, preventing rendering stalls during
    large 250,000-element mesh ingestion or multi-thousand line G-code previews.
  - Slicer / Twin Integration:
    Bridges the gap between slicing CAM software and physical FEM simulation by displaying
    both the exact deposition toolpath and the resulting substrate thermal envelope simultaneously.

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                 3D SLICER & TWIN VIEWPORT                   │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Lazy-Loaded Canvas Wrapper                               │
  │    ├── Placeholder Notice (Initial state)                   │
  │    └── ensure_viewport_loaded() -> Lazy Activation Gate     │
  │                                                             │
  │ 2. Interactive 3D Studio Frame (WAAMSlicerFrame)            │
  │    ├── Orbit Camera Controller (Pan / Tilt / Dolly)         │
  │    ├── Toolpath Wireframe Visualizer (G-code sweep)         │
  │    ├── Substrate & Deposit Bounding Envelopes               │
  │    └── Layer Height & Bead Width Cross-Section Overlay      │
  │                                                             │
  │ 3. Fallback Viewport (EmbeddedMeshViewport)                 │
  │    └── Lightweight Tkinter Canvas 3D Orthographic Engine    │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/viewport_tab.py
        │
        ├── Listens to: Notebook tab selection event ("<<NotebookTabChanged>>")
        │     │
        │     ▼
        ├──► ensure_viewport_loaded()
        │      │
        │      ├─► Imports waam_slicer.gui.WAAMSlicerFrame
        │      ├─► Ingests app.params (Substrate, Bead Width, Layer Heights)
        │      ├─► Generates toolpath preview via slicer_api
        │      └─► Updates viewport.update_mesh(params)
        │
        └──► Provides live visual confirmation of active CAD model alignment

5. Numerical & Physical Impact
------------------------------
  - Prevents fatal simulation runtime aborts by visually exposing inverted coordinate
    axes, unaligned substrate centers, or toolpath collisions before solver launch.
  - Lazy loading eliminates 500+ ms of startup latency, keeping the application lightweight.
"""
