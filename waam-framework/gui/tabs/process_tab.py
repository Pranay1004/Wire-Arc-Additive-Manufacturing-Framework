#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Process Tab
Modular tab for Welding parameters, heat source models, and dynamic parameters.
"""

import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION, FONT_MONO
)
from gui.tabs.base import reg_widget, make_param_row, add_info_button


def build_process_tab(app):
    """Build the Process tab in app.notebook."""
    tab = tk.Frame(app.notebook)
    app.notebook.add(tab, text="Process")
    reg_widget(app, tab, "card_frame")

    # Arc / Energy Process Parameters
    lf1 = tk.LabelFrame(tab, text="Arc / Energy Process Parameters", font=FONT_SECTION, padx=8, pady=4)
    lf1.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf1, "card_labelframe")
    add_info_button(app, lf1, app._show_process_info)
    make_param_row(app, lf1, "Arc Current (I_arc):", "I_weld", 0, "A")
    make_param_row(app, lf1, "Arc Voltage (U_arc):", "U_weld", 1, "V")
    make_param_row(app, lf1, "Thermal Efficiency (η_arc):", "eta_arc", 2, "[-]")
    make_param_row(app, lf1, "Torch Travel Speed (v_scan / v_travel):", "v_scan", 3, "mm/s")
    make_param_row(app, lf1, "Wire Feed Speed (WFS / v_wire):", "v_wire", 4, "m/min")
    make_param_row(app, lf1, "Wire Diameter (d_wire):", "d_wire", 5, "mm")
    make_param_row(app, lf1, "Inter-Pass Dwell (t_dwell):", "t_wait", 6, "s")

    # Calculated Heat Input & Energy Output Card
    app.heat_calc_frame = tk.LabelFrame(
        tab, text="Calculated Heat Input & Energy Output",
        font=FONT_SECTION, padx=8, pady=4
    )
    app.heat_calc_frame.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, app.heat_calc_frame, "card_labelframe")
    add_info_button(app, app.heat_calc_frame, app._show_heat_calc_info)

    app.heat_calc_label = tk.Label(
        app.heat_calc_frame, text="—",
        font=FONT_MONO, justify=tk.LEFT, anchor=tk.W
    )
    app.heat_calc_label.pack(fill=tk.X, padx=4, pady=2)
    reg_widget(app, app.heat_calc_label, "label")

    # Heat Source Model
    lf2 = tk.LabelFrame(tab, text="Heat Source Model", font=FONT_SECTION, padx=8, pady=4)
    lf2.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf2, "card_labelframe")
    add_info_button(app, lf2, app._show_heatsource_info)

    sources = [
        ("goldak", "Goldak Double Ellipsoid (Arc / GMAW WAAM)"),
        ("p48_surface", "P48 Surface Arc Flux + Droplet Impingement (GMAW ER70S6 / 316L Thin-Wall)"),
        ("gaussian_vol", "3D Gaussian Volumetric (Laser-DED)"),
        ("gaussian_surf", "2D Gaussian Surface Heat Flux (Thin powder/wire)"),
        ("conical", "Conical Frustum (Keyhole / Plasma PTA)"),
        ("uniform", "Uniform Moving Band (Wide weave / Brazing)"),
        ("prescribed", "Prescribed Liquidus Temperature (Fast)"),
    ]

    app.source_var = tk.StringVar(value=app.params.get("heat_source", "goldak"))
    for i, (val, text) in enumerate(sources):
        rb = tk.Radiobutton(
            lf2, text=text, variable=app.source_var, value=val,
            font=FONT_SMALL, command=app._update_source_params
        )
        rb.grid(row=i, column=0, sticky=tk.W, padx=4, pady=1)
        reg_widget(app, rb, "radio")

    app.source_params_frame = tk.LabelFrame(tab, text="Active Heat Source Dimensions", font=FONT_SECTION, padx=8, pady=4)
    app.source_params_frame.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, app.source_params_frame, "card_labelframe")
    add_info_button(app, app.source_params_frame, app._show_heatsource_info)
    app._update_source_params()

    return tab


def update_source_params(app):
    """Dynamically reconstruct parameter inputs for the selected heat source."""
    if not hasattr(app, "source_params_frame"):
        return
    for w in app.source_params_frame.winfo_children():
        w.destroy()
    src = app.source_var.get()
    if src == "goldak":
        make_param_row(app, app.source_params_frame, "Front Semi-Axis (a_f):", "af", 0, "mm")
        make_param_row(app, app.source_params_frame, "Rear Semi-Axis (a_r):", "ar", 1, "mm")
        make_param_row(app, app.source_params_frame, "Melt Half-Width (b_G):", "bG", 2, "mm")
        make_param_row(app, app.source_params_frame, "Penetration Depth (c_G):", "cG", 3, "mm")
        make_param_row(app, app.source_params_frame, "Front Power Fraction (f_f):", "ff", 4, "[-]")
        make_param_row(app, app.source_params_frame, "Rear Power Fraction (f_r):", "fr", 5, "[-]")
    elif src in ("p48_surface", "p48"):
        make_param_row(app, app.source_params_frame, "Droplet Enthalpy Fraction (η_d):", "eta_drop", 0, "[-]")
        make_param_row(app, app.source_params_frame, "Droplet Transfer Temp (T_drop):", "T_drop", 1, "°C")
        try:
            i_w = float(app._param_vars["I_weld"][0].get().strip() or "150")
        except Exception:
            i_w = 150.0
        try:
            eta_d = float(app._param_vars.get("eta_drop", [None])[0].get().strip() or "0.25")
        except Exception:
            eta_d = 0.25
        sig_q = 6.205e-4 * (max(i_w, 10.0) ** 0.28) * 1000.0
        lbl_info = tk.Label(
            app.source_params_frame,
            text=f"ⓘ P48 Arc Radius: σ_q(I) = 6.205×10⁻⁴·I⁰·²⁸ = {sig_q:.2f} mm | Direct Flux = {(1.0-eta_d)*100:.0f}% | Droplet = {eta_d*100:.0f}%",
            font=FONT_SMALL_BOLD, fg="#0284c7"
        )
        lbl_info.grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(4, 2))
        reg_widget(app, lbl_info, "label")
    elif src == "gaussian_vol":
        make_param_row(app, app.source_params_frame, "Beam Radius (R_beam):", "R_beam", 0, "mm")
    elif src == "gaussian_surf":
        make_param_row(app, app.source_params_frame, "Surface Spot Radius (R_spot):", "R_spot", 0, "mm")
    elif src == "conical":
        make_param_row(app, app.source_params_frame, "Top Radius (r_top):", "r_top", 0, "mm")
        make_param_row(app, app.source_params_frame, "Bottom Radius (r_bot):", "r_bot", 1, "mm")
        make_param_row(app, app.source_params_frame, "Penetration Depth (d_cone):", "depth_cone", 2, "mm")
    elif src == "uniform":
        make_param_row(app, app.source_params_frame, "Half-Length (X):", "a_band", 0, "mm")
        make_param_row(app, app.source_params_frame, "Half-Width (Y):", "b_band", 1, "mm")
        make_param_row(app, app.source_params_frame, "Depth (Z):", "c_band", 2, "mm")
    elif src == "prescribed":
        make_param_row(app, app.source_params_frame, "Activation Radius:", "R_activate", 0, "mm")
    app._apply_theme()


"""
================================================================================
PROCESS TAB — ARCHITECTURAL SPECIFICATION & FORMULATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The Process Tab governs electromagnetic power transformation, thermal energy injection,
wire mass addition, and spatial distribution of heat flux into the melt pool.

  a. Arc Power & Net Thermal Input:
       P_arc    = I_arc · U_arc                               [W]
       Q_eff    = η_arc · P_arc = η_arc · I_arc · U_arc       [W]
       E_linear = Q_eff / v_scan = (η_arc · I_arc · U_arc) / v_scan   [J/m or kJ/mm]
     where:
       I_arc  = Welding current [A]
       U_arc  = Arc voltage [V]
       η_arc  = Arc thermal efficiency (0.75 - 0.85 for GMAW/WAAM, 0.35 - 0.45 for Laser)
       v_scan = Torch translation speed [m/s]

  b. Wire Feed Kinematics & Deposition Rate:
       A_wire = π · (d_wire / 2)²                             [m²]
       V̇_dep  = A_wire · v_wire                               [m³/s]
       ṁ_dep  = ρ_metal · V̇_dep                               [kg/s]
     The linear mass deposition density per unit length:
       λ_mass = ṁ_dep / v_scan                                [kg/m]

  c. Heat Source Spatial Kernels:
     1. Goldak Double-Ellipsoid Volumetric Model (GMAW / Arc WAAM standard):
        The power density q(x, y, z) is divided into front (f) and rear (r) quadrants:
          q_f(x,y,z) = [6√3 · f_f · Q_eff] / [π√π · a_f · b_G · c_G]
                       · exp( -3(x-x₀)²/a_f² - 3(y-y₀)²/b_G² - 3(z-z₀)²/c_G² )
          q_r(x,y,z) = [6√3 · f_r · Q_eff] / [π√π · a_r · b_G · c_G]
                       · exp( -3(x-x₀)²/a_r² - 3(y-y₀)²/b_G² - 3(z-z₀)²/c_G² )
        Subject to physical energy continuity: f_f + f_r = 2.0.

     2. P48 Combined Surface Flux + Droplet Superheat Impingement:
        Current-dependent arc distribution parameter:
          σ_q(I) = 6.205 × 10⁻⁴ · I_arc⁰·²⁸                   [m]
        Direct arc surface flux:
          q_surf(r) = [(1 - η_drop) · Q_eff] / [2π · σ_q²] · exp( -r² / (2σ_q²) )
        Droplet transfer enthalpy:
          Q_drop = η_drop · Q_eff injected at T_drop (≈ 2200 - 2400 °C).

     3. 3D Volumetric Gaussian (Laser-DED / Electron Beam):
          q(r, z) = [2 · Q_eff] / [π · R_beam² · d_pen] · exp( -2r² / R_beam² ) · (1 - z/d_pen)

