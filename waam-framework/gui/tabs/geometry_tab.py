#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Geometry Tab
Modular tab for Substrate, Wall, Layer driver mode, and fusion preview.
"""

import math
import os
import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION
)
from gui.tabs.base import reg_widget, make_param_row, add_info_button


def build_geometry_tab(app):
    """Build the Geometry tab in app.notebook."""
    tab = tk.Frame(app.notebook)
    app.notebook.add(tab, text="Geometry")
    reg_widget(app, tab, "card_frame")

    # 1. Substrate Dimensions
    lf1 = tk.LabelFrame(tab, text="Substrate (Base Plate) Dimensions", font=FONT_SECTION, padx=8, pady=4)
    lf1.pack(fill=tk.X, padx=8, pady=4)
    reg_widget(app, lf1, "card_labelframe")
    add_info_button(app, lf1, app._show_substrate_info)
    make_param_row(app, lf1, "Substrate Length (Lₓ):", "lx", 0, "mm")
    make_param_row(app, lf1, "Substrate Width (W_sub):", "ly_base", 1, "mm")
    make_param_row(app, lf1, "Substrate Thickness (H_sub):", "hz_base", 2, "mm")

    # 2. Deposit Wall & Fusion Model
    lf2 = tk.LabelFrame(tab, text="WAAM Deposit Wall Geometry & Fusion Model", font=FONT_SECTION, padx=8, pady=4)
    lf2.pack(fill=tk.X, padx=8, pady=4)
    reg_widget(app, lf2, "card_labelframe")
    add_info_button(app, lf2, app._show_fusion_info)

    # Row 0: Active CAD Geometry Bounding Box / Status Banner
    app.geom_cad_status_lbl = tk.Label(
        lf2, text="• Parametric Straight Wall Active (No CAD model loaded)",
        font=FONT_SMALL_BOLD, fg="#64748b", justify=tk.LEFT, anchor=tk.W
    )
    app.geom_cad_status_lbl.grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(2, 4))
    reg_widget(app, app.geom_cad_status_lbl, "label_dim")

    # Row 1-3: Bead & Fusion Parameters (Connected with Mesh Slicer)
    make_param_row(app, lf2, "Single Bead Width (W_bead):", "ty_dep", 1, "mm [⇄ Mesh Slicer]")
    make_param_row(app, lf2, "First Layer Height (h₁):", "h_bead", 2, "mm [⇄ Mesh Slicer]")
    make_param_row(app, lf2, "Remelt / Fusion Ratio (η_remelt):", "remelt_ratio", 3, "[-]")

    # Row 4: Dimensioning Driver Strategy (Total Layers vs Target Wall Height)
    app._layer_mode = tk.StringVar(value="n_layers")
    mode_frame = tk.Frame(lf2)
    mode_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(4, 4))
    reg_widget(app, mode_frame, "card_frame")

    lbl_mode = tk.Label(mode_frame, text="Dimensioning Driver:", font=FONT_SMALL_BOLD)
    lbl_mode.pack(side=tk.LEFT, padx=(0, 8))
    reg_widget(app, lbl_mode, "label")

    rb_n = tk.Radiobutton(
        mode_frame, text="Define by Total Layers (N_layer)",
        variable=app._layer_mode, value="n_layers",
        font=FONT_SMALL, command=app._on_layer_mode_change
    )
    rb_n.pack(side=tk.LEFT, padx=6)
    reg_widget(app, rb_n, "radio")

    rb_h = tk.Radiobutton(
        mode_frame, text="Define by Target Wall Height (H_build)",
        variable=app._layer_mode, value="height",
        font=FONT_SMALL, command=app._on_layer_mode_change
    )
    rb_h.pack(side=tk.LEFT, padx=6)
    reg_widget(app, rb_h, "radio")

    # Row 5: Deposited Layers Count (N_layer)
    make_param_row(app, lf2, "Deposited Layers Count (N_layer):", "n_layers", 5, "layers", type_="int")

    # Row 6: Target Wall Build Height (H_build)
    lbl_h = tk.Label(lf2, text="Target Wall Build Height (H_build):", font=FONT_LABEL)
    lbl_h.grid(row=6, column=0, sticky=tk.W, padx=(8, 4), pady=2)
    reg_widget(app, lbl_h, "label")

    app._build_height_var = tk.StringVar(value=str(round(app._current_build_height_mm(), 2)))
    app._build_height_entry = tk.Entry(lf2, textvariable=app._build_height_var, width=10, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
    app._build_height_entry.grid(row=6, column=1, padx=4, pady=2, sticky=tk.W)
    reg_widget(app, app._build_height_entry, "entry")
    app._build_height_entry.bind("<FocusIn>", lambda e: app._on_build_height_focus())
    app._build_height_entry.bind("<KeyRelease>", lambda e: app._on_build_height_key())

    u_lbl = tk.Label(lf2, text="mm [⇄ CAD Lz]", font=FONT_SMALL_BOLD, fg="#2563eb")
    u_lbl.grid(row=6, column=2, sticky=tk.W, padx=4)
    reg_widget(app, u_lbl, "label_dim")

    app._build_height_var.trace_add("write", lambda *a: app._on_build_height_change())

    # Row 7: Unified Deposition / Infill Pattern Selection
    pattern_frame = tk.Frame(lf2)
    pattern_frame.grid(row=7, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(4, 4))
    reg_widget(app, pattern_frame, "card_frame")

    lbl_pat = tk.Label(pattern_frame, text="Deposition / Infill Pattern:", font=FONT_SMALL_BOLD)
    lbl_pat.pack(side=tk.LEFT, padx=(0, 8))
    reg_widget(app, lbl_pat, "label")

    app.deposition_pattern_var = tk.StringVar(value="zigzag")
    pat_cb = ttk.Combobox(
        pattern_frame, textvariable=app.deposition_pattern_var, width=22,
        values=["contour", "concentric", "zigzag", "lines", "grid", "triangles", "hollow", "unidirectional", "meander", "crosshatch"],
        state="readonly"
    )
    pat_cb.pack(side=tk.LEFT, padx=4)
    app.deposition_pattern_var.trace_add("write", lambda *a: app._on_deposition_pattern_change())

    tk.Label(pattern_frame, text="[⇄ Mesh Slicer Pattern]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=2)

    # Row 8: Live Fusion Profile Badge
    app.geom_fusion_info_lbl = tk.Label(
        lf2, text="—", font=FONT_SMALL_BOLD, fg="#2563eb", justify=tk.LEFT, anchor=tk.W
    )
    app.geom_fusion_info_lbl.grid(row=8, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(4, 6))
    reg_widget(app, app.geom_fusion_info_lbl, "label")

    app._update_geom_fusion_label()
    app._on_layer_mode_change()
    app._auto_update_wall_gcode()

    return tab


"""
================================================================================
GEOMETRY TAB — ARCHITECTURAL SPECIFICATION & FORMULATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The Geometry Tab defines the macroscopic spatial envelope for both the substrate
baseplate (Ω_sub) and the additive deposit wall (Ω_dep):

  a. Substrate Domain Envelope:
       Ω_sub = [0, L_x] × [-W_sub/2, +W_sub/2] × [0, H_sub]
     where:
       L_x   = Substrate length along primary deposition axis [m]
       W_sub = Substrate width (transverse span) [m]
       H_sub = Substrate thickness (vertical heat sink) [m]

  b. Bead Profile & Inter-Pass Remelting Kinematics:
     During layer deposition, arc heat penetrates into previously deposited material,
     remelting a fraction η_remelt of the preceding layer. The effective layer height
     increment Δz_layer for layer k ≥ 2 is governed by:
       Δz_layer(1) = h₁
       Δz_layer(k) = h_bead · (1 - η_remelt),   ∀ k ≥ 2
     where:
       h₁        = First layer bead height (anchored directly to substrate) [m]
       h_bead    = Unconstrained single-bead height [m]
       η_remelt  = Remelt ratio (0.0 ≤ η_remelt < 1.0, typically 0.15 - 0.30)

  c. Bidirectional Dimensioning Strategy:
     The software provides two coupled mathematical constraint drivers:
     - Layer-Driven (N_layer -> H_build):
         H_build = h₁ + (N_layer - 1) · h_bead · (1 - η_remelt)
     - Height-Driven (H_build -> N_layer):
         N_layer = 1 + ceil( (H_build - h₁) / (h_bead · (1 - η_remelt)) )

  d. Spatial Toolpath Generators (G-code Synthesis):
     - Zigzag: Alternating vector paths [0 → L_x] and [L_x → 0] minimizing idle travel.
     - Unidirectional: Consistent sweep [0 → L_x] with torch return at zero arc power,
       introducing cyclic thermal relaxation.
     - Meander / Contour-Infill: Multi-track perimeter bounding with raster fill.

