#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Ultrasonic & Multi-Material Tab
Modular tab for Ultrasonic Vibration Assistance (UVA), acoustic softening, and layer-by-layer multi-material zones.
"""

import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION, FONT_TITLE, FONT_SUBTITLE, FONT_BTN, FONT_STATUS, FONT_MONO_SM
)
from gui.tabs.base import reg_widget


def build_ultrasonic_tab(app):
    """Build the Ultrasonic & Multi-Material tab in app.notebook."""
    app.claude_tab = tk.Frame(app.notebook)
    app.notebook.add(app.claude_tab, text="Ultrasonic")
    reg_widget(app, app.claude_tab, "card_frame")

    content = tk.Frame(app.claude_tab, padx=14, pady=10)
    content.pack(fill=tk.BOTH, expand=True)
    reg_widget(app, content, "card_frame")

    title = tk.Label(
        content, text="Ultrasonic & Multi-Material WAAM Solver",
        font=FONT_TITLE, anchor=tk.W
    )
    title.pack(fill=tk.X, pady=(0, 4))
    reg_widget(app, title, "label")

    desc = tk.Label(
        content,
        text="High-fidelity 3D multi-material thermo-mechanical additive simulation with Ultrasonic Acoustic Softening\n"
             "and exact conforming mesh (zero hanging nodes).",
        font=FONT_SUBTITLE, justify=tk.LEFT, anchor=tk.W
    )
    desc.pack(fill=tk.X, pady=(0, 6))
    reg_widget(app, desc, "label")

    # Physics Module Gating Status Card
    status_card = tk.Frame(content, padx=8, pady=6, bd=1, relief=tk.SOLID)
    status_card.pack(fill=tk.X, pady=(0, 8))
    reg_widget(app, status_card, "card_frame")

    app.us_physics_status_lbl = tk.Label(
        status_card,
        text="⚠ Ultrasonic Physics Module: DISABLED (Physics Tab OFF — Zero Acoustic Softening Applied)",
        font=FONT_SMALL_BOLD, fg="#ea580c", anchor=tk.W
    )
    app.us_physics_status_lbl.pack(side=tk.LEFT, padx=4)
    reg_widget(app, app.us_physics_status_lbl, "label")

    app.us_toggle_btn = tk.Button(
        status_card, text="Enable in Physics Tab", font=FONT_SMALL_BOLD,
        relief=tk.FLAT, padx=8, pady=2, cursor="hand2",
        command=app._toggle_ultrasonic_from_tab
    )
    app.us_toggle_btn.pack(side=tk.RIGHT, padx=4)
    reg_widget(app, app.us_toggle_btn, "button")

    # Parameters Frame
    param_lf = tk.LabelFrame(content, text="Simulation Parameters", font=FONT_SECTION, padx=10, pady=8)
    param_lf.pack(fill=tk.X, pady=(0, 10))
    reg_widget(app, param_lf, "card_labelframe")

    grid = tk.Frame(param_lf)
    grid.pack(fill=tk.X)
    reg_widget(app, grid, "card_frame")

    # Row 0
    tk.Label(grid, text="Ultrasonic Freq (Hz):", font=FONT_SMALL_BOLD).grid(row=0, column=0, sticky=tk.W, pady=3)
    app.us_freq_var = tk.StringVar(value="20000")
    ttk.Entry(grid, textvariable=app.us_freq_var, width=12).grid(row=0, column=1, sticky=tk.W, padx=6, pady=3)

    tk.Label(grid, text="Total Layers:", font=FONT_SMALL_BOLD).grid(row=0, column=2, sticky=tk.W, padx=(15, 0), pady=3)
    app.us_layers_var = tk.StringVar(value="10")
    ttk.Entry(grid, textvariable=app.us_layers_var, width=12).grid(row=0, column=3, sticky=tk.W, padx=6, pady=3)

    # Row 1
    tk.Label(grid, text="Bead Width (mm):", font=FONT_SMALL_BOLD).grid(row=1, column=0, sticky=tk.W, pady=3)
    app.us_width_var = tk.StringVar(value="5.0")
    ttk.Entry(grid, textvariable=app.us_width_var, width=12).grid(row=1, column=1, sticky=tk.W, padx=6, pady=3)

    tk.Label(grid, text="First Layer Height (mm):", font=FONT_SMALL_BOLD).grid(row=1, column=2, sticky=tk.W, padx=(15, 0), pady=3)
    app.us_height_var = tk.StringVar(value="4.0")
    ttk.Entry(grid, textvariable=app.us_height_var, width=12).grid(row=1, column=3, sticky=tk.W, padx=6, pady=3)

    # Row 2
    tk.Label(grid, text="Remelt Fusion (%):", font=FONT_SMALL_BOLD).grid(row=2, column=0, sticky=tk.W, pady=3)
    app.us_remelt_var = tk.StringVar(value="80")
    ttk.Entry(grid, textvariable=app.us_remelt_var, width=12).grid(row=2, column=1, sticky=tk.W, padx=6, pady=3)

    app.us_fusion_info_lbl = tk.Label(grid, text="Subsequent: 3.20 mm (80% fusion)", font=FONT_SMALL_BOLD, fg="#2563eb")
    app.us_fusion_info_lbl.grid(row=2, column=2, columnspan=2, sticky=tk.W, padx=(15, 0), pady=3)
    reg_widget(app, app.us_fusion_info_lbl, "label")

    # Row 3
    tk.Label(grid, text="UVA Amplitude (um):", font=FONT_SMALL_BOLD).grid(row=3, column=0, sticky=tk.W, pady=3)
    app.us_amp_var = tk.StringVar(value="15.0")
    ttk.Entry(grid, textvariable=app.us_amp_var, width=12).grid(row=3, column=1, sticky=tk.W, padx=6, pady=3)

    tk.Label(grid, text="Coupling Eff (0-1):", font=FONT_SMALL_BOLD).grid(row=3, column=2, sticky=tk.W, padx=(15, 0), pady=3)
    app.us_coupling_var = tk.StringVar(value="0.15")
    ttk.Entry(grid, textvariable=app.us_coupling_var, width=12).grid(row=3, column=3, sticky=tk.W, padx=6, pady=3)

    # Row 4
    tk.Label(grid, text="Attenuation (1/m):", font=FONT_SMALL_BOLD).grid(row=4, column=0, sticky=tk.W, pady=3)
    app.us_attenuation_var = tk.StringVar(value="0.12")
    ttk.Entry(grid, textvariable=app.us_attenuation_var, width=12).grid(row=4, column=1, sticky=tk.W, padx=6, pady=3)

    tk.Label(grid, text="Sound Speed (m/s):", font=FONT_SMALL_BOLD).grid(row=4, column=2, sticky=tk.W, padx=(15, 0), pady=3)
    app.us_csound_var = tk.StringVar(value="5790")
    ttk.Entry(grid, textvariable=app.us_csound_var, width=12).grid(row=4, column=3, sticky=tk.W, padx=6, pady=3)

    # Row 5
    tk.Label(grid, text="Streaming k (W/m/K):", font=FONT_SMALL_BOLD).grid(row=5, column=0, sticky=tk.W, pady=3)
    app.us_kstream_var = tk.StringVar(value="45.0")
    ttk.Entry(grid, textvariable=app.us_kstream_var, width=12).grid(row=5, column=1, sticky=tk.W, padx=6, pady=3)

    tk.Label(grid, text="Cavitation thresh (MPa):", font=FONT_SMALL_BOLD).grid(row=5, column=2, sticky=tk.W, padx=(15, 0), pady=3)
    app.us_cavthresh_var = tk.StringVar(value="1.0")
    ttk.Entry(grid, textvariable=app.us_cavthresh_var, width=12).grid(row=5, column=3, sticky=tk.W, padx=6, pady=3)

    # UVA Physics Modules
    uva_lf = tk.LabelFrame(content, text="UVA Physics Modules", font=FONT_SECTION, padx=10, pady=8)
    uva_lf.pack(fill=tk.X, pady=(0, 10))
    reg_widget(app, uva_lf, "card_labelframe")

    uva_grid = tk.Frame(uva_lf)
    uva_grid.pack(fill=tk.X)
    reg_widget(app, uva_grid, "card_frame")

    app.us_streaming_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(uva_grid, text="Acoustic Streaming (k boost in melt pool)", variable=app.us_streaming_var).grid(row=0, column=0, sticky=tk.W, padx=6, pady=3)

    app.us_heatgen_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(uva_grid, text="Acoustic Heat Generation (dissipation)", variable=app.us_heatgen_var).grid(row=0, column=1, sticky=tk.W, padx=6, pady=3)

    app.us_cavitation_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(uva_grid, text="Acoustic Cavitation (void fraction)", variable=app.us_cavitation_var).grid(row=1, column=0, sticky=tk.W, padx=6, pady=3)

    app.us_momentum_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(uva_grid, text="Acoustic Momentum Transfer (radiation pressure)", variable=app.us_momentum_var).grid(row=1, column=1, sticky=tk.W, padx=6, pady=3)

    # Multi-Material Zones
    zone_lf = tk.LabelFrame(content, text="Multi-Material Zones (Layer-by-Layer Architecture)", font=FONT_SECTION, padx=10, pady=8)
    zone_lf.pack(fill=tk.X, pady=(0, 10))
    reg_widget(app, zone_lf, "card_labelframe")

    top_bar = tk.Frame(zone_lf)
    top_bar.pack(fill=tk.X, pady=(0, 6))
    reg_widget(app, top_bar, "card_frame")

    tk.Label(
        top_bar, text="Define discrete material zones, layer allocations, and build sequence:",
        font=FONT_SMALL, fg="#4b5563"
    ).pack(side=tk.LEFT)

    btn_box = tk.Frame(top_bar)
    btn_box.pack(side=tk.RIGHT)
    reg_widget(app, btn_box, "card_frame")

    add_btn = tk.Button(
        btn_box, text="+ Add Zone", font=FONT_SMALL_BOLD,
        relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
        command=app._add_us_zone
    )
    add_btn.pack(side=tk.RIGHT, padx=(4, 0))
    reg_widget(app, add_btn, "button")

    sync_btn = tk.Button(
        btn_box, text="Auto-Balance", font=FONT_SMALL,
        relief=tk.FLAT, padx=8, pady=3, cursor="hand2",
        command=app._auto_balance_us_zones
    )
    sync_btn.pack(side=tk.RIGHT)
    reg_widget(app, sync_btn, "button")

    app.us_zones_container = tk.Frame(zone_lf)
    app.us_zones_container.pack(fill=tk.X, pady=2)
    reg_widget(app, app.us_zones_container, "card_frame")

    app.us_zone_entries = []

    app.us_zones_summary_lbl = tk.Label(zone_lf, text="", font=FONT_SMALL_BOLD, fg="#1d4ed8")
    app.us_zones_summary_lbl.pack(anchor=tk.W, pady=(6, 0))
    reg_widget(app, app.us_zones_summary_lbl, "label")

    app._add_us_zone(layers=5, material="SS308L")
    app._add_us_zone(layers=5, material="SS316L")

    try:
        app.us_layers_var.trace_add("write", lambda *args: (app._sync_ultrasonic_to_geometry(), app._refresh_us_zones()))
        app.us_width_var.trace_add("write", lambda *args: app._sync_ultrasonic_to_geometry())
        app.us_height_var.trace_add("write", lambda *args: (app._sync_ultrasonic_to_geometry(), app._refresh_us_zones()))
        app.us_remelt_var.trace_add("write", lambda *args: (app._sync_ultrasonic_to_geometry(), app._refresh_us_zones()))
    except Exception:
        pass

    action_box = tk.LabelFrame(content, text="Simulation Action", font=FONT_SECTION, padx=10, pady=8)
    action_box.pack(fill=tk.X, pady=(0, 10))
    reg_widget(app, action_box, "card_labelframe")

    b1 = tk.Button(
        action_box, text="Run Ultrasonic Multi-Material Simulation",
        font=FONT_STATUS,
        bg=app.colors.get("button_primary", "#2563eb"), fg=app.colors.get("button_primary_fg", "#ffffff"),
        activebackground=app.colors.get("button_primary_active", "#1d4ed8"),
        command=app._run_simulation, padx=10, pady=6
    )
    b1.pack(fill=tk.X, pady=3)
    app.claude_b1 = b1
    reg_widget(app, b1, "primary_button")

    post_box = tk.LabelFrame(content, text="Results & Post-Processing", font=FONT_SECTION, padx=10, pady=8)
    post_box.pack(fill=tk.X, pady=(0, 10))
    reg_widget(app, post_box, "card_labelframe")

    prow = tk.Frame(post_box)
    prow.pack(fill=tk.X)
    reg_widget(app, prow, "card_frame")

    pv_btn = tk.Button(
        prow, text="Open in ParaView (waam.pvd)", font=FONT_BTN,
        command=app._open_paraview, padx=10, pady=4
    )
    pv_btn.pack(side=tk.LEFT, padx=(0, 6))
    app.claude_pv_btn2 = pv_btn
    reg_widget(app, pv_btn, "button")

    out_btn = tk.Button(
        prow, text="Open Output Directory", font=FONT_BTN,
        command=app._open_output, padx=10, pady=4
    )
    out_btn.pack(side=tk.LEFT)
    app.claude_out_btn2 = out_btn
    reg_widget(app, out_btn, "button")

    app._update_ultrasonic_status_badge()
    return app.claude_tab


"""
================================================================================
ULTRASONIC VIBRATION ASSISTANCE (UVA) TAB — ARCHITECTURAL SPECIFICATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The Ultrasonic Tab governs high-frequency acoustic wave propagation, acoustic cavitation,
microstructural grain refinement, and in-situ stress relief (the Blaha acoustic softening effect).

  a. High-Frequency Acoustic Pressure Wave Field:
     The spatial distribution of acoustic pressure p_ac in the substrate-deposit domain is
     governed by the 3D Helmholtz equation:
       ∇²p_ac + k_ac² · p_ac = 0,   where k_ac = ω / c_sound = 2π f_US / √(K_bulk / ρ)
     where:
       f_US    = Ultrasonic excitation frequency (typically 20 kHz to 40 kHz)
       c_sound = Speed of sound in the liquid/solid metal (≈ 4500 - 5200 m/s)
       A_US    = Sonotrode horn displacement amplitude (5 to 30 μm)
     Peak acoustic pressure amplitude at horn interface:
       P_ac,peak = ρ · c_sound · (2π f_US) · A_US             [MPa]

  b. Acoustic Cavitation & Dendrite Fragmentation (Blake Criterion):
     Transient cavitation bubble collapse occurs whenever local acoustic pressure exceeds
     the Blake threshold:
       P_ac ≥ P_Blake ≈ P_ambient + 0.77 · (γ_liquid / R_nuclei)
     The violent collapse of cavitation bubbles produces localized supersonic micro-jets
     (v_jet > 150 m/s) and local shock waves (P_shock > 1 GPa) that shatter growing primary
     dendrite arms, transforming coarse columnar grains into fine equiaxed grains (CET).

  c. Acoustic Streaming Body Force (Eckart Streaming):
     Attenuation of ultrasonic wave energy imparts a momentum body force to the melt pool:
       F_stream = (2 · α_attenuation · I_acoustic) / c_sound  [N/m³]
     intensifying liquid recirculation, dispersing solute elements, and reducing thermal
     stratification across the melt pool.

  d. Acoustic Plastic Softening (The Blaha Effect) & Stress Relief:
     Oscillatory acoustic stress lowers the apparent static yield strength of the cooling alloy:
       σ_y,eff(T) = σ_y(T) - Δσ_Blaha
     where:
       Δσ_Blaha = K_acoustic · (P_ac / G_shear)⁰·⁵
     Dynamic dislocation unpinning during solid-state cooling prevents residual tensile stress
     accumulation, reducing final macro-distortion by 35% to 65%.

