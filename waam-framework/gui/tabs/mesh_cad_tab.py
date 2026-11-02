#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Mesh & CAD Tab
Modular tab for Mesh source, CAD file selector, Gmsh sizing, and toolpath slicer.
"""

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION, FONT_MONO, FONT_BTN
)
from gui.tabs.base import reg_widget, make_param_row, add_info_button, create_scrollable_container


def build_mesh_cad_tab(app):
    """Build the Mesh & CAD tab in app.notebook."""
    tab = tk.Frame(app.notebook)
    app.notebook.add(tab, text="Mesh")
    reg_widget(app, tab, "card_frame")

    # Scrollable container for Mesh tab
    canvas, scroll_content = create_scrollable_container(tab, app.colors.get("bg_card", "#ffffff"))
    app.mesh_canvas = canvas

    # 1. Geometry Source & CAD / Toolpath Pipeline
    lf1 = tk.LabelFrame(scroll_content, text="Geometry & CAD Source Pipeline", font=FONT_SECTION, padx=8, pady=3)
    lf1.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf1, "card_labelframe")
    add_info_button(app, lf1, app._show_mesh_info)

    app.mesh_source_var = tk.StringVar(value="parametric")
    sources = [
        ("parametric", "Parametric Straight Wall (Structured Hex/Tet Domain with Conforming Interface)"),
        ("cad_file", "Import 3D CAD (.stl, .step, .stp, .iges, .igs via Gmsh 4.15 & OCCT)"),
        ("gcode_file", "Import G-code Toolpath (.gcode, .nc)"),
    ]
    for i, (val, text) in enumerate(sources):
        rb = tk.Radiobutton(
            lf1, text=text, variable=app.mesh_source_var, value=val,
            font=FONT_SMALL, command=app._update_mesh_ui
        )
        rb.grid(row=i, column=0, sticky=tk.W, padx=4, pady=1)
        reg_widget(app, rb, "radio")

    app.file_picker_frame = tk.Frame(lf1)
    app.file_picker_frame.grid(row=3, column=0, sticky=tk.EW, padx=4, pady=3)
    reg_widget(app, app.file_picker_frame, "card_frame")

    app.mesh_file_var = tk.StringVar()
    entry = tk.Entry(app.file_picker_frame, textvariable=app.mesh_file_var, width=32, font=FONT_MONO, relief=tk.SOLID, bd=1)
    entry.pack(side=tk.LEFT, padx=3)
    reg_widget(app, entry, "entry")

    btn = tk.Button(app.file_picker_frame, text="Browse CAD...", command=app._browse_mesh_file, font=FONT_SMALL_BOLD, padx=4)
    btn.pack(side=tk.LEFT, padx=2)
    reg_widget(app, btn, "button")

    import_stl_btn = tk.Button(
        app.file_picker_frame, text="Import & Mesh CAD",
        command=app._import_stl, font=FONT_SMALL_BOLD,
        padx=4
    )
    import_stl_btn.pack(side=tk.LEFT, padx=2)
    reg_widget(app, import_stl_btn, "button")

    view_3d_btn = tk.Button(
        app.file_picker_frame, text="View 3D",
        command=app._open_3d_mesh_viewer, font=FONT_SMALL_BOLD,
        padx=4
    )
    view_3d_btn.pack(side=tk.LEFT, padx=2)
    reg_widget(app, view_3d_btn, "button")

    # Quick Load CAD Samples Row
    quick_frame = tk.Frame(lf1)
    quick_frame.grid(row=4, column=0, sticky=tk.W, padx=4, pady=(2, 3))
    reg_widget(app, quick_frame, "card_frame")

    tk.Label(quick_frame, text="Quick Load Sample CAD:", font=FONT_SMALL_BOLD).pack(side=tk.LEFT, padx=(0, 4))
    reg_widget(app, quick_frame.winfo_children()[-1], "label")

    # Sample files were renamed over time (letter_Z_WAAM.stl -> z.stl): resolve
    # the first candidate that actually exists so the button never dead-ends.
    _stl_dir = Path(__file__).resolve().parent.parent.parent / "stl"
    _z_sample = next(
        (str(_stl_dir / n) for n in ("letter_Z_WAAM.stl", "z.stl", "Main.stl", "main.stl")
         if (_stl_dir / n).exists()),
        str(_stl_dir / "z.stl"),
    )
    sample_z_path = _z_sample
    sample_sphere_path = str(Path(__file__).resolve().parent.parent.parent / "stl" / "sphere_R40mm.stl")

    btn_sample_z = tk.Button(
        quick_frame, text=f"Load {Path(sample_z_path).name}", font=FONT_SMALL,
        command=lambda: app._load_sample_cad(sample_z_path), padx=4
    )
    btn_sample_z.pack(side=tk.LEFT, padx=2)
    reg_widget(app, btn_sample_z, "button")

    btn_sample_sphere = tk.Button(
        quick_frame, text="Load sphere_R40mm.stl", font=FONT_SMALL,
        command=lambda: app._load_sample_cad(sample_sphere_path), padx=4
    )
    btn_sample_sphere.pack(side=tk.LEFT, padx=2)
    reg_widget(app, btn_sample_sphere, "button")

    btn_browse_sample = tk.Button(
        quick_frame, text="Browse Custom CAD File...", font=FONT_SMALL,
        command=lambda: app._browse_mesh_file(), padx=4
    )
    btn_browse_sample.pack(side=tk.LEFT, padx=2)
    reg_widget(app, btn_browse_sample, "button")

    app.cad_info_label = tk.Label(
        lf1, text="No external CAD model loaded. Using parametric straight wall geometry.",
        font=FONT_MONO, fg="#64748b", justify=tk.LEFT, anchor=tk.W
    )
    app.cad_info_label.grid(row=5, column=0, sticky=tk.W, padx=4, pady=(1, 3))
    reg_widget(app, app.cad_info_label, "label_dim")

    # 2. Customizable WAAM G-Code Slicer & Toolpath Planning
    lf_slicer = tk.LabelFrame(scroll_content, text="Synchronized Toolpath Planning & G-Code Slicer", font=FONT_SECTION, padx=8, pady=4)
    lf_slicer.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_slicer, "card_labelframe")
    add_info_button(app, lf_slicer, app._show_mesh_info)

    s_row1 = tk.Frame(lf_slicer)
    s_row1.pack(fill=tk.X, pady=2)
    reg_widget(app, s_row1, "card_frame")

    tk.Label(s_row1, text="Layer Height (h):", font=FONT_SMALL).pack(side=tk.LEFT, padx=2)
    reg_widget(app, s_row1.winfo_children()[-1], "label")
    init_h = app._param_vars.get("h_bead", (tk.StringVar(value="3.0"),))[0].get() or "3.0"
    app.slicer_h_var = tk.StringVar(value=init_h)
    e_sh = tk.Entry(s_row1, textvariable=app.slicer_h_var, width=6, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_sh.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_sh, "entry")
    app.slicer_h_var.trace_add("write", app._on_slicer_h_change)
    tk.Label(s_row1, text="mm [⇄ Geom]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=1)

    tk.Label(s_row1, text="Bead Width (w):", font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
    reg_widget(app, s_row1.winfo_children()[-1], "label")
    init_w = app._param_vars.get("ty_dep", (tk.StringVar(value="5.0"),))[0].get() or "5.0"
    app.slicer_w_var = tk.StringVar(value=init_w)
    e_sw = tk.Entry(s_row1, textvariable=app.slicer_w_var, width=6, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_sw.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_sw, "entry")
    app.slicer_w_var.trace_add("write", app._on_slicer_w_change)
    tk.Label(s_row1, text="mm [⇄ Geom]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=1)

    tk.Label(s_row1, text="Bead Overlap:", font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
    reg_widget(app, s_row1.winfo_children()[-1], "label")
    app.slicer_overlap_var = tk.StringVar(value="75.0")
    e_so = tk.Entry(s_row1, textvariable=app.slicer_overlap_var, width=5, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_so.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_so, "entry")
    tk.Label(s_row1, text="%", font=FONT_SMALL).pack(side=tk.LEFT, padx=1)

    tk.Label(s_row1, text="Wall Perimeters:", font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
    reg_widget(app, s_row1.winfo_children()[-1], "label")
    app.slicer_perim_var = tk.StringVar(value="3")
    e_sp = tk.Entry(s_row1, textvariable=app.slicer_perim_var, width=4, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_sp.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_sp, "entry")
    tk.Label(s_row1, text="loops", font=FONT_SMALL).pack(side=tk.LEFT, padx=1)

    s_row2 = tk.Frame(lf_slicer)
    s_row2.pack(fill=tk.X, pady=2)
    reg_widget(app, s_row2, "card_frame")

    tk.Label(s_row2, text="Infill Pattern:", font=FONT_SMALL).pack(side=tk.LEFT, padx=2)
    reg_widget(app, s_row2.winfo_children()[-1], "label")

    init_pat = "contour" if getattr(app, "deposition_pattern_var", tk.StringVar()).get() in ("contour", "contour_infill") else "contour"
    app.slicer_pattern_var = tk.StringVar(value=init_pat)
    pattern_cb = ttk.Combobox(
        s_row2, textvariable=app.slicer_pattern_var, width=22,
        values=["contour", "concentric", "zigzag", "lines", "grid", "triangles", "hollow", "unidirectional", "meander", "crosshatch"],
        state="readonly"
    )
    pattern_cb.pack(side=tk.LEFT, padx=3)
    app.slicer_pattern_var.trace_add("write", app._on_slicer_pattern_change)
    tk.Label(s_row2, text="[⇄ Geom Pattern]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=1)

    app.slicer_reverse_var = tk.BooleanVar(value=True)
    cb_rev = tk.Checkbutton(
        s_row2, text="Bi-Directional Start Reversal (Prevents End Bulge)",
        variable=app.slicer_reverse_var, font=FONT_SMALL
    )
    cb_rev.pack(side=tk.LEFT, padx=6)
    reg_widget(app, cb_rev, "check")

    s_row3 = tk.Frame(lf_slicer)
    s_row3.pack(fill=tk.X, pady=2)
    reg_widget(app, s_row3, "card_frame")

    tk.Label(s_row3, text="Weld Feedrate:", font=FONT_SMALL).pack(side=tk.LEFT, padx=2)
    reg_widget(app, s_row3.winfo_children()[-1], "label")
    v_scan_val = float(app._param_vars.get("v_scan", (tk.StringVar(value="8.0"),))[0].get() or "8.0")
    v_scan_mms = v_scan_val if v_scan_val > 0.05 else v_scan_val * 1000.0
    app.slicer_feedrate_var = tk.StringVar(value=f"{v_scan_mms * 60.0:.1f}")
    e_sf = tk.Entry(s_row3, textvariable=app.slicer_feedrate_var, width=6, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_sf.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_sf, "entry")
    app.slicer_feedrate_var.trace_add("write", app._on_slicer_feedrate_change)
    tk.Label(s_row3, text="mm/min [⇄ v_scan]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=1)

    tk.Label(s_row3, text="Rapid Travel:", font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
    reg_widget(app, s_row3.winfo_children()[-1], "label")
    app.slicer_rapid_var = tk.StringVar(value="3000.0")
    e_sr = tk.Entry(s_row3, textvariable=app.slicer_rapid_var, width=6, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_sr.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_sr, "entry")
    tk.Label(s_row3, text="mm/min", font=FONT_SMALL).pack(side=tk.LEFT, padx=1)

    tk.Label(s_row3, text="Inter-Layer Dwell:", font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
    reg_widget(app, s_row3.winfo_children()[-1], "label")
    init_dw = app._param_vars.get("t_wait", (tk.StringVar(value="10.0"),))[0].get() or "10.0"
    app.slicer_dwell_var = tk.StringVar(value=init_dw)
    e_sd = tk.Entry(s_row3, textvariable=app.slicer_dwell_var, width=5, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_sd.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_sd, "entry")
    app.slicer_dwell_var.trace_add("write", app._on_slicer_dwell_change)
    tk.Label(s_row3, text="s [⇄ t_wait]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=1)

    tk.Label(s_row3, text="Arc Power:", font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
    reg_widget(app, s_row3.winfo_children()[-1], "label")
    u_init = float(app._param_vars.get("U_weld", (tk.StringVar(value="20.0"),))[0].get() or "20.0")
    i_init = float(app._param_vars.get("I_weld", (tk.StringVar(value="180.0"),))[0].get() or "180.0")
    app.slicer_power_var = tk.StringVar(value=f"{u_init * i_init:.1f}")
    e_spw = tk.Entry(s_row3, textvariable=app.slicer_power_var, width=6, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_spw.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_spw, "entry")
    app.slicer_power_var.trace_add("write", app._on_slicer_power_change)
    tk.Label(s_row3, text="W [⇄ U·I]", font=FONT_SMALL_BOLD, fg="#2563eb").pack(side=tk.LEFT, padx=1)

    s_row4 = tk.Frame(lf_slicer)
    s_row4.pack(fill=tk.X, pady=(4, 2))
    reg_widget(app, s_row4, "card_frame")

    slice_btn = tk.Button(
        s_row4, text="Slice CAD to G-Code Toolpath",
        font=FONT_SMALL_BOLD, command=app._execute_custom_slicer,
        padx=8, pady=2
    )
    slice_btn.pack(side=tk.LEFT, padx=2)
    reg_widget(app, slice_btn, "button")

    app.slicer_summary_label = tk.Label(
        s_row4, text="Slicer Ready. Configure bead parameters and click Slice.",
        font=FONT_MONO, fg="#0d6efd", justify=tk.LEFT, anchor=tk.W
    )
    app.slicer_summary_label.pack(side=tk.LEFT, padx=8)
    reg_widget(app, app.slicer_summary_label, "label")

    # 3. WAAM Discretization Engine
    lf_discretize = tk.LabelFrame(scroll_content, text="WAAM Discretization Engine & Sizing", font=FONT_SECTION, padx=8, pady=4)
    lf_discretize.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_discretize, "card_labelframe")
    add_info_button(app, lf_discretize, app._show_mesh_info)

    mode_bar = tk.Frame(lf_discretize)
    mode_bar.pack(fill=tk.X, pady=(2, 6))
    reg_widget(app, mode_bar, "card_frame")

    tk.Label(mode_bar, text="Discretization Mode (OR):", font=FONT_SMALL_BOLD).pack(side=tk.LEFT, padx=(0, 8))
    reg_widget(app, mode_bar.winfo_children()[-1], "label")

    app.mesh_discretize_mode_var = tk.StringVar(value="auto_rule")
    for m_val, m_lbl in [
        ("auto_rule", "Auto-Mesh Engine (Physics & Heat-Source Adaptive)"),
        ("by_size", "Define by Element Size (dx, dy, dz)"),
        ("by_counts", "Define by Division Counts (Nx, Ny, Nz)"),
    ]:
        rb = tk.Radiobutton(
            mode_bar, text=m_lbl, variable=app.mesh_discretize_mode_var, value=m_val,
            font=FONT_SMALL, command=app._on_discretize_mode_change
        )
        rb.pack(side=tk.LEFT, padx=4)
        reg_widget(app, rb, "radio")

    app.discretize_container = tk.Frame(lf_discretize)
    app.discretize_container.pack(fill=tk.X, pady=2)
    reg_widget(app, app.discretize_container, "card_frame")

    # Mode A: Auto-Mesh Frame
    app.mode_auto_frame = tk.Frame(app.discretize_container)
    reg_widget(app, app.mode_auto_frame, "card_frame")

    strat_frame = tk.Frame(app.mode_auto_frame)
    strat_frame.pack(fill=tk.X, pady=2)
    reg_widget(app, strat_frame, "card_frame")

    tk.Label(strat_frame, text="Rule Strategy:", font=FONT_SMALL_BOLD).pack(side=tk.LEFT, padx=(0, 4))
    reg_widget(app, strat_frame.winfo_children()[-1], "label")

    app.mesh_strategy_var = tk.StringVar(value="physics_adaptive")
    for s_val, s_lbl in [
        ("physics_adaptive", "Physics-Adaptive (65% HAZ Meltpool / 35% Bulk, AR <= 2.0)"),
        ("equal_aspect", "Equal-Aspect Voxel (dx ~ dy ~ dz Isotropic)"),
        ("feature_adaptive", "CAD Feature & Curvature Adaptive"),
    ]:
        rb = tk.Radiobutton(
            strat_frame, text=s_lbl, variable=app.mesh_strategy_var, value=s_val,
            font=FONT_SMALL, command=app._auto_enforce_node_budget
        )
        rb.pack(side=tk.LEFT, padx=3)
        reg_widget(app, rb, "radio")

    budget_bar = tk.Frame(app.mode_auto_frame)
    budget_bar.pack(fill=tk.X, pady=2)
    reg_widget(app, budget_bar, "card_frame")

    tk.Label(budget_bar, text="Target Budget:", font=FONT_SMALL_BOLD).pack(side=tk.LEFT, padx=(0, 4))
    reg_widget(app, budget_bar.winfo_children()[-1], "label")

    app.mesh_budget_var = tk.StringVar(value="2500")
    for b_val, b_lbl in [
        ("1500", "Fast (~1,500)"),
        ("2500", "Balanced (~2,500)"),
        ("5000", "High-Res (~5,000)"),
    ]:
        rb = tk.Radiobutton(
            budget_bar, text=b_lbl, variable=app.mesh_budget_var, value=b_val,
            font=FONT_SMALL, command=app._auto_enforce_node_budget
        )
        rb.pack(side=tk.LEFT, padx=3)
        reg_widget(app, rb, "radio")

    tk.Label(budget_bar, text="Custom:", font=FONT_SMALL).pack(side=tk.LEFT, padx=(6, 2))
    reg_widget(app, budget_bar.winfo_children()[-1], "label")
    e_custom_b = tk.Entry(budget_bar, textvariable=app.mesh_budget_var, width=6, font=FONT_MONO, relief=tk.SOLID, bd=1)
    e_custom_b.pack(side=tk.LEFT, padx=2)
    reg_widget(app, e_custom_b, "entry")

    auto_btn = tk.Button(
        budget_bar, text="⚡ Calculate Auto-Mesh Grid", font=FONT_SMALL_BOLD,
        command=app._auto_enforce_node_budget, padx=8, pady=2
    )
    auto_btn.pack(side=tk.RIGHT, padx=3)
    reg_widget(app, auto_btn, "button")

    # Mode B: Define by Element Size Frame
    app.mode_size_frame = tk.Frame(app.discretize_container)
    reg_widget(app, app.mode_size_frame, "card_frame")

    size_dep_row = tk.Frame(app.mode_size_frame)
    size_dep_row.pack(fill=tk.X, pady=2)
    reg_widget(app, size_dep_row, "card_frame")

    tk.Label(size_dep_row, text="Deposit Sizes:", font=FONT_SMALL_BOLD).pack(side=tk.LEFT, padx=(0, 4))
    reg_widget(app, size_dep_row.winfo_children()[-1], "label")

    app.target_dx_var = tk.StringVar(value="4.0")
    app.target_dy_var = tk.StringVar(value="1.33")
    app.target_dz_var = tk.StringVar(value="1.5")

    for axis_name, axis_var in [("dx:", app.target_dx_var), ("dy:", app.target_dy_var), ("dz (≤ h/2):", app.target_dz_var)]:
        tk.Label(size_dep_row, text=axis_name, font=FONT_SMALL).pack(side=tk.LEFT, padx=2)
        e = tk.Entry(size_dep_row, textvariable=axis_var, width=5, font=FONT_MONO, relief=tk.SOLID, bd=1)
        e.pack(side=tk.LEFT, padx=2)
        reg_widget(app, e, "entry")
        tk.Label(size_dep_row, text="mm", font=FONT_SMALL).pack(side=tk.LEFT, padx=(1, 6))

    size_base_row = tk.Frame(app.mode_size_frame)
    size_base_row.pack(fill=tk.X, pady=2)
    reg_widget(app, size_base_row, "card_frame")

    tk.Label(size_base_row, text="Substrate Sizes:", font=FONT_SMALL_BOLD).pack(side=tk.LEFT, padx=(0, 4))
    reg_widget(app, size_base_row.winfo_children()[-1], "label")

    app.base_dx_var = tk.StringVar(value="5.0")
    app.base_dy_var = tk.StringVar(value="7.5")
    app.base_dz_var = tk.StringVar(value="1.0")

    for axis_name, axis_var in [("dx:", app.base_dx_var), ("dy:", app.base_dy_var), ("dz:", app.base_dz_var)]:
        tk.Label(size_base_row, text=axis_name, font=FONT_SMALL).pack(side=tk.LEFT, padx=2)
        e = tk.Entry(size_base_row, textvariable=axis_var, width=5, font=FONT_MONO, relief=tk.SOLID, bd=1)
        e.pack(side=tk.LEFT, padx=2)
        reg_widget(app, e, "entry")
        tk.Label(size_base_row, text="mm", font=FONT_SMALL).pack(side=tk.LEFT, padx=(1, 6))

    apply_size_btn = tk.Button(
        size_base_row, text="Apply Element Sizes", font=FONT_SMALL_BOLD,
        command=app._apply_element_size_to_divisions, padx=6
    )
    apply_size_btn.pack(side=tk.LEFT, padx=6)
    reg_widget(app, apply_size_btn, "button")

    # Mode C: Define by Division Counts Frame
    app.mode_counts_frame = tk.LabelFrame(
        app.discretize_container, text="Mesh Division Counts (Nx, Ny, Nz)", font=FONT_SMALL_BOLD
    )
    reg_widget(app, app.mode_counts_frame, "card_frame")
    app.mesh_divisions_frame = app.mode_counts_frame

    make_param_row(app, app.mode_counts_frame, "Deposit Elements X (Nx_dep):", "nx_dep", 0, "divisions", type_="int")
    make_param_row(app, app.mode_counts_frame, "Deposit Elements Y (Ny_dep):", "ny_dep", 1, "divisions (≥ 4 across bead)", type_="int")
    make_param_row(app, app.mode_counts_frame, "Deposit Elements Z (Nz_dep):", "nz_dep", 2, "divisions (≥ 2 × n_layers)", type_="int")
    make_param_row(app, app.mode_counts_frame, "Substrate Elements X (Nx_base):", "nx_base", 3, "divisions", type_="int")
    make_param_row(app, app.mode_counts_frame, "Substrate Elements Y (Ny_base):", "ny_base", 4, "divisions", type_="int")
    make_param_row(app, app.mode_counts_frame, "Substrate Elements Z (Nz_base):", "nz_base", 5, "divisions", type_="int")

    apply_counts_btn = tk.Button(
        app.mode_counts_frame, text="Apply Division Counts to Sizes", font=FONT_SMALL_BOLD,
        command=app._apply_division_counts_to_sizes, padx=6
    )
    apply_counts_btn.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=4, pady=3)
    reg_widget(app, apply_counts_btn, "button")

    # Initialize display to Mode A
    app.mode_auto_frame.pack(fill=tk.X, pady=2)

    # 4. Mesh Quality & Standards
    lf_quality = tk.LabelFrame(scroll_content, text="Mesh Quality & Heat-Source Resolvability Standards", font=FONT_SECTION, padx=8, pady=4)
    lf_quality.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_quality, "card_labelframe")
    add_info_button(app, lf_quality, app._show_mesh_info)

    app.quality_frame = tk.Frame(lf_quality)
    app.quality_frame.pack(fill=tk.X, pady=2)
    reg_widget(app, app.quality_frame, "card_frame")

    app.quality_rule1_lbl = tk.Label(app.quality_frame, text="• Rule 1 [Layer Resolution]: —", font=FONT_SMALL_BOLD, justify=tk.LEFT, anchor=tk.W)
    app.quality_rule1_lbl.pack(fill=tk.X, padx=4, pady=1)

    app.quality_rule2_lbl = tk.Label(app.quality_frame, text="• Rule 2 [Bead Width Resolution]: —", font=FONT_SMALL_BOLD, justify=tk.LEFT, anchor=tk.W)
    app.quality_rule2_lbl.pack(fill=tk.X, padx=4, pady=1)

    app.quality_rule3_lbl = tk.Label(app.quality_frame, text="• Rule 3 [Goldak Heat Source Resolvability]: —", font=FONT_SMALL_BOLD, justify=tk.LEFT, anchor=tk.W)
    app.quality_rule3_lbl.pack(fill=tk.X, padx=4, pady=1)

    app.quality_rule4_lbl = tk.Label(app.quality_frame, text="• Rule 4 [Aspect Ratio Metric]: —", font=FONT_SMALL_BOLD, justify=tk.LEFT, anchor=tk.W)
    app.quality_rule4_lbl.pack(fill=tk.X, padx=4, pady=1)

    q_btn_bar = tk.Frame(lf_quality)
    q_btn_bar.pack(fill=tk.X, pady=(4, 2))
    reg_widget(app, q_btn_bar, "card_frame")

    app.btn_autofix_mesh = tk.Button(
        q_btn_bar, text="⚡ Auto-Fix Mesh to Standards (dz <= h/2, AR <= 2.0, Goldak Resolved)",
        font=FONT_SMALL_BOLD, command=app._auto_fix_mesh_rules, padx=8, pady=2
    )
    app.btn_autofix_mesh.pack(side=tk.LEFT, padx=4)
    reg_widget(app, app.btn_autofix_mesh, "button")

    app.mesh_calc_label = tk.Label(
        lf_quality, text="—", font=FONT_MONO, justify=tk.LEFT, anchor=tk.W
    )
    app.mesh_calc_label.pack(fill=tk.X, padx=4, pady=(4, 2))
    reg_widget(app, app.mesh_calc_label, "label")

    # 5. Bottom Action Buttons
    lf_actions = tk.Frame(scroll_content)
    lf_actions.pack(fill=tk.X, padx=8, pady=(8, 12))
    reg_widget(app, lf_actions, "card_frame")

    app.btn_generate_mesh = tk.Button(
        lf_actions, text="⚡ Generate & Validate WAAM Volume Mesh",
        font=FONT_BTN, command=app._generate_waam_mesh, padx=12, pady=6,
        bg="#2563eb", fg="#ffffff", activebackground="#1d4ed8"
    )
    app.btn_generate_mesh.pack(side=tk.LEFT, padx=4)
    reg_widget(app, app.btn_generate_mesh, "primary_button")

    preview_btn = tk.Button(
        lf_actions, text="Interactive 3D Mesh Preview (Rotate / Pan / Zoom)",
        font=FONT_BTN, command=app._open_3d_mesh_viewer, padx=10, pady=6
    )
    preview_btn.pack(side=tk.LEFT, padx=6)
    reg_widget(app, preview_btn, "button")

    app._update_mesh_ui()
    return tab


"""
================================================================================
MESH & CAD TAB — ARCHITECTURAL SPECIFICATION & FORMULATION
================================================================================