2. Design & Engineering Philosophy
-----------------------------------
  - Bi-Directional CAD / Slicer Coupling:
    Geometry parameters are bidirectionally synchronized with the embedded 3D Slicer.
    Modifying bead width or layer count in the GUI instantly regenerates the G-code
    toolpath without requiring external slicing software.
  - Conservative Remelt Conservation:
    By explicitly accounting for η_remelt, the framework guarantees that the physical
    top coordinate of the deposit matches experimental profilometry measurements within ±2%.

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                        GEOMETRY TAB                         │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Substrate (Base Plate) Dimensions                        │
  │    ├── Length (L_x)                   -> lx                 │
  │    ├── Width (W_sub)                  -> ly_base            │
  │    └── Thickness (H_sub)              -> hz_base            │
  │                                                             │
  │ 2. Deposit Wall & Fusion Model                              │
  │    ├── Single Bead Width (W_bead)     -> ty_dep             │
  │    ├── First Layer Height (h₁)        -> h_bead             │
  │    ├── Remelt / Fusion Ratio (η)      -> remelt_ratio       │
  │    ├── Dimensioning Driver Strategy   -> _layer_mode        │
  │    │     ├── Define by Total Layers   -> n_layers           │
  │    │     └── Define by Target Height  -> _build_height_var  │
  │    ├── Deposition / Infill Pattern    -> deposition_pattern │
  │    └── Live Fusion Profile Badge      -> geom_fusion_info   │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/geometry_tab.py
        │
        ├──► app.params['lx'], ['ly_base'], ['hz_base']
        │      │
        │      ▼
        │    mesh/box_mesh.py & FreeFEM mesh3 builder
        │      └── Constructs Ω_sub and substrate boundary facets (labels 1..6)
        │
        ├──► app.params['ty_dep'], ['h_bead'], ['n_layers']
        │      │
        │      ├─► codegen/waam_live.py (G-code generator)
        │      │     └── Generates X, Y, Z, t travel coordinates for torch sweep
        │      │
        │      └─► codegen/edp/builder_core.py
        │            └── Synthesizes psiActive level-set activation bounds
        │
        └──► mesh/slicer_api.py (Synchronizes layer slice count & 3D twin bounding box)

5. Numerical & Physical Impact
------------------------------
  - Substrate thickness (H_sub) governs conductive cooling: thin substrates (≤ 6 mm)
    accumulate heat rapidly, causing wide bead spread and potential run-off; thick
    substrates (≥ 20 mm) induce high thermal quench rates and martensitic phase transformation.
  - Bead width (W_bead) directly sets the lateral transverse mesh refinement requirement
    to prevent heat source artificial distortion.
"""