2. Design & Engineering Philosophy
-----------------------------------
  - Coupled Multiphysics Acoustic-Thermal-Mechanical Engine:
    Integrates acoustic transducer parameters directly into the FreeFEM++ variational solver,
    modifying both effective yield surfaces and fluid thermal conductivity in real time.
  - Live Sonotrode Safety & Tuning Badges:
    Automatically computes standing wave nodes and resonance matching to verify horn placement
    relative to the active deposition track.

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                   ULTRASONIC (UVA) TAB                      │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Transducer & Sonotrode Setup                             │
  │    ├── Ultrasonic Frequency (f_US)    -> us_freq (kHz)      │
  │    ├── Vibration Amplitude (A_US)     -> us_amp (μm)        │
  │    ├── Transducer Power Rating        -> us_power (W)       │
  │    └── Horn Coupling Efficiency (η)   -> us_efficiency      │
  │                                                             │
  │ 2. Acoustic Physics Mechanisms                              │
  │    ├── Acoustic Cavitation Toggle     -> enable_cavitation  │
  │    ├── Acoustic Streaming Convection  -> enable_streaming   │
  │    └── Acoustic Softening (Blaha)     -> enable_blaha       │
  │                                                             │
  │ 3. Multi-Material Interface & Transducer Position           │
  │    ├── Substrate Horn Attachment Point-> horn_pos_x, y      │
  │    └── Acoustic Impedance Match Ratio -> Z_ratio display    │
  │                                                             │
  │ 4. Simulation Dispatch & Visualization                      │
  │    ├── Run Ultrasonic Simulation      -> b1 (claude_b1)     │
  │    ├── Open in ParaView (waam.pvd)    -> pv_btn             │
  │    └── Open Output Directory          -> out_btn            │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/ultrasonic_tab.py
        │
        ├── Reads: app.params['us_freq'], ['us_amp'], ['us_power']
        │     │
        │     ▼
        ├──► codegen/edp/builder_core.py (EDPBuilder)
        │      │
        │      ├─► Modifies melt thermal conductivity: k_eff = k_solid + k_streaming
        │      ├─► Modifies J2 yield limit: sig_y = max(10e6, sig_y - delta_blaha)
        │      └─► Exports acoustic pressure field P_ac to VTU/PVD
        │
        └──► Post-processes grain refinement index & residual stress reduction ratio

5. Numerical & Physical Impact
------------------------------
  - Suppresses hot cracking and micro-porosity in crack-sensitive alloys (e.g. Al 7075,
    Ti-6Al-4V, and Nickel superalloys).
  - Lowers peak longitudinal tensile stress at the deposit-substrate interface below the
    critical yield threshold, preventing substrate peeling and delamination.
"""