1. Mathematical & Physical Formulation
--------------------------------------
The Mesh & CAD Tab dictates spatial spatial discretization, element topology, metric
quality bounds, and CAD geometry ingestion for finite element analysis.

  a. Structured Graded Parametric Mesh (Split-Tetrahedra):
     Generates conformal 3D brick topologies split into 6 tetrahedra per hexahedron:
       N_elements = 6 · nx · ny · (nz_base + nz_dep)
       N_nodes    = (nx + 1) · (ny + 1) · (nz_base + nz_dep + 1)
     where spatial cell dimensions satisfy:
       Δx = L_x / nx,   Δy = W_sub / ny,   Δz_base = H_sub / nz_base
       Δz_layer = h_bead / nz_layer

  b. CAD Boundary Representation (B-Rep) & Slicing:
     Ingests arbitrary geometry (.STEP, .IGES, .STL) and applies planar level-set slicing:
       S_k = ∂Ω_CAD ∩ { z = z_k },   z_k = z_sub + k · Δz_layer
     generating 2D polygonal boundary contours for medial-axis / zigzag toolpath synthesis.

  c. Sizing Fields & Delaunay Tetrahedralization (Gmsh 4.x):
     Anisotropic distance-based size field relative to the weld bead trajectory Γ_weld:
       lc(x) = lc_min + (lc_max - lc_min) · min( 1.0, [dist(x, Γ_weld) / R_refine]² )
     guaranteeing sub-millimeter refinement inside the melt pool while coarsening the far-field
     baseplate to minimize total degree-of-freedom (DoF) count.

  d. Mesh Quality & Resolvability Standards (Built-in Rules):
     - Rule 1 [Layer Resolution]:
         Δz_layer ≤ h_bead / 2.0 (Ensures at least 2 quadratic elements across layer thickness
         to prevent artificial shear locking during thermal bending).
     - Rule 2 [Bead Width Resolution]:
         Δy_dep ≤ W_bead / 4.0 (At least 4 elements across transverse bead span).
     - Rule 3 [Goldak Heat Source Resolvability]:
         Δx ≤ a_f / 2.0,   Δy ≤ b_G / 2.0,   Δz ≤ c_G / 2.0
         (Guarantees numerical integration of the exponential Goldak kernel captures ≥ 99.5%
         of total thermal input without spatial aliasing).
     - Rule 4 [Aspect Ratio Metric]:
         AR = max(Δx, Δy, Δz) / min(Δx, Δy, Δz) ≤ 3.0 (Preserves stiffness matrix condition number).

