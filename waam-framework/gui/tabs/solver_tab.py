#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Solver Tab
Modular tab for Temporal discretization, adaptive Fo time-stepping, probes, and restart/checkpointing.
"""

import math
import os
import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION, FONT_MONO
)
from gui.tabs.base import reg_widget, make_param_row, add_info_button


def build_solver_tab(app):
    """Build the Solver tab in app.notebook."""
    tab = tk.Frame(app.notebook)
    app.notebook.add(tab, text="Solver")
    reg_widget(app, tab, "card_frame")

    # 1. Temporal Discretization
    lf1 = tk.LabelFrame(tab, text="Temporal Discretization", font=FONT_SECTION, padx=8, pady=4)
    lf1.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf1, "card_labelframe")
    add_info_button(app, lf1, app._show_solver_info)
    make_param_row(app, lf1, "Time Scheme Weight (θ):", "theta", 0, "[-]")
    make_param_row(app, lf1, "Deposition Timestep (Δt_weld):", "dt_weld", 1, "s")
    make_param_row(app, lf1, "Inter-Pass Timestep (Δt_dwell):", "dt_wait", 2, "s")
    make_param_row(app, lf1, "Final Cooling Timestep (Δt_cool):", "dt_cool", 3, "s")
    make_param_row(app, lf1, "Cooling Steps Count (N_cool):", "n_cool_steps", 4, "steps", type_="int")

    # 2. Adaptive Time Stepping
    lf_ada = tk.LabelFrame(tab, text="Adaptive Time Stepping", font=FONT_SECTION, padx=8, pady=4)
    lf_ada.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_ada, "card_labelframe")
    ttk.Label(lf_ada, text="Controller:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
    app.adaptive_dt_var = tk.StringVar(value="off")
    ada_combo = ttk.Combobox(lf_ada, textvariable=app.adaptive_dt_var,
                             state="readonly", width=22, values=["off", "fourier"])
    ada_combo.grid(row=0, column=1, padx=4, pady=2, sticky=tk.W)
    ttk.Label(lf_ada, text="fourier = limit Fo = α·Δt/h² from measured h_min (dt capped so arc resolves source width)",
              foreground="#64748b").grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=4)
    make_param_row(app, lf_ada, "Target Diffusion Number (Fo):", "adaptive_fo_target", 2, "[-]")
    make_param_row(app, lf_ada, "Minimum Δt:", "adaptive_dt_min", 3, "s")
    make_param_row(app, lf_ada, "Maximum Δt:", "adaptive_dt_max", 4, "s")

    # 3. History Output (Probe Points & Paths)
    lf_hist = tk.LabelFrame(tab, text="History Output (Probe Points & Paths)", font=FONT_SECTION, padx=8, pady=4)
    lf_hist.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_hist, "card_labelframe")
    add_info_button(app, lf_hist, app._show_history_output_info)

    app.probe_geom_badge_lbl = tk.Label(
        lf_hist, text="✓ Auto-Linked to Geometry Window Coordinates",
        font=FONT_SMALL_BOLD, fg="#2563eb", bg=app.colors.get("bg_card", "#ffffff")
    )
    app.probe_geom_badge_lbl.grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=4, pady=(2, 6))

    ttk.Label(lf_hist, text="Probe points (mm, one per line, x,y,z):").grid(
        row=1, column=0, sticky=tk.NW, padx=4, pady=2)
    app.probe_points_text = tk.Text(lf_hist, height=5, width=44, font=FONT_MONO)
    app.probe_points_text.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=4)
    app.probe_points_text.insert("1.0", app._get_default_probe_points_text())
    app.probe_points_text.bind("<Key>", app._on_probe_points_user_key)

    btn_reset_probes = tk.Button(
        lf_hist, text="🔄 Reset to Standard Probes & Paths (Baseplate Center & Geometry Drivers)",
        font=FONT_SMALL, relief=tk.FLAT, padx=6, pady=2, cursor="hand2",
        command=app._reset_default_probe_points
    )
    btn_reset_probes.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=4, pady=(2, 4))
    reg_widget(app, btn_reset_probes, "button")

    ttk.Label(lf_hist, text="Probe paths (mm; x1,y1,z1,x2,y2,z2 per line):").grid(
        row=3, column=0, sticky=tk.NW, padx=4, pady=2)
    app.probe_paths_text = tk.Text(lf_hist, height=3, width=44, font=FONT_MONO)
    app.probe_paths_text.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=4)
    app.probe_paths_text.insert("1.0", app._get_default_probe_paths_text())
    app.probe_paths_text.bind("<Key>", app._on_probe_paths_user_key)

    make_param_row(app, lf_hist, "Stations per Path:", "path_samples", 4, "[-]", type_="int")
    make_param_row(app, lf_hist, "Write History Every N Steps:", "probe_interval", 5, "steps", type_="int")
    app._update_probe_geom_badge()

    # 4. Restart / Checkpoint
    lf_ck = tk.LabelFrame(tab, text="Restart / Checkpoint", font=FONT_SECTION, padx=8, pady=4)
    lf_ck.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_ck, "card_labelframe")
    add_info_button(app, lf_ck, app._show_solver_info)
    ttk.Label(lf_ck, text="Checkpointing:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
    app.restart_mode_var = tk.StringVar(value="off")
    ck_combo = ttk.Combobox(lf_ck, textvariable=app.restart_mode_var,
                            state="readonly", width=18,
                            values=["off", "layer", "step"])
    ck_combo.grid(row=0, column=1, padx=4, pady=2, sticky=tk.W)
    ttk.Label(lf_ck, text="layer = checkpoint after each layer (resume unit); step = every N steps",
              foreground="#64748b").grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=4)
    make_param_row(app, lf_ck, "Steps Between Checkpoints:", "restart_every", 2, "steps", type_="int")
    app.restart_resume_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(lf_ck, text="Resume from existing checkpoint if present",
                    variable=app.restart_resume_var).grid(
        row=3, column=0, columnspan=3, sticky=tk.W, padx=4, pady=2)

    # 5. Parallel Execution & Multi-Core Acceleration
    lf_par = tk.LabelFrame(tab, text="Parallel Execution & Multi-Core Acceleration", font=FONT_SECTION, padx=8, pady=4)
    lf_par.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf_par, "card_labelframe")
    add_info_button(app, lf_par, app._show_solver_info)

    # Linear Solver Backend
    ttk.Label(lf_par, text="Linear Solver Backend:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
    app.solver_backend_var = tk.StringVar(value="MUMPS")
    solver_combo = ttk.Combobox(lf_par, textvariable=app.solver_backend_var, state="readonly", width=22,
                                values=["MUMPS", "UMFPACK", "sparsesolver", "CG", "GMRES"])
    solver_combo.grid(row=0, column=1, padx=4, pady=2, sticky=tk.W)
    ttk.Label(lf_par, text="MUMPS = Multi-frontal Massively Parallel Direct Solver (Scales to 250k+ DoFs)",
              foreground="#64748b").grid(row=0, column=2, sticky=tk.W, padx=4)

    # Execution Mode
    ttk.Label(lf_par, text="Execution Architecture:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
    app.parallel_mode_var = tk.StringVar(value="multi_core_threaded")
    mode_combo = ttk.Combobox(lf_par, textvariable=app.parallel_mode_var, state="readonly", width=22,
                              values=["multi_core_threaded", "mpi_parallel", "serial"])
    mode_combo.grid(row=1, column=1, padx=4, pady=2, sticky=tk.W)
    ttk.Label(lf_par, text="multi_core_threaded = OpenMP/MKL/Accelerate shared memory; mpi = ff-mpirun",
              foreground="#64748b").grid(row=1, column=2, sticky=tk.W, padx=4)

    # CPU Cores
    n_detected = os.cpu_count() or 4
    ttk.Label(lf_par, text="CPU Thread Allocation:").grid(row=2, column=0, sticky=tk.W, padx=4, pady=2)
    app.cpu_threads_var = tk.StringVar(value=f"Auto ({min(n_detected, 16)} Cores)")
    thread_choices = [f"Auto ({min(n_detected, 16)} Cores)", "1 Core", "2 Cores", "4 Cores", "8 Cores", "12 Cores", "16 Cores"]
    thread_combo = ttk.Combobox(lf_par, textvariable=app.cpu_threads_var, state="readonly", width=22,
                                values=thread_choices)
    thread_combo.grid(row=2, column=1, padx=4, pady=2, sticky=tk.W)
    ttk.Label(lf_par, text=f"Host hardware: {n_detected} logical CPU cores detected",
              foreground="#059669").grid(row=2, column=2, sticky=tk.W, padx=4)

    # MPI Ranks
    ttk.Label(lf_par, text="MPI Rank Count:").grid(row=3, column=0, sticky=tk.W, padx=4, pady=2)
    app.mpi_ranks_var = tk.StringVar(value="1 (Serial / Shared-Memory)")
    mpi_choices = ["1 (Serial / Shared-Memory)", "2 Ranks", "4 Ranks", "8 Ranks", "12 Ranks", "16 Ranks"]
    mpi_combo = ttk.Combobox(lf_par, textvariable=app.mpi_ranks_var, state="readonly", width=22,
                             values=mpi_choices)
    mpi_combo.grid(row=3, column=1, padx=4, pady=2, sticky=tk.W)
    ttk.Label(lf_par, text="Phase 1 I/O-safe multi-rank partitioning (rank0 canonical)",
              foreground="#64748b").grid(row=3, column=2, sticky=tk.W, padx=4)

    # 6. Output & Checkpointing Config
    lf2 = tk.LabelFrame(tab, text="Output Directory & Recording", font=FONT_SECTION, padx=8, pady=4)
    lf2.pack(fill=tk.X, padx=8, pady=3)
    reg_widget(app, lf2, "card_labelframe")
    add_info_button(app, lf2, app._show_solver_info)
    make_param_row(app, lf2, "Output Directory:", "output_dir", 0, width=25, type_="str")
    make_param_row(app, lf2, "Save Every N Weld Steps:", "save_every_n_weld", 1, "", type_="int")
    make_param_row(app, lf2, "Save Every N Cool Steps:", "save_every_n_cool", 2, "", type_="int")

    return tab


# ==============================================================================
# ARCHITECTURAL DOCUMENTATION & ENGINEERING FORMULATION
# ==============================================================================
"""
SOLVER TAB FORMULATION & PHILOSOPHY
===================================

