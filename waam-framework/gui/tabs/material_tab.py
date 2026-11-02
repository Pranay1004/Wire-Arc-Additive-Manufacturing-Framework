#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Material Tab
Modular tab for Alloy assignment, wire feedstock, and interfacial metallurgy mismatch.
"""

import math
import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION, FONT_MONO
)
from gui.tabs.base import reg_widget, make_param_row, add_info_button


def build_material_tab(app):
    """Build the Material tab in app.notebook."""
    tab = tk.Frame(app.notebook)
    app.notebook.add(tab, text="Material")
    reg_widget(app, tab, "card_frame")

    mat_names = list(app.materials.keys()) if app.materials else ["SS308L", "SS316L", "Ti-6Al-4V", "Pure Al (Al1xxx)"]

    # 1. Dual Material Assignment (Substrate vs Deposit)
    lf1 = tk.LabelFrame(tab, text="Alloy Assignment (Dissimilar Multi-Material)", font=FONT_SECTION, padx=8, pady=4)
    lf1.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf1, "card_labelframe")
    add_info_button(app, lf1, app._show_material_info)

    lbl_base = tk.Label(lf1, text="Substrate Alloy (Base Plate):", font=FONT_SMALL_BOLD)
    lbl_base.grid(row=0, column=0, padx=6, pady=3, sticky=tk.W)
    reg_widget(app, lbl_base, "label")

    app.material_base_var = tk.StringVar(value=app.params.get("material_base", "SS316L"))
    base_combo = ttk.Combobox(lf1, textvariable=app.material_base_var, values=mat_names, width=22, state="readonly", font=FONT_SMALL)
    base_combo.grid(row=0, column=1, padx=4, pady=3, sticky=tk.W)
    base_combo.bind("<<ComboboxSelected>>", app._on_multi_material_change)

    lbl_dep = tk.Label(lf1, text="Deposit Bead Alloy (Wire):", font=FONT_SMALL_BOLD)
    lbl_dep.grid(row=1, column=0, padx=6, pady=3, sticky=tk.W)
    reg_widget(app, lbl_dep, "label")

    app.material_dep_var = tk.StringVar(value=app.params.get("material_dep", "SS308L"))
    dep_combo = ttk.Combobox(lf1, textvariable=app.material_dep_var, values=mat_names, width=22, state="readonly", font=FONT_SMALL)
    dep_combo.grid(row=1, column=1, padx=4, pady=3, sticky=tk.W)
    dep_combo.bind("<<ComboboxSelected>>", app._on_multi_material_change)

    lbl_wire_dia = tk.Label(lf1, text="Wire Diameter / Size (d_wire):", font=FONT_SMALL_BOLD)
    lbl_wire_dia.grid(row=2, column=0, padx=6, pady=3, sticky=tk.W)
    reg_widget(app, lbl_wire_dia, "label")

    wire_var = app._param_vars["d_wire"][0] if "d_wire" in app._param_vars else tk.StringVar(value="1.2")
    app.material_wire_combo = ttk.Combobox(
        lf1, textvariable=wire_var,
        values=["0.8", "0.9", "1.0", "1.2", "1.6", "2.0", "2.4", "3.2"],
        width=10, font=FONT_SMALL
    )
    app.material_wire_combo.grid(row=2, column=1, padx=4, pady=3, sticky=tk.W)
    app.material_wire_combo.bind("<<ComboboxSelected>>", lambda e: app._on_any_param_change("d_wire"))

    lbl_wire_u = tk.Label(lf1, text="mm (AWS/ISO Solid Wire Feedstock)", font=FONT_SMALL)
    lbl_wire_u.grid(row=2, column=2, padx=4, pady=3, sticky=tk.W)
    reg_widget(app, lbl_wire_u, "label_dim")

    app.material_feed_info = tk.Label(
        lf1, text="—", font=FONT_MONO, justify=tk.LEFT, anchor=tk.W,
        relief=tk.SOLID, bd=1, padx=6, pady=4
    )
    app.material_feed_info.grid(row=3, column=0, columnspan=3, padx=6, pady=4, sticky=tk.EW)
    reg_widget(app, app.material_feed_info, "entry")

    # 2. Interfacial Thermophysical & CTE Compatibility Card
    lf_mismatch = tk.LabelFrame(tab, text="Interfacial Thermophysical & CTE Compatibility", font=FONT_SECTION, padx=8, pady=4)
    lf_mismatch.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_mismatch, "card_labelframe")
    add_info_button(app, lf_mismatch, app._show_material_info)

    app.dissimilar_info = tk.Text(lf_mismatch, height=5, width=60, font=FONT_MONO, state=tk.DISABLED, relief=tk.SOLID, bd=1)
    app.dissimilar_info.pack(fill=tk.X, padx=4, pady=4)
    reg_widget(app, app.dissimilar_info, "entry")

    # 3. Physical Constants & Thermal Boundary Loss
    lf2 = tk.LabelFrame(tab, text="Physical Constants & Thermal Boundary Loss", font=FONT_SECTION, padx=8, pady=4)
    lf2.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf2, "card_labelframe")
    add_info_button(app, lf2, app._show_properties_info)
    make_param_row(app, lf2, "Deposit Density (ρ):", "rho", 0, "kg/m³")
    make_param_row(app, lf2, "Solidus Temp (T_sol):", "T_sol", 1, "°C")
    make_param_row(app, lf2, "Liquidus Temp (T_liq):", "T_liq", 2, "°C")
    make_param_row(app, lf2, "Latent Heat of Fusion (L_f):", "latent_heat", 3, "J/kg")
    make_param_row(app, lf2, "Surface Emissivity (ε):", "emissivity", 4, "[-]")
    make_param_row(app, lf2, "Convection Coeff (h_conv):", "h_conv", 5, "W/(m²·K)")
    make_param_row(app, lf2, "Base Contact Loss (h_bot):", "h_bot", 6, "W/(m²·K)")
    make_param_row(app, lf2, "Mechanical Cutoff (T_mech):", "T_mech", 7, "°C")

    app._on_multi_material_change()
    return tab


"""
================================================================================
MATERIAL TAB — ARCHITECTURAL SPECIFICATION & FORMULATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The Material Tab configures alloy properties, phase transition thermodynamics, and
interfacial mismatch between dissimilar baseplate and deposited wire alloys.

  a. Apparent Heat Capacity Formulation (Latent Heat of Fusion):
     Phase change over the mushy zone [T_sol, T_liq] is modeled via the apparent heat
     capacity method, eliminating moving boundary singularities:
       C_p,eff(T) = { C_p(T),                                        T < T_sol
                    { C_p(T) + L_f / (T_liq - T_sol),                T_sol ≤ T ≤ T_liq
                    { C_p(T),                                        T > T_liq
     where:
       T_sol = Solidus temperature [°C]
       T_liq = Liquidus temperature [°C]
       L_f   = Latent heat of fusion [J/kg]

  b. Thermal Boundary Dissipation:
     Total surface heat loss q_loss combines natural/forced convection and Stefan-Boltzmann radiation:
       q_loss = h_conv · (T - T_amb) + ε · σ_SB · ( (T + 273.15)⁴ - (T_amb + 273.15)⁴ )
     where:
       h_conv = Convective heat transfer coefficient [W/(m²·K)]
       ε      = Surface emissivity (0.4 - 0.8 for oxidized steel/titanium)
       σ_SB   = 5.670374 × 10⁻⁸ W/(m²·K⁴) (Stefan-Boltzmann constant)
     Conductive loss into the clamping tooling / cold worktable:
       q_bottom = h_bot · (T - T_table) [W/m²]

  c. Interfacial CTE & Bimetallic Thermal Stress:
     When depositing dissimilar alloys (e.g. Inconel 625 onto 316L, or ER70S6 onto CuCrZr),
     the differential coefficient of thermal expansion Δα induces severe interfacial shears:
       Δα = |α_dep(T) - α_base(T)|                            [1/K]
       σ_interface ≈ E_eff · Δα · (T_solidification - T_amb)  [MPa]
     The built-in compatibility checker warns when Δα > 3.0 × 10⁻⁶ /K to prevent
     delamination during cooldown.

2. Design & Engineering Philosophy
-----------------------------------
  - Multi-Material Domain Partitioning:
    Substrate (Ω_sub) and Deposit (Ω_dep) are assigned discrete material tags (labels 1 and 2),
    enabling continuous variational formulations with piecewise material tensors.
  - Zero Hardcoding:
    All alloy coefficients are read dynamically from `materials.json` with polynomial
    temperature fits k(T), Cp(T), E(T), and σ_y(T).

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                        MATERIAL TAB                         │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Alloy Assignment (Dissimilar Multi-Material)             │
  │    ├── Substrate Alloy (Base)         -> material_base      │
  │    ├── Deposit Bead Alloy (Wire)      -> material_dep       │
  │    ├── Wire Feedstock Diameter        -> d_wire             │
  │    └── Feedstock Metallurgy Summary   -> material_feed_info │
  │                                                             │
  │ 2. Interfacial Thermophysical & CTE Compatibility           │
  │    └── Live Delta-CTE, Conductivity & Solidus Mismatch Card │
  │                                                             │
  │ 3. Physical Constants & Thermal Boundary Loss               │
  │    ├── Density (ρ)                    -> rho                │
  │    ├── Solidus Temp (T_sol)           -> T_sol              │
  │    ├── Liquidus Temp (T_liq)          -> T_liq              │
  │    ├── Latent Heat of Fusion (L_f)    -> latent_heat        │
  │    ├── Surface Emissivity (ε)         -> emissivity         │
  │    ├── Convection Coeff (h_conv)      -> h_conv             │
  │    ├── Base Contact Loss (h_bot)      -> h_bot              │
  │    └── Mechanical Cutoff (T_mech)     -> T_mech             │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/material_tab.py
        │
        ├──► app.material_base_var & app.material_dep_var
        │      │
        │      ▼
        │    codegen/edp/builder_core.py (EDPBuilder)
        │      │
        │      ├─► piecewise P0 function kTh, CpTh, rhoTh
        │      ├─► Boundary condition facets (radiation & convection)
        │      └─► Mechanical temperature-dependent Young's modulus E(T)
        │
        └──► gui/tabs/ultrasonic_tab.py
               └── Seeds acoustic impedance Z = ρ · c_sound for UVA analysis

5. Numerical & Physical Impact
------------------------------
  - Latent heat smoothing (mushy zone ΔT = T_liq - T_sol) prevents severe non-linear
    Newton oscillations while preserving exact Stefan energy conservation.
  - T_mech cutoff quenches unphysical high-temperature elastic stresses above 800-1000 °C,
    where material flows plastically under minimal stress.
"""
