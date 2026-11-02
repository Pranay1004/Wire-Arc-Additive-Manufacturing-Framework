"""
WAAM Multi-Physics Simulator — Engineering & Educational Info Guides
=====================================================================
Encapsulates rich engineering documentation, physical formulation details,
and metallurgical guidance dialogs decoupled from the main WAAMApp controller.
"""

import tkinter as tk
from tkinter import ttk

from gui.fonts import FONT_TITLE, FONT_SECTION, FONT_LABEL, FONT_BTN


def show_info_dialog(parent, colors: dict, title: str, heading: str, text_blocks: list):
    """Generic info dialog generator with rich typography and scrollable text."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.geometry("760x640")
    dlg.minsize(680, 500)
    dlg.transient(parent)
    dlg.grab_set()

    canvas = tk.Canvas(dlg, highlightthickness=0, bg=colors["bg_card"])
    scroll = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
    frame = tk.Frame(canvas, bg=colors["bg_card"], padx=18, pady=14)
    frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    cw = canvas.create_window((0, 0), window=frame, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    title_lbl = tk.Label(
        frame, text=heading,
        font=FONT_TITLE, fg=colors["accent"], bg=colors["bg_card"]
    )
    title_lbl.pack(anchor=tk.W, pady=(0, 10))

    for sect_title, body_text in text_blocks:
        card = tk.LabelFrame(
            frame, text=f"  {sect_title}  " if sect_title else "",
            font=FONT_SECTION, fg="#2563eb", bg=colors["bg_card"],
            padx=12, pady=8
        )
        card.pack(fill=tk.X, pady=6)
        b = tk.Label(
            card, text=body_text,
            font=FONT_LABEL, fg=colors["fg"], bg=colors["bg_card"],
            justify=tk.LEFT, wraplength=690
        )
        b.pack(anchor=tk.W, fill=tk.X)

    btn_close = tk.Button(
        frame, text="Close Guide", font=FONT_BTN,
        command=dlg.destroy, padx=14, pady=5, relief=tk.FLAT,
        bg=colors["button"], fg=colors["button_fg"]
    )
    btn_close.pack(anchor=tk.E, pady=(12, 4))


def show_substrate_info(app):
    show_info_dialog(
        app.root, app.colors,
        "Substrate (Base Plate) Engineering Guide",
        "Substrate Base Plate Engineering & Boundary Mechanics Guide",
        [
            ("1. Coordinate Reference Frame & Dimensions (Lx, Ly_base, hz_base)",
             "• Global Origin (0, 0, 0): Located at the bottom-corner of the substrate base plate.\n"
             "• Longitudinal Axis (X): Runs along the length Lx (mm). Deposition toolpath travels along X.\n"
             "• Transverse Axis (Y): Spans the base width Ly_base (mm). Centerline is located at Yc = Ly_base / 2.\n"
             "• Vertical Elevation (Z): Plate thickness hz_base (mm). The substrate top surface and fusion boundary sit at Z = hz_base."),
            ("2. Thermal Conductive Heat Sinking & Biot Number",
             "• Governing Heat Equation: ρ·Cp·(∂T/∂t) = ∇·(k∇T). The substrate acts as the primary heat sink.\n"
             "• Biot Number (Bi = h·Lc/k): For thick plates (Bi << 0.1 internally), 3D conduction dominates over surface convection.\n"
             "• Cooling Gradient: Thicker substrates provide rapid 3D conductive heat extraction away from the weld bead, resulting in steeper cooling rates (higher dT/dt) and narrower heat-affected zones (HAZ)."),
            ("3. Mechanical Bending Rigidity & Warpage Resistance",
             "• Flexural Rigidity D = E·hz_base³ / [12·(1 - ν²)]. Plate bending resistance scales cubically with thickness.\n"
             "• Thin Baseplates (< 8 mm): Undergo significant longitudinal bowing and transverse angular distortion due to weld shrinkage moments.\n"
             "• Thick Baseplates (≥ 12 mm): Strongly resist global out-of-plane distortion but accumulate higher tensile residual stress (up to yield strength σy) across the deposit/substrate fusion interface."),
            ("4. Preheating & Boundary Fixturing Recommendations",
             "• Substrate Preheating: Raising initial substrate temperature (e.g. 100 - 150 °C for steel) decreases cooling rates, lowers peak thermal stress, and mitigates cold cracking.\n"
             "• Clamping Interaction: Fixture springs restrain the plate underside during deposition; releasing clamps simulates post-deposition elastic springback.")
        ]
    )


def show_fusion_info(app):
    show_info_dialog(
        app.root, app.colors,
        "WAAM Deposit Geometry & Fusion Model Guide",
        "Deposit Bead Morphology, Layer Slicing & Fusion Retention Guide",
        [
            ("1. Bead Width (w_bead) & Initial Layer Height (h1)",
             "• Single Bead Width (ty_dep): Transverse width of the deposited track (typically 4.0 - 10.0 mm for GMAW/WAAM).\n"
             "• Layer 1 Height (h_bead): Vertical height of the initial layer deposited directly on the bare substrate plate.\n"
             "• Aspect Ratio (w_bead / h1): Recommended between 1.5 and 3.0. Ratios < 1.5 risk bead humping or collapse; ratios > 3.5 cause excessive lateral spreading."),
            ("2. Remelt / Fusion Retention Physics",
             "• Remelt Ratio (β_remelt): Fraction of preceding layer re-melted by the incoming electric arc (typical range: 0.70 - 0.85, default 0.80).\n"
             "• Subsequent Layer Height Increment: Δh_layer = h_bead · (1.0 - β_remelt). For h_bead = 4.0 mm and β = 0.80, Δh = 0.80 mm (or nominal bead build ~ 1.32 mm with weld overlap).\n"
             "• Physics Impact: High remelt ratios enhance interlayer bonding and reduce lack-of-fusion voids, but reduce build rate and increase heat accumulation."),
            ("3. Bi-Directional Dimensioning Drivers (N_layer vs H_build)",
             "• Strict Bi-Directional Coupling: Either Total Layer Count (N_layer) or Target Wall Height (H_build) can drive the build.\n"
             "• Total Build Height Formula: H_build = h1 + (N_layer - 1) · Δh_layer.\n"
             "• Automatic Synchronization: Typing in either field auto-updates the opposite field without locking entries."),
            ("4. Deposition Scanning Patterns",
             "• Unidirectional: Torch deposits from X=0 to X=Lx on every pass. Leads to uneven height accumulation and end-stop crater build-up.\n"
             "• Bidirectional (Reverse): Torch reverses direction on alternate layers (Layer 1: 0→Lx, Layer 2: Lx→0). Ensures symmetric temperature distribution, uniform wall height, and balanced residual stress.")
        ]
    )


def show_process_info(app):
    show_info_dialog(
        app.root, app.colors,
        "Arc & Energy Process Parameters Guide",
        "Electric Arc Power, Heat Input & Feedstock Kinematics Guide",
        [
            ("1. Electrical Arc Power (P_gross = U · I)",
             "• Welding Current (I_weld): Dictates arc force, penetration depth, and wire burn-off rate (typical: 120 - 280 A).\n"
             "• Welding Voltage (U_weld): Dictates arc length and bead spreading width (typical: 18 - 28 V).\n"
             "• Gross Arc Power: P_gross = U · I [Watts]. For 200 A and 24 V, P_gross = 4800 W."),
            ("2. Arc Thermal Transfer Efficiency (η_arc)",
             "• Net Workpiece Power: P_net = η_arc · U · I [Watts].\n"
             "• GMAW / MIG: η_arc ≈ 0.75 - 0.85 (default 0.80).\n"
             "• GTAW / TIG: η_arc ≈ 0.60 - 0.70.\n"
             "• Plasma Arc: η_arc ≈ 0.65 - 0.75.\n"
             "• Unaccounted energy is lost via arc radiation and droplet spatter."),
            ("3. Net Linear Heat Input (H_net)",
             "• Formula: H_net = (η_arc · U · I) / v_scan [J/mm or kJ/mm].\n"
             "• For P_net = 3840 W and v_scan = 10 mm/s: H_net = 384 J/mm (0.384 kJ/mm).\n"
             "• Metallurgical Significance: Higher linear heat input slows cooling rates (Δt_8/5), coarsens austenite grain size, increases dendrite arm spacing, and elevates angular distortion."),
            ("4. Wire Feedstock Kinematics & Deposition Rate",
             "• Wire Feed Speed (v_wire): Governs volumetric mass deposition rate (typical: 3.0 - 8.0 m/min).\n"
             "• Wire Diameter (d_wire): Standard feedstock wire diameter (typical: 1.0 or 1.2 mm).\n"
             "• Mass Deposition Rate: ṁ = ρ_wire · (π·d_wire² / 4) · v_wire · 3600 [kg/h].")
        ]
    )


def show_heatsource_info(app):
    show_info_dialog(
        app.root, app.colors,
        "Analytical Heat Source Models Guide",
        "Volumetric & Surface Heat Source Formulations Guide",
        [
            ("1. Goldak Double-Ellipsoid Heat Source (Standard Arc/WAAM)",
             "• Formulation: Combines two semi-ellipsoids with shared semi-axes b (half-width) and c (depth):\n"
             "  Front (x > 0): q_f(x,y,z) = [6√3·f_f·Q / (π√π·af·b·c)] · exp(-3x²/af² - 3y²/b² - 3z²/c²)\n"
             "  Rear (x < 0):  q_r(x,y,z) = [6√3·f_r·Q / (π√π·ar·b·c)] · exp(-3x²/ar² - 3y²/b² - 3z²/c²)\n"
             "• Power Distribution: f_f + f_r = 2.0 (typical: f_f = 0.60, f_r = 1.40).\n"
             "• Recommended Dimensions: af ≈ 0.8 · w_bead, ar ≈ 2.0 · w_bead, b ≈ 0.5 · w_bead, c ≈ h_bead."),
            ("2. P48 Dual-Component Arc + Droplet Impingement",
             "• Component 1 (Surface Gaussian Arc Flux): Delivers ~60% of power to the top surface via electron/plasma conduction.\n"
             "• Component 2 (Volumetric Droplet Transfer): Transports ~40% of power via superheated liquid metal droplets directly into the weld pool root.\n"
             "• Physical Fidelity: Accurately reproduces deep finger penetration characteristic of GMAW spray transfer."),
            ("3. Gaussian Volumetric & Surface Models",
             "• 3D Cylindrical Gaussian: q(r,z) = [3Q / (π·r0²·H)] · exp(-3r²/r0²) with uniform or linear depth decay.\n"
             "• 2D Surface Gaussian: q(r) = [3Q / (π·r0²)] · exp(-3r²/r0²), optimal for laser beam deposition or thin foils."),
            ("4. Conical Frustum & Uniform Band",
             "• Conical Frustum: Linearly tapering Gaussian radius r(z) from top surface to root, suitable for plasma keyhole welding.\n"
             "• Uniform Moving Band: Homogenized rectangular heat flux for wide weaving passes or high-speed oscillating torches.")
        ]
    )


def show_material_info(app):
    show_info_dialog(
        app.root, app.colors,
        "Alloy Metallurgy & Multi-Material Guide",
        "Constitutional Metallurgy & Dissimilar Alloy Transitions Guide",
        [
            ("1. Substrate vs Deposit Alloy Selection",
             "• Single Alloy: Identical base plate and deposit metal (e.g. SS316L on SS316L).\n"
             "• Dissimilar Alloys: Structural steel substrate (e.g. S355 / ER70S-6) with corrosion-resistant deposit (e.g. SS308L / SS316L / Inconel 625).\n"
             "• Multi-Material Zones: Graded functional transitions across layers (e.g. Zone 1: Inconel 625, Zone 2: SS316L)."),
            ("2. Interfacial Thermal Expansion Mismatch & Residual Stress",
             "• CTE Difference: Δα = α_dep - α_sub.\n"
             "• Interfacial Shear Stress: σ_int ≈ [E_dep / (1 - ν)] · Δα · (T_interpass - T_amb).\n"
             "• When depositing austenitic stainless steel (α ≈ 18e-6 K⁻¹) on carbon steel (α ≈ 12e-6 K⁻¹), large tensile stresses develop at the fusion boundary, promoting interfacial shear and potential debonding."),
            ("3. Constitutional Metallurgy & Ferrite Number (WRC-1992)",
             "• Chromium Equivalent: Cr_eq = Cr + Mo + 1.5·Si + 0.5·Nb.\n"
             "• Nickel Equivalent: Ni_eq = Ni + 30·C + 30·N + 0.5·Mn.\n"
             "• Primary Ferrite Solidification: Target Ferrite Number (FN = 4 - 12) prevents solidification hot-cracking while maintaining ductility and toughness.")
        ]
    )


def show_physics_info(app):
    show_info_dialog(
        app.root, app.colors,
        "Multi-Physics Module Coupling Guide",
        "Governing Thermo-Mechanical-Metallurgical Field Equations Guide",
        [
            ("1. Transient Thermal Conduction Field",
             "• Equation: ρ·Cp·(∂T/∂t) = ∇·(k∇T) + q_vol(x,y,z,t).\n"
             "• Evaluates temperature history T(x,y,z,t) across active elements activated via element birth-and-death."),
            ("2. Non-Linear Thermo-Elasto-Plastic Mechanics",
             "• Equilibrium: ∇·σ + b = 0, where b = -ρ·g·k̂ represents gravitational body force.\n"
             "• Total Strain Decomposition: ε = ε_e + ε_p + ε_th.\n"
             "• Thermal Strain: ε_th = α(T)·(T - T_ref)·I.\n"
             "• J2 Associative Plasticity: von Mises yield surface f = σ_eq - σ_y(T) ≤ 0 with isotropic hardening."),
            ("3. Annealing & Stress Relaxation at Fusion Temperatures",
             "• Molten metal above solidus (T > T_sol) loses plastic strain history (ε_p is reset to zero).\n"
             "• Liquid elements are assigned a bounded compliant stiffness to prevent matrix singularity while transmitting zero unphysical residual stress.")
        ]
    )


def show_ultrasonic_info(app):
    show_info_dialog(
        app.root, app.colors,
        "Ultrasonic Vibration Assistance (UVA-WAAM) Guide",
        "Acoustic Cavitation, Streaming & Grain Refinement Guide",
        [
            ("1. Ultrasonic Vibration Assistance (UVA) Principles",
             "• High-frequency acoustic waves (20 - 40 kHz) applied to the substrate or wire promote acoustic cavitation and acoustic streaming in the molten weld pool.\n"
             "• Acoustic streaming disrupts columnar dendritic growth, promoting equiaxed grain refinement and suppressing hot-cracking."),
            ("2. Blaha Effect & Acoustic Softening",
             "• Static yield strength is reduced by ultrasonic energy absorption (acoustic softening multiplier).\n"
             "• Accelerates dislocation glide and relieves thermal contraction stresses during solidification."),
            ("3. Enhanced Pool Convection",
             "• Effective thermal dispersion (k_stream) flattens peak pool temperature gradients and broadens the weld bead shape.")
        ]
    )


def show_solve_cadence_info(app):
    """Display an engineering guide explaining structural solve cadence and trade-offs."""
    dlg = tk.Toplevel(app.root)
    dlg.title("Structural Solve Cadence & Equilibrium Guide")
    dlg.geometry("760x640")
    dlg.minsize(680, 500)
    dlg.transient(app.root)
    dlg.grab_set()

    canvas = tk.Canvas(dlg, highlightthickness=0, bg=app.colors["bg_card"])
    scroll = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
    frame = tk.Frame(canvas, bg=app.colors["bg_card"], padx=18, pady=14)
    frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    cw = canvas.create_window((0, 0), window=frame, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    title = tk.Label(
        frame, text="Structural Solve Cadence & Equilibrium Guide",
        font=FONT_TITLE, fg=app.colors["accent"], bg=app.colors["bg_card"]
    )
    title.pack(anchor=tk.W, pady=(0, 8))

    intro_text = (
        "Solve Cadence defines the coupling frequency between the transient thermal "
        "conduction field T(x, y, z, t) and the non-linear thermo-elasto-plastic mechanical "
        "equilibrium solver K·u = F_th.\n\n"
        "Because non-linear J₂ plasticity with isotropic hardening requires iterative "
        "Newton-Raphson equilibrium iterations at every evaluation, solving mechanics at "
        "every thermal time step can be computationally demanding. The simulator "
        "provides three calibrated cadence strategies:"
    )
    tk.Label(
        frame, text=intro_text, font=FONT_LABEL, fg=app.colors["fg"],
        bg=app.colors["bg_card"], justify=tk.LEFT, wraplength=690
    ).pack(anchor=tk.W, pady=(0, 10))

    cadences = [
        ("1. 'interpass' (Inter-Pass Cadence — Once per Layer)",
         "• Mechanism: Structural equilibrium is evaluated once at the completion of each deposit layer.\n"
         "• Performance: 5x to 15x faster than continuous solve.\n"
         "• Best For: Large multi-layer walls, fast macro-distortion predictions, overall substrate warpage, "
         "and final unconstrained springback estimation.\n"
         "• Physics Assumption: Elastic-plastic strain accumulates during high-speed bead travel and relaxes at dwell."),

        ("2. 'layer_n' (Every N Weld Steps Cadence)",
         "• Mechanism: Structural mechanics runs periodically every N thermal time increments (e.g. N = 5 steps).\n"
         "• Performance: 2x to 5x faster with minimal loss of accuracy.\n"
         "• Best For: Capturing transient thermal shock waves and gradual bending accumulation during long weld passes "
         "without paying the penalty of full step-by-step solving."),

        ("3. 'weld' (Continuous Every Step — Abaqus / ANSYS Benchmark)",
         "• Mechanism: Structural equilibrium is solved at EVERY single deposition time increment Δt_weld.\n"
         "• Performance: Computationally demanding (1x baseline).\n"
         "• Best For: Rigorous academic research, thin-wall hot cracking assessment, transient stress reversal, "
         "and high-fidelity experimental strain gauge validation.")
    ]

    for head, body in cadences:
        box = tk.LabelFrame(frame, text=f"  {head}  ", font=FONT_SECTION, bg=app.colors["bg_card"],
                            fg=app.colors["accent2"], padx=12, pady=8)
        box.pack(fill=tk.X, pady=6)
        tk.Label(box, text=body, font=FONT_LABEL, fg=app.colors["fg"],
                 bg=app.colors["bg_card"], justify=tk.LEFT, wraplength=670).pack(anchor=tk.W)

    btn_close = tk.Button(
        frame, text="Close Guide", font=FONT_BTN, bg=app.colors["button"],
        fg=app.colors["button_fg"], command=dlg.destroy, padx=14, pady=5,
        relief=tk.FLAT, bd=0
    )
    btn_close.pack(anchor=tk.E, pady=(12, 4))