1. Mathematical & Numerical Formulation
---------------------------------------
The Solver Tab governs the temporal integration of the non-linear transient
heat equation and the mechanical momentum balance:

    ρ C_p(T) ∂T/∂t - ∇ · (k(T) ∇T) = Q_arc(x, t) + Q_drop + Q_uva

Temporal discretization uses the generalized θ-method (Crank-Nicolson for θ=0.5,
implicit Euler for θ=1.0):

    [M/Δt + θ K(T^{n+θ})] T^{n+1} = [M/Δt - (1-θ) K(T^{n+θ})] T^n + F^{n+θ}

The Courant/Fourier stability number Fo governs the spatial diffusion limit:
    Fo = α Δt / h_min² <= Fo_target
where α = k / (ρ C_p) is the thermal diffusivity and h_min is the minimum
element circumradius in the active weld pool.

2. Parallel Execution & Multi-Core Architecture
----------------------------------------------
Finite element systems in 3D WAAM routinely involve 100,000 to 300,000 DoFs.
Single-threaded direct solvers (e.g., standard UMFPACK) scale as O(N^2) in memory
and O(N^3) in factorization time, causing out-of-memory crashes above 150k DoFs.

This tab exposes:
  a. MUMPS (MUltifrontal Massively Parallel Sparse direct Solver):
     Employs multi-threaded parallel multifrontal factorization using OpenMP/MKL
     and distributed MPI memory hierarchies, resolving 250k DoF elasticity in
     under 7 GB RAM.
  b. OpenMP / Accelerate / MKL Multi-Core Thread Allocation:
     Configures OMP_NUM_THREADS, OPENBLAS_NUM_THREADS, and VECLIB_MAXIMUM_THREADS
     to saturate host CPU performance cores while preventing GUI starvation.
  c. MPI Distributed Execution:
     Launches multi-rank FreeFem++-mpi instances via ff-mpirun with isolated per-rank
     output structures (Phase 1 I/O-safe execution).

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                        SOLVER TAB                           │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Temporal Discretization                                  │
  │    ├── Time Scheme Weight (θ)          -> theta             │
  │    ├── Deposition Timestep (Δt_weld)   -> dt_weld           │
  │    ├── Inter-Pass Timestep (Δt_dwell)  -> dt_wait           │
  │    └── Final Cooling Timestep (Δt_cool)-> dt_cool           │
  │                                                             │
  │ 2. Adaptive Time Stepping (Fourier / Fo Controller)         │
  │    ├── Controller Type                 -> adaptive_dt       │
  │    ├── Target Diffusion Number (Fo)    -> adaptive_fo_target│
  │    └── Min / Max Bounds [Δt_min, max]  -> adaptive_dt_min/max│
  │                                                             │
  │ 3. History Output (Probe Points & Paths)                    │
  │    ├── Coordinate Group Textbox        -> probe_points      │
  │    ├── Continuous Resampled Paths      -> probe_paths       │
  │    └── Output Interval                 -> probe_interval    │
  │                                                             │
  │ 4. Restart / Checkpointing                                  │
  │    ├── Checkpoint Cadence              -> restart           │
  │    ├── Step Frequency                  -> restart_every     │
  │    └── State Resume Toggle             -> restart_resume    │
  │                                                             │
  │ 5. Parallel Execution & Multi-Core Acceleration             │
  │    ├── Linear Solver (MUMPS/UMFPACK)   -> solver            │
  │    ├── Execution Architecture (OMP/MPI)-> exec_mode         │
  │    ├── CPU Thread Count                -> cpu_threads       │
  │    └── MPI Rank Count                  -> mpi_ranks         │
  │                                                             │
  │ 6. Output Directory & Step Recording                        │
  │    ├── Run Storage Root                -> output_dir        │
  │    └── VTU Export Frequency            -> save_every_n_*    │
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  - solver_backend_var, parallel_mode_var, cpu_threads_var, mpi_ranks_var
      │
      ▼
  gui/app.py (_collect_params)
      │
      ▼
  codegen/edp/builder_core.py (EDPBuilder.build())
      │
      ├─► solver_setup() -> load "MUMPS"; set(..., solver=sparsesolver);
      ├─► mpi_safe -> isolated rank0/ canonical trees
      ├─► adaptive_dt -> FreeFEM local h_min timestep limiter
      └─► probe_setup() -> FreeFEM probe_points.csv & probe_paths.csv

5. Numerical & Physical Impact
------------------------------
  - Sub-optimal Δt_weld leads to torch-advance smearing if the torch traverses
    more than 1/8th of the Goldak beam semi-axis per step.
  - MUMPS solver eliminates out-of-memory termination on fine meshes.
  - Proper probe intervals capture steep cooling gradients (800 °C -> 500 °C,
    dt85) critical for accurate metallurgical hardness (HV) prediction.
"""