2. Design & Engineering Philosophy
-----------------------------------
  - Two-Click Auto-Fix Standard:
    Clicking "Auto-Fix Mesh to Standards" computes the optimal integer division counts
    (nx, ny, nz) satisfying all 4 mathematical rules simultaneously without manual trial and error.
  - Interactive In-Process 3D Rendering:
    Enables instant inspection of node distribution, surface facet normals, and element
    aspect ratios prior to solver dispatch.

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                       MESH & CAD TAB                        │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. CAD Geometry & Slicer Ingestion                          │
  │    ├── File Selection (.step, .stl, .iges) -> cad_path      │
  │    ├── Slicing Strategy (Adaptive/Uniform) -> slice_mode    │
  │    └── Bounding Box & Part Height Display  -> cad_bbox_info │
  │                                                             │
  │ 2. Mesh Generation Driver Mode                              │
  │    ├── Mode A: Target Element Sizes (mm)   -> auto_sizes    │
  │    │     └── [dx_sub, dy_sub, dz_sub, dx_dep, dy_dep, dz]   │
  │    └── Mode B: Explicit Grid Divisions     -> manual_divs   │
  │          └── [nx, ny, nz_base, ny_dep, nz_layer]            │
  │                                                             │
  │ 3. Mesh Quality & Resolvability Standards                   │
  │    ├── Rule 1: Layer Resolution Banner     -> quality_rule1 │
  │    ├── Rule 2: Bead Width Resolution       -> quality_rule2 │
  │    ├── Rule 3: Goldak Resolvability        -> quality_rule3 │
  │    ├── Rule 4: Aspect Ratio Metric (AR)    -> quality_rule4 │
  │    └── Auto-Fix Mesh Standards Action      -> btn_autofix   │
  │                                                             │
  │ 4. Mesh Generation & 3D Preview Actions                     │
  │    ├── Generate & Validate Mesh (Gmsh)     -> btn_generate  │
  │    └── Open Interactive 3D Mesh Viewer     -> preview_btn   │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  gui/tabs/mesh_cad_tab.py
        │
        ├──► app.params['nx'], ['ny'], ['nz_base'], ['nz_layer']
        │      │
        │      ▼
        │    mesh/box_mesh.py & mesh/gmsh_waam.py
        │      │
        │      ├─► Generates waam_substrate.msh & waam_wall.msh
        │      ├─► Merges conformal nodes along substrate-wall interface
        │      └─► Exports waam_mesh.mesh (MEDIT format for FreeFEM++)
        │
        └──► codegen/edp/builder_core.py
               └── FreeFEM: mesh3 Th = readmesh3("waam_mesh.mesh");

5. Numerical & Physical Impact
------------------------------
  - Violating Rule 3 (Goldak under-resolution) causes severe heat-loss artifacts: the peak
    temperature can be underestimated by 300 - 500 °C if the Gaussian center falls between
    sparse nodes.
  - Proper layer discretization (Rule 1) prevents artificial plastic locking, ensuring
    accurate prediction of longitudinal residual tensile stress (σ_xx) and substrate warping.
"""