2. Design & Engineering Philosophy
-----------------------------------
  - Dynamic Form Reconstitution:
    Switching the heat source radio buttons instantly tears down and reconstructs the active
    parameter cards without reloading the tab or losing shared process parameters.
  - Live Process Metric Derivation:
    Every keystroke recalculates linear heat input, cooling rate bounds, and expected dilution,
    giving the welding engineer instantaneous physical feedback.

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                         PROCESS TAB                         │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Arc / Energy Process Parameters                          │
  │    ├── Arc Current (I_arc)            -> I_weld             │
  │    ├── Arc Voltage (U_arc)            -> U_weld             │
  │    ├── Thermal Efficiency (η_arc)     -> eta_arc            │
  │    ├── Travel Speed (v_scan)          -> v_scan             │
  │    ├── Wire Feed Speed (WFS)          -> v_wire             │
  │    ├── Wire Diameter (d_wire)         -> d_wire             │
  │    └── Inter-Pass Dwell (t_dwell)     -> t_wait             │
  │                                                             │
  │ 2. Calculated Heat Input & Energy Card                      │
  │    └── Live Net Power, Linear Heat Input & Deposition Rate  │
  │                                                             │
  │ 3. Heat Source Model Selector                               │
  │    ├── Goldak Double Ellipsoid        -> "goldak"           │
  │    ├── P48 Surface + Droplets         -> "p48_surface"      │
  │    ├── 3D Gaussian Volumetric         -> "gaussian_vol"     │
  │    ├── 2D Gaussian Surface            -> "gaussian_surf"    │
  │    ├── Conical Frustum                -> "conical"          │
  │    └── Uniform Moving Band            -> "uniform"          │
  │                                                             │
  │ 4. Active Heat Source Dimensions Frame                      │
  │    └── [Dynamically rebuilt for active kernel]              │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/process_tab.py
        │
        ├──► app.params['I_weld'], ['U_weld'], ['eta_arc'], ['v_scan']
        │      │
        │      ▼
        │    codegen/edp/builder_core.py (EDPBuilder)
        │      │
        │      ├─► Formulates Q_eff & transient source coordinates (x0, y0, z0)
        │      ├─► freefem_goldak_snippet() / freefem_p48_snippet()
        │      └─► Heat source term in variational form: + int3d(Th)( q_source * v )
        │
        └──► gui/tabs/openfoam_tab.py
               └── Seeds beamWeldFoam laser/arc power boundary dictionary

5. Numerical & Physical Impact
------------------------------
  - Linear heat input E_linear directly governs peak melt pool temperature and
    the cooling time between 800 °C and 500 °C (Δt8/5).
  - Accurate Goldak dimensions (a_f, a_r, b_G, c_G) are mandatory: undersized dimensions
    create steep spatial gradients requiring fine meshes; oversized dimensions falsely
    smear the melt pool and underestimate peak temperatures.
"""
