#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — OpenFOAM CFD Tab
Modular tab for beamWeldFoam melt pool simulation, VOF controls, mesh resolution, and case generation.
"""

import glob
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION, FONT_MONO, FONT_STATUS, FONT_BTN
)
from gui.tabs.base import reg_widget, add_info_button, create_scrollable_container


def build_openfoam_tab(app):
    """Build the CFD tab in app.notebook."""
    tab = tk.Frame(app.notebook)
    app.notebook.add(tab, text="CFD")
    reg_widget(app, tab, "card_frame")

    canvas, scroll_content = create_scrollable_container(tab, app.colors.get("bg_card", "#ffffff"))
    app.openfoam_canvas = canvas

    # --- CFD Solver Info ---
    info_lf = tk.LabelFrame(scroll_content, text="beamWeldFoam -- VOF Melt Pool CFD (OpenFOAM 2412)",
                            font=FONT_SECTION, padx=8, pady=4)
    info_lf.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, info_lf, "card_labelframe")
    add_info_button(app, info_lf, app._show_openfoam_info)
    info_text = (
        "Two-phase VOF solver with diverging-Gaussian heat source, Marangoni\n"
        "convection, vapor recoil, Darcy mushy damping, and latent heat.\n"
        "Local melt-pool window (X transverse / Y vertical / Z travel, ms\n"
        "timescale). Arc power, speed, and material auto-populate from the\n"
        "Process and Material tabs; window auto-sizes from CAD/G-code bbox."
    )
    info_lbl = tk.Label(info_lf, text=info_text, font=FONT_MONO, justify=tk.LEFT, anchor=tk.W)
    info_lbl.pack(fill=tk.X, padx=4, pady=2)
    reg_widget(app, info_lbl, "label_dim")

    # --- Time Controls ---
    lf_time = tk.LabelFrame(scroll_content, text="CFD Time Controls",
                            font=FONT_SECTION, padx=8, pady=4)
    lf_time.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_time, "card_labelframe")
    add_info_button(app, lf_time, app._show_openfoam_info)

    app.cfd_endtime_var = tk.StringVar(value="0.0005")
    app.cfd_deltat_var = tk.StringVar(value="1e-7")
    app.cfd_writeint_var = tk.StringVar(value="5e-5")
    app.cfd_maxco_var = tk.StringVar(value="0.2")
    app.cfd_maxalphaco_var = tk.StringVar(value="0.2")
    app.cfd_maxdeltat_var = tk.StringVar(value="1e-5")

    cfd_time_fields = [
        ("End Time:", app.cfd_endtime_var, "s"),
        ("Initial deltaT:", app.cfd_deltat_var, "s"),
        ("Write Interval:", app.cfd_writeint_var, "s"),
        ("Max Courant No.:", app.cfd_maxco_var, "[-]"),
        ("Max Alpha Courant:", app.cfd_maxalphaco_var, "[-]"),
        ("Max deltaT:", app.cfd_maxdeltat_var, "s"),
    ]
    for i, (label, var, unit) in enumerate(cfd_time_fields):
        lbl = tk.Label(lf_time, text=label, font=FONT_LABEL)
        lbl.grid(row=i, column=0, sticky=tk.W, padx=(8, 4), pady=2)
        reg_widget(app, lbl, "label")
        entry = tk.Entry(lf_time, textvariable=var, width=12, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
        entry.grid(row=i, column=1, padx=4, pady=2, sticky=tk.W)
        reg_widget(app, entry, "entry")
        u_lbl = tk.Label(lf_time, text=unit, font=FONT_SMALL)
        u_lbl.grid(row=i, column=2, sticky=tk.W, padx=4)
        reg_widget(app, u_lbl, "label_dim")

    # --- Mesh Resolution ---
    lf_mesh = tk.LabelFrame(scroll_content, text="CFD Mesh Resolution",
                            font=FONT_SECTION, padx=8, pady=4)
    lf_mesh.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_mesh, "card_labelframe")
    add_info_button(app, lf_mesh, app._show_openfoam_info)

    app.cfd_cellsize_var = tk.StringVar(value="1.0")
    app.cfd_atmoheight_var = tk.StringVar(value="3.0")
    app.cfd_travel_var = tk.StringVar(value="40.0")
    app.cfd_width_var = tk.StringVar(value="auto")

    mesh_fields = [
        ("Target Cell Size:", app.cfd_cellsize_var, "mm"),
        ("Gas Gap (Y=0..gap):", app.cfd_atmoheight_var, "mm"),
        ("Travel Window (Z):", app.cfd_travel_var, "mm"),
        ("Transverse Width (X, auto):", app.cfd_width_var, "mm"),
    ]
    for i, (label, var, unit) in enumerate(mesh_fields):
        lbl = tk.Label(lf_mesh, text=label, font=FONT_LABEL)
        lbl.grid(row=i, column=0, sticky=tk.W, padx=(8, 4), pady=2)
        reg_widget(app, lbl, "label")
        entry = tk.Entry(lf_mesh, textvariable=var, width=10, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
        entry.grid(row=i, column=1, padx=4, pady=2, sticky=tk.W)
        reg_widget(app, entry, "entry")
        u_lbl = tk.Label(lf_mesh, text=unit, font=FONT_SMALL)
        u_lbl.grid(row=i, column=2, sticky=tk.W, padx=4)
        reg_widget(app, u_lbl, "label_dim")

    # --- MELTING Dict Overrides ---
    lf_melt = tk.LabelFrame(scroll_content, text="Melting Solver Controls",
                            font=FONT_SECTION, padx=8, pady=4)
    lf_melt.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_melt, "card_labelframe")
    add_info_button(app, lf_melt, app._show_openfoam_info)

    app.cfd_mintcorr_var = tk.StringVar(value="1")
    app.cfd_maxtcorr_var = tk.StringVar(value="150")
    app.cfd_epstol_var = tk.StringVar(value="1e-6")
    app.cfd_epsrel_var = tk.StringVar(value="0.95")
    app.cfd_damper_var = tk.BooleanVar(value=False)

    melt_fields = [
        ("Min Temp Correctors:", app.cfd_mintcorr_var, "[-]"),
        ("Max Temp Correctors:", app.cfd_maxtcorr_var, "[-]"),
        ("Epsilon Tolerance:", app.cfd_epstol_var, "[-]"),
        ("Epsilon Relaxation:", app.cfd_epsrel_var, "[-]"),
    ]
    for i, (label, var, unit) in enumerate(melt_fields):
        lbl = tk.Label(lf_melt, text=label, font=FONT_LABEL)
        lbl.grid(row=i, column=0, sticky=tk.W, padx=(8, 4), pady=2)
        reg_widget(app, lbl, "label")
        entry = tk.Entry(lf_melt, textvariable=var, width=12, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
        entry.grid(row=i, column=1, padx=4, pady=2, sticky=tk.W)
        reg_widget(app, entry, "entry")
        u_lbl = tk.Label(lf_melt, text=unit, font=FONT_SMALL)
        u_lbl.grid(row=i, column=2, sticky=tk.W, padx=4)
        reg_widget(app, u_lbl, "label_dim")

    cb_damp = tk.Checkbutton(lf_melt, text="Enable Interface Damper",
                             variable=app.cfd_damper_var, font=FONT_LABEL)
    cb_damp.grid(row=len(melt_fields), column=0, columnspan=3, sticky=tk.W, padx=8, pady=2)
    reg_widget(app, cb_damp, "check")

    # --- Beam Oscillation & Focus ---
    lf_beam = tk.LabelFrame(scroll_content, text="Beam Oscillation & Focus",
                            font=FONT_SECTION, padx=8, pady=4)
    lf_beam.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_beam, "card_labelframe")
    add_info_button(app, lf_beam, app._show_openfoam_info)

    app.cfd_osc_amp_var = tk.StringVar(value="0.0")
    app.cfd_osc_freq_var = tk.StringVar(value="0.0")
    app.cfd_yr_var = tk.StringVar(value="0.15")
    app.cfd_focshift_var = tk.StringVar(value="0.0")

    beam_fields = [
        ("Oscillation Amplitude:", app.cfd_osc_amp_var, "mm"),
        ("Oscillation Frequency:", app.cfd_osc_freq_var, "Hz"),
        ("Y_R (Divergence Param):", app.cfd_yr_var, "[-]"),
        ("Focus Shift Velocity:", app.cfd_focshift_var, "mm/s"),
    ]
    for i, (label, var, unit) in enumerate(beam_fields):
        lbl = tk.Label(lf_beam, text=label, font=FONT_LABEL)
        lbl.grid(row=i, column=0, sticky=tk.W, padx=(8, 4), pady=2)
        reg_widget(app, lbl, "label")
        entry = tk.Entry(lf_beam, textvariable=var, width=12, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
        entry.grid(row=i, column=1, padx=4, pady=2, sticky=tk.W)
        reg_widget(app, entry, "entry")
        u_lbl = tk.Label(lf_beam, text=unit, font=FONT_SMALL)
        u_lbl.grid(row=i, column=2, sticky=tk.W, padx=4)
        reg_widget(app, u_lbl, "label_dim")

    # --- Power Ramp ---
    lf_ramp = tk.LabelFrame(scroll_content, text="Power Ramp & Deposition Cutoff",
                            font=FONT_SECTION, padx=8, pady=4)
    lf_ramp.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_ramp, "card_labelframe")
    add_info_button(app, lf_ramp, app._show_openfoam_info)

    app.cfd_qramp_var = tk.StringVar(value="auto")
    app.cfd_tshift_var = tk.StringVar(value="1.0")
    app.cfd_cutoff_var = tk.StringVar(value="0.5")

    ramp_fields = [
        ("Q Ramp Rate (auto=10x Q, decays past tshift):", app.cfd_qramp_var, "W/s"),
        ("Time Shift (tshift, keep > endTime):", app.cfd_tshift_var, "s"),
        ("Deposition Cutoff (alpha):", app.cfd_cutoff_var, "[-]"),
    ]
    for i, (label, var, unit) in enumerate(ramp_fields):
        lbl = tk.Label(lf_ramp, text=label, font=FONT_LABEL)
        lbl.grid(row=i, column=0, sticky=tk.W, padx=(8, 4), pady=2)
        reg_widget(app, lbl, "label")
        entry = tk.Entry(lf_ramp, textvariable=var, width=12, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
        entry.grid(row=i, column=1, padx=4, pady=2, sticky=tk.W)
        reg_widget(app, entry, "entry")
        u_lbl = tk.Label(lf_ramp, text=unit, font=FONT_SMALL)
        u_lbl.grid(row=i, column=2, sticky=tk.W, padx=4)
        reg_widget(app, u_lbl, "label_dim")

    # --- Action Buttons ---
    btn_frame = tk.Frame(scroll_content, pady=6)
    btn_frame.pack(fill=tk.X, padx=8)
    reg_widget(app, btn_frame, "card_frame")

    gen_btn = tk.Button(
        btn_frame, text="Generate BeamWeldFoam Case",
        font=FONT_STATUS,
        command=app._openfoam_generate_case, padx=12, pady=5
    )
    gen_btn.pack(side=tk.LEFT, padx=(0, 6))
    reg_widget(app, gen_btn, "button")

    run_btn = tk.Button(
        btn_frame, text="Run BeamWeldFoam",
        font=FONT_STATUS,
        command=app._openfoam_run, padx=12, pady=5
    )
    run_btn.pack(side=tk.LEFT, padx=6)
    reg_widget(app, run_btn, "button")

    pv_btn = tk.Button(
        btn_frame, text="ParaView (OpenFOAM)",
        font=FONT_BTN,
        command=app._openfoam_paraview, padx=8, pady=4
    )
    pv_btn.pack(side=tk.LEFT, padx=6)
    reg_widget(app, pv_btn, "button")

    rep_btn = tk.Button(
        btn_frame, text="CFD Report",
        font=FONT_BTN,
        command=app._open_cfd_report, padx=8, pady=4
    )
    rep_btn.pack(side=tk.LEFT, padx=6)
    reg_widget(app, rep_btn, "button")

    # --- Status readout ---
    app.cfd_status_var = tk.StringVar(value="Ready. Configure parameters and click Generate.")
    cfd_status = tk.Label(scroll_content, textvariable=app.cfd_status_var,
                          font=FONT_MONO, anchor=tk.W, justify=tk.LEFT)
    cfd_status.pack(fill=tk.X, padx=12, pady=(4, 8))
    reg_widget(app, cfd_status, "label_dim")

    return tab


"""
================================================================================
OPENFOAM CFD TAB — ARCHITECTURAL SPECIFICATION & FORMULATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The OpenFOAM CFD Tab interfaces with `beamWeldFoam` (OpenFOAM 2412) to resolve 3D multiphase
free-surface hydrodynamics, keyhole dynamics, and Marangoni convection in the melt pool.

  a. Multiphase Volume-of-Fluid (VOF) Phase Indicator:
     Fluid phase fraction α₁ (1 = liquid metal, 0 = shielding gas/air) is tracked via algebraic
     interface compression:
       ∂α₁/∂t + ∇ · (α₁ U) + ∇ · ( α₁ (1 - α₁) U_r ) = 0
     where U_r is the artificial relative compression velocity active only at the interface.

  b. Incompressible Navier-Stokes with Interfacial Momentum Sources:
       ∂(ρ U)/∂t + ∇ · (ρ U ⊗ U) = -∇p_rgh - g · x ∇ρ + ∇ · [ μ (∇U + ∇Uᵀ) ]
                                  + F_CSF + F_Darcy + F_recoil
     where:
       1. Continuum Surface Force (CSF) & Thermocapillary Marangoni Traction:
            F_CSF = [ γ · κ · n + (∂γ/∂T) · ( ∇T - (∇T · n) n ) ] · ||∇α₁||
          where γ is surface tension [N/m], κ = -∇ · n is surface curvature, and
          ∂γ/∂T is the Marangoni coefficient (typically -0.2 to -0.4 mN/(m·K) for steel).
       2. Darcy Mushy-Zone Permeability Damping (Carman-Kozeny):
            F_Darcy = -C_mush · [ (1 - f_L)² / (f_L³ + ε_safe) ] · (U - U_solid)
          where f_L is liquid mass fraction, driving velocity to zero inside solid dendrites.
       3. Vapor Recoil Pressure (Anisimov Keyhole Model):
            p_rec = 0.54 · p_atm · exp[ (ΔH_v / R) · (1/T_boil - 1/T) ]

  c. Energy Conservation with Latent Enthalpy & Evaporation Loss:
       ∂(ρ C_p T)/∂t + ∇ · (ρ C_p U T) = ∇ · (k ∇T) + Q_source - Q_melt - Q_evap

  d. Courant Number Stability Bounds:
     Due to capillary wave velocities and rapid fluid jets, explicit interface marching requires:
       Co       = ||U|| · Δt / Δx ≤ Co_max             (typically 0.2 - 0.3)
       Co_alpha = ||U_surf|| · Δt / Δx ≤ AlphaCo_max   (typically 0.2)

