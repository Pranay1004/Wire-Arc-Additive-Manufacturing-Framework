#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Tab Base Utilities and Layout Helpers
"""

import tkinter as tk
from tkinter import ttk

from gui.fonts import (
    FONT_LABEL, FONT_ENTRY, FONT_SMALL, FONT_SMALL_BOLD, FONT_SECTION
)

MM_DIMENSION_KEYS = {
    "lx", "ly_base", "hz_base", "ty_dep", "h_bead", "h_bead_first", "h_bead_subseq",
    "d_wire", "af", "ar", "bG", "cG",
    "R_beam", "R_spot", "rt", "rb", "d_pen",
    "a_band", "b_band", "c_band", "R_activate"
}
MM_SPEED_KEYS = {"v_scan"}


def reg_widget(app, widget, role):
    """Register widget with app's theme listener."""
    if hasattr(app, "registered_widgets"):
        app.registered_widgets.append((widget, role))
    return widget


def make_param_row(app, parent, label, key, row, unit="", type_="float", width=10, on_change=None):
    """
    Standard parameter entry row: Label [column 0] | Entry [column 1] | Unit [column 2].
    Syncs with app.params and sets up trace callbacks.
    """
    lbl = tk.Label(parent, text=label, font=FONT_LABEL)
    lbl.grid(row=row, column=0, sticky=tk.W, padx=(8, 4), pady=2)
    reg_widget(app, lbl, "label")

    raw_val = app.params.get(key, "")
    if key in MM_DIMENSION_KEYS and isinstance(raw_val, (int, float)):
        display_val = round(raw_val * 1000.0, 2)
        raw_val = int(display_val) if display_val == int(display_val) else display_val
    elif key in MM_SPEED_KEYS and isinstance(raw_val, (int, float)):
        display_val = round(raw_val * 1000.0, 2)
        raw_val = int(display_val) if display_val == int(display_val) else display_val

    var = tk.StringVar(value=str(raw_val))
    entry = tk.Entry(parent, textvariable=var, width=width, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
    entry.grid(row=row, column=1, padx=4, pady=2, sticky=tk.W)
    reg_widget(app, entry, "entry")

    if unit:
        u_lbl = tk.Label(parent, text=unit, font=FONT_SMALL)
        u_lbl.grid(row=row, column=2, sticky=tk.W, padx=4)
        reg_widget(app, u_lbl, "label_dim")

    app._param_vars[key] = (var, type_)
    if not hasattr(app, "param_entries"):
        app.param_entries = {}
    app.param_entries[key] = entry

    if key == "n_layers":
        entry.bind("<FocusIn>", lambda e: app._on_n_layers_focus())
        entry.bind("<KeyRelease>", lambda e: app._on_n_layers_key())

    if on_change:
        var.trace_add("write", lambda *args: on_change())
    else:
        var.trace_add("write", lambda *args: app._on_any_param_change(key))

    return var


def add_info_button(app, lf, command):
    """Place an Info button in the top right corner of a LabelFrame."""
    btn = tk.Button(
        lf, text="ⓘ Info", font=FONT_SMALL_BOLD,
        command=command, padx=6, pady=1,
        relief=tk.FLAT, bd=0, highlightthickness=0
    )
    btn.place(relx=1.0, rely=0.0, anchor="ne", x=-6, y=2)
    reg_widget(app, btn, "button")
    return btn


def create_scrollable_container(parent, bg_color):
    """
    Creates a responsive canvas with vertical scrollbar that automatically expands.
    Returns (canvas, content_frame).
    """
    canvas = tk.Canvas(parent, highlightthickness=0, bg=bg_color)
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    content = tk.Frame(canvas, bg=bg_color)

    content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    cw = canvas.create_window((0, 0), window=content, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Bind mousewheel scrolling
    def _on_mousewheel(event):
        if canvas.winfo_exists():
            delta = -1 if event.delta < 0 or getattr(event, "num", 0) == 5 else 1
            canvas.yview_scroll(delta * -1, "units")

    canvas.bind("<MouseWheel>", _on_mousewheel)
    canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
    canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

    return canvas, content


"""
================================================================================
WAAM TAB BASE UTILITIES & COMPONENT ARCHITECTURE
================================================================================

1. Design & Engineering Philosophy
-----------------------------------
The base module (`gui/tabs/base.py`) provides the foundational layout abstractions,
unit normalization engines, and reactive UI observers across all GUI tabs. It enforces:
  a. Unit Strictness with Display Ergonomics:
     Internal computational engines (FreeFEM++, OpenFOAM, Gmsh) strictly mandate SI units
     (meters, seconds, Pascals, Watts). Human engineers, however, reason in millimeters (mm)
     and millimeters per second (mm/s). The base module automatically converts between
     millimeter display values in UI entry boxes and meters in the computational state
     dictionary (`app.params`).
  b. Reactive Observer Model:
     Every parameter row created via `make_param_row()` wires a Tkinter `StringVar` trace
     listener that propagates live edits to both memory (`app.params`) and cross-tab
     subscribers (e.g., synchronizing bead width between Geometry and Mesh Slicer).
  c. Zero-Flicker Layout Hierarchy:
     Dynamic scroll containers (`create_scrollable_container`) embed virtual canvas viewports
     with mousewheel normalization across macOS (Aqua) and Linux (X11).

2. Mathematical & Unit Normalization Engine
-------------------------------------------
Let x_display be the UI entry value and x_sim be the physical engine variable:
  - Linear Dimensions (x ∈ MM_DIMENSION_KEYS):
      x_sim = x_display × 10⁻³ [m]
      x_display = round(x_sim × 10³, 2) [mm]
  - Scanning Velocities (v ∈ MM_SPEED_KEYS):
      v_sim = v_display × 10⁻³ [m/s]
      v_display = round(v_sim × 10³, 2) [mm/s]
  - General Dimensionless & Physical Quantities (I, U, T, η, ρ, k, Cp):
      x_sim = x_display [Identity mapping]

3. ASCII Component Hierarchy
----------------------------
  ┌─────────────────────────────────────────────────────────────┐
  │                    GUI TAB BASE SYSTEM                      │
  ├─────────────────────────────────────────────────────────────┤
  │ 1. Parameter Normalization Layer                            │
  │    ├── MM_DIMENSION_KEYS      -> {lx, ly_base, hz_base, ...}│
  │    └── MM_SPEED_KEYS          -> {v_scan}                   │
  │                                                             │
  │ 2. Widget Factory & Observer Binding                        │
  │    ├── make_param_row()       -> Label + Entry + Unit Label │
  │    ├── reg_widget()           -> Theme registry listener    │
  │    └── add_info_button()      -> Contextual modal dialogs   │
  │                                                             │
  │ 3. Scrollable Viewport Containers                           │
  │    ├── create_scrollable_container()                        │
  │    │     ├── tk.Canvas (Virtual coordinate space)           │
  │    │     ├── ttk.Scrollbar (Normalized Y-scroll)            │
  │    │     └── Mousewheel Bindings (Aqua / X11 delta adapter) │
  │    └────────────────────────────────────────────────────────┘
  └─────────────────────────────────────────────────────────────┘

4. Cross-Connections & Data Flow Map
-------------------------------------
  User Keystroke in Entry Widget
        │
        ▼
  var.trace_add("write", ...) -> make_param_row()
        │
        ├─► app._on_any_param_change(key)
        │     │
        │     ├─► Live Unit Conversion (mm -> m)
        │     ├─► app.params[key] = val_si
        │     └─► Synchronize Cross-Tab Labels & 3D Preview
        │
        └─► app._param_vars[key] -> (StringVar, type_)

5. Numerical & Engineering Impact
---------------------------------
  - Eliminates silent unit mismatch errors (e.g., entering 150 mm as 150 m would
    cause computational explosion or divergence in transient thermal diffusion).
  - Guarantees theme responsiveness without widget leaks or orphaned event handlers.
"""