2. Design & Engineering Philosophy
-----------------------------------
  - Hierarchical Micro-Macro Domain Decomposition:
    FreeFEM++ solves macro thermal-structural evolution over the entire 300 mm workpiece (seconds/hours);
    beamWeldFoam solves high-resolution local melt pool fluid flow inside a moving 20 mm window
    over millisecond timescales (0.1 to 10 ms).
  - One-Click Automated Case Generation:
    Automatically translates active WAAM arc current, travel speed, and material thermophysical
    properties into valid OpenFOAM dictionaries (`transportProperties`, `fvSchemes`, `controlDict`).

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                       OPENFOAM CFD TAB                      │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Solver Info & Capabilities Banner                        │
  │    └── beamWeldFoam VOF Solver Overview                     │
  │                                                             │
  │ 2. CFD Time Controls & Stability Limits                     │
  │    ├── End Time (s)                   -> cfd_endtime_var    │
  │    ├── Initial deltaT (s)             -> cfd_deltat_var     │
  │    ├── Write Interval (s)             -> cfd_writeint_var   │
  │    ├── Max Courant Number (Co)        -> cfd_maxco_var      │
  │    ├── Max Alpha Courant (Co_alpha)   -> cfd_maxalphaco_var │
  │    └── Max deltaT Bound (s)           -> cfd_maxdeltat_var  │
  │                                                             │
  │ 3. Domain & Grid Sizing Controls                            │
  │    ├── Window Dimensions (Lx, Ly, Lz) -> cfd_box_*_var      │
  │    └── Cell Count / Mesh Refinement   -> cfd_mesh_*_var     │
  │                                                             │
  │ 4. Execution Actions & Diagnostics                          │
  │    ├── Generate BeamWeldFoam Case     -> gen_btn            │
  │    ├── Run BeamWeldFoam (Parallel)    -> run_btn            │
  │    ├── Launch ParaView (foam.foam)    -> pv_btn             │
  │    ├── Open CFD Summary Report        -> rep_btn            │
  │    └── Live Execution Status Readout  -> cfd_status_var     │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/openfoam_tab.py
        │
        ├── Reads: app.params['I_weld'], ['v_scan'], ['material_dep']
        │     │
        │     ▼
        ├──► cfd/openfoam_adapter.py
        │      │
        │      ├─► Writes 0/alpha.metal, 0/U, 0/T, 0/p_rgh
        │      ├─► Writes constant/thermophysicalProperties
        │      ├─► blockMesh / snappyHexMesh execution
        │      └─► Launches beamWeldFoam in background worker
        │
        └──► Post-processes melt pool width, depth, and fluid recirculation velocity

5. Numerical & Physical Impact
------------------------------
  - Captures outward Marangoni flow (negative ∂γ/∂T), explaining the characteristic
    shallow, wide bead profile observed in stainless steel WAAM.
  - Resolves keyhole porosity formation caused by vapor recoil collapse during arc pulsing.
"""
