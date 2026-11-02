"""
gui.py - Tkinter desktop GUI for the WAAM slicer (no terminal needed).

Run:
    python waam_slicer/gui.py
or from the waam_lab folder:
    python -m waam_slicer.gui

Features:
- "Attach STL" file browser (fixes the `Main.stl` relative-path confusion:
  the dialog always returns an absolute path).
- All slicer params editable in a form (same defaults as main.py / machine
  nameplate: 800x800x400mm, 1000 mm/min max).
- One-click Slice + Generate, with live log, progress bar, mesh report,
  warnings, and stats.
- 2D layer preview (perimeter / infill / centerline in different colours).
- 3D "digital-twin-lite" replay: kinematic preview of the whole build,
  scrubbed with a slider (Phase-1 twin - see README / chat for full plan).
"""

import os
import sys
import time
import math
import queue
import threading
import traceback
from pathlib import Path

# Make imports work whether launched as `python waam_slicer/gui.py`
# (script dir on sys.path) or `python -m waam_slicer.gui` (package mode).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_THIS_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from waam_slicer.slicer_core import (
        load_mesh, slice_mesh, auto_place_mesh, apply_orientation,
        MeshValidationError, SlicingError, parse_fea_mesh, parse_fea_mesh_or_none,
    )
    from waam_slicer.toolpath import plan_all_layers, summarize_warnings, INFILL_STYLES
    from waam_slicer.gcode_gen import (
        WAAMParams, MachineLimits, generate_gcode, write_gcode_file,
        GCodeGenerationError, compute_job_stats, _format_time, _apply_lead_in_out,
    )
except ImportError:  # fallback for plain `python waam_slicer/gui.py`
    from slicer_core import (
        load_mesh, slice_mesh, auto_place_mesh, apply_orientation,
        MeshValidationError, SlicingError, parse_fea_mesh, parse_fea_mesh_or_none,
    )
    from toolpath import plan_all_layers, summarize_warnings, INFILL_STYLES
    from gcode_gen import (
        WAAMParams, MachineLimits, generate_gcode, write_gcode_file,
        GCodeGenerationError, compute_job_stats, _format_time, _apply_lead_in_out,
    )

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import numpy as np


BEAD_COLORS = {"perimeter": "#1f77b4", "infill": "#ff7f0e", "centerline": "#d62728"}


class ScrollableFrame(ttk.Frame):
    """Vertical scrolling container with mousewheel and trackpad support."""
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_content = ttk.Frame(self.canvas)

        self.scrollable_content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self._window_id = self.canvas.create_window((0, 0), window=self.scrollable_content, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self._window_id, width=e.width)
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.scrollable_content.bind("<Enter>", self._on_enter)
        self.scrollable_content.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
        except Exception:
            pass

    def _on_leave(self, _event=None):
        self._unbind()

    def _on_mousewheel(self, event):
        try:
            if event.num == 4:
                self.canvas.yview_scroll(-2, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(2, "units")
            elif event.delta:
                step = -1 if event.delta > 0 else 1
                self.canvas.yview_scroll(step * 2, "units")
        except Exception:
            pass


class WAAMSlicerFrame(ttk.Frame):
    def __init__(self, master=None, app=None, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app

        self.log_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.toolpaths = []
        self.layers = []
        self.mesh_report = None
        self.mesh = None
        self.last_gcode_path = ""
        self._preview_result = None   # background preview-load handoff (main thread polls it)
        self._preview_gen = 0         # invalidates stale preview loads
        self._orient_after = None
        self.p_lx_val = 150.0
        self.p_ly_val = 150.0
        self.p_hz_val = 5.0
        self.p_nl_val = 8

        # FEA Conformal Volume Mesh state
        self.fea_mesh: dict | None = None
        self.fea_mesh_path: str = ""
        self.v_view_source = tk.StringVar(value="FEA Conformal Mesh")
        self.v_show_nodes = tk.BooleanVar(value=True)
        self.v_show_substrate = tk.BooleanVar(value=True)

        self._build_widgets()
        self.after(120, self._poll_log_queue)
        init_stl = self.stl_var.get().strip()
        if init_stl and os.path.isfile(init_stl):
            self.after(150, lambda: self.load_file(init_stl))
        else:
            self.after(150, self._draw_parametric_mesh)

    def _load_sample_letter_z(self):
        """Quickly load the workspace sample letter Z STL geometry."""
        for cand in [
            os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "stl", "z.stl")),
            os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "stl", "letter_Z_WAAM.stl")),
            os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "stl", "cube_80mm.stl")),
        ]:
            if os.path.isfile(cand):
                self.load_file(cand)
                return
        messagebox.showinfo("Sample Model", "No sample STL found in workspace.")

    def load_fea_mesh(self, path: str, auto_switch: bool = True):
        """Load an Inria Medit volume mesh (.mesh, .mesh3) and refresh orient view."""
        if not path or not os.path.isfile(path):
            return
        # Fast path: skip the 0.5-3 s re-parse when the same file (same stat)
        # is already loaded. This is the hot path: the app re-issues
        # update_mesh()/load_file() on EVERY debounced parameter refresh, and
        # a full re-parse here froze the UI with 5k+ node meshes.
        try:
            try:
                from core.platform_adapter import stat_fingerprint
            except Exception:
                import sys as _sys, os as _os
                _fw = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "WAAM-Framework")
                if _fw not in _sys.path:
                    _sys.path.insert(0, _fw)
                from core.platform_adapter import stat_fingerprint
            _abspath, _mtime, _size = stat_fingerprint(path)
            same = (
                self.fea_mesh is not None
                and self._fea_mesh_stat == (_mtime, _size)
                and os.path.abspath(self.fea_mesh_path or "") == os.path.abspath(path)
            )
        except (AttributeError, OSError, Exception):
            same = False
        if same:
            if auto_switch and hasattr(self, "v_view_source") and self.v_view_source:
                self.v_view_source.set("FEA Conformal Mesh")
            self._schedule_orient_redraw()
            return
        fea = parse_fea_mesh_or_none(path)
        if fea is None:
            self.log(f"[FEA Preview] Warning: could not parse mesh file: {path}")
            return
        self.fea_mesh = fea
        self.fea_mesh_path = path
        try:
            try:
                from core.platform_adapter import stat_fingerprint
            except Exception:
                import sys as _sys, os as _os
                _fw = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "WAAM-Framework")
                if _fw not in _sys.path:
                    _sys.path.insert(0, _fw)
                from core.platform_adapter import stat_fingerprint
            self._fea_mesh_stat = (stat_fingerprint(path)[1], stat_fingerprint(path)[2])
        except Exception:
            self._fea_mesh_stat = None
        self.log(
            f"[FEA Preview] Loaded Conformal FEA Mesh: {fea['n_nodes']:,} nodes | "
            f"{fea['n_tets']:,} tets | {fea['n_triangles']:,} boundary facets"
        )
        if auto_switch and hasattr(self, "v_view_source") and self.v_view_source:
            self.v_view_source.set("FEA Conformal Mesh")
        self._schedule_orient_redraw()
        try:
            self.nb.select(self.tab_orient)
        except Exception:
            pass

    def load_file(self, path: str):
        """Set active STL / mesh file path and refresh orient & view preview."""
        if not path or not os.path.isfile(path):
            return

        # If an FEA mesh is directly provided
        if str(path).lower().endswith((".mesh", ".mesh3")):
            self.load_fea_mesh(path, auto_switch=True)
            # Look for sibling CAD STL if available
            cand_stem = Path(path).stem
            if cand_stem.startswith("imported_"):
                cand_stem = cand_stem[len("imported_"):]
            for s_dir in [os.path.dirname(path), "./stl", "../WAAM-Framework/stl"]:
                s_cand = os.path.abspath(os.path.join(s_dir, f"{cand_stem}.stl"))
                if os.path.isfile(s_cand):
                    self.stl_var.set(s_cand)
                    self._refresh_orient_view()
                    break
            return

        old = self.stl_var.get().strip()
        self.stl_var.set(path)
        self.log(f"Attached from app: {path}")
        self.preview_base = None
        if path != old:
            self.p_scale.set("1.0")
            self._reset_orientation()

        # Check if an FEA mesh already exists for this CAD geometry
        stem = Path(path).stem
        for cand in [
            os.path.abspath(f"./waam_output/imported_{stem}.mesh"),
            os.path.abspath(f"./waam_output/{stem}.mesh"),
            os.path.abspath(os.path.join(os.path.dirname(path), f"imported_{stem}.mesh")),
            os.path.abspath(os.path.join(os.path.dirname(path), f"{stem}.mesh")),
            os.path.abspath(os.path.join(os.path.dirname(path), "..", "waam_output", f"imported_{stem}.mesh")),
        ]:
            if os.path.isfile(cand):
                self.load_fea_mesh(cand, auto_switch=True)
                break

        self._refresh_orient_view()
        try:
            self.nb.select(self.tab_orient)
        except Exception:
            pass

    def update_mesh(self, params: dict = None):
        """Sync parameters if provided and refresh 3D orient view."""
        if params and isinstance(params, dict):
            # Check for FEA volume mesh first
            mesh_file = params.get("mesh_file")
            if mesh_file and isinstance(mesh_file, str) and os.path.isfile(mesh_file) and mesh_file.lower().endswith((".mesh", ".mesh3")):
                # Skip the re-parse when the same mesh (same stat) is loaded
                # already; only a regenerated file needs a fresh load.
                try:
                    try:
                        from core.platform_adapter import stat_fingerprint
                    except Exception:
                        import sys as _sys, os as _os
                        _fw = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "WAAM-Framework")
                        if _fw not in _sys.path:
                            _sys.path.insert(0, _fw)
                        from core.platform_adapter import stat_fingerprint
                    _fp = stat_fingerprint(mesh_file)
                    need_load = self.fea_mesh is None or self._fea_mesh_stat != (_fp[1], _fp[2])
                except (AttributeError, OSError, Exception):
                    need_load = True
                if need_load:
                    self.load_fea_mesh(mesh_file, auto_switch=True)

            # Check if STL or CAD file path is passed
            cad_path = params.get("stl_file") or params.get("cad_file")
            if cad_path and isinstance(cad_path, str) and os.path.isfile(cad_path):
                if cad_path.lower().endswith(('.stl', '.3mf', '.obj', '.step', '.stp', '.iges', '.igs')):
                    if cad_path != self.stl_var.get().strip():
                        self.load_file(cad_path)            # Parametric geometry dimensions
            if "lx" in params:
                try:
                    val = float(params["lx"])
                    self.p_lx_val = val * 1000.0 if val < 1.0 else val
                except Exception:
                    pass
            if "ly_base" in params:
                try:
                    val = float(params["ly_base"])
                    self.p_ly_val = val * 1000.0 if val < 1.0 else val
                except Exception:
                    pass
            if "hz_base" in params:
                try:
                    val = float(params["hz_base"])
                    self.p_hz_val = val * 1000.0 if val < 1.0 else val
                except Exception:
                    pass
            if "n_layers" in params:
                try:
                    self.p_nl_val = int(params["n_layers"])
                except Exception:
                    pass
            if "h_bead" in params:
                try:
                    hb_mm = float(params["h_bead"]) * 1000.0 if float(params["h_bead"]) < 0.1 else float(params["h_bead"])
                    self.p_layer_h.set(f"{hb_mm:.2f}")
                except Exception:
                    pass
            if "ty_dep" in params:
                try:
                    w_mm = float(params["ty_dep"]) * 1000.0 if float(params["ty_dep"]) < 0.1 else float(params["ty_dep"])
                    self.p_bead_w.set(f"{w_mm:.2f}")
                except Exception:
                    pass
            if "v_scan" in params:
                try:
                    vs = float(params["v_scan"])
                    vs_mmin = vs * 60.0 if vs > 0.5 else vs * 60000.0  # m/s -> mm/min or mm/s -> mm/min
                    self.p_weld.set(f"{vs_mmin:.1f}")
                except Exception:
                    pass
            if "v_wire" in params:
                try:
                    vw = float(params["v_wire"])
                    vw_mmin = vw if vw < 50.0 else vw / 1000.0
                    self.p_wfs.set(f"{vw_mmin:.2f}")
                except Exception:
                    pass
            if "I_weld" in params:
                try:
                    self.p_current.set(f"{float(params['I_weld']):.1f}")
                except Exception:
                    pass
            if "U_weld" in params:
                try:
                    self.p_voltage.set(f"{float(params['U_weld']):.1f}")
                except Exception:
                    pass
            if "eta_arc" in params:
                try:
                    self.p_wire_eff.set(f"{float(params['eta_arc']):.2f}")
                except Exception:
                    pass
            if "d_wire" in params:
                try:
                    dw = float(params["d_wire"])
                    dw_mm = dw * 1000.0 if dw < 0.05 else dw
                    self.p_wire_dia.set(f"{dw_mm:.2f}")
                except Exception:
                    pass
            if "material" in params or "material_dep" in params:
                mat = str(params.get("material_dep", params.get("material", "steel")))
                self.p_material.set(mat)
            if "num_perimeters" in params or "perimeters" in params:
                try:
                    np_val = int(params.get("num_perimeters", params.get("perimeters", 2)))
                    self.p_perim.set(str(np_val))
                except Exception:
                    pass
        self._refresh_orient_view()

    # ---------------- layout ----------------
    def _build_widgets(self):
        # ---- bottom action bar FIRST (guarantees buttons are NEVER pushed off or hidden) ----
        bot = ttk.Frame(self, padding=(6, 4))
        bot.pack(side=tk.BOTTOM, fill=tk.X)
        self.run_btn = ttk.Button(bot, text="▶ Slice + Generate G-code", command=self.start_job)
        self.run_btn.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bot, text="📁 Open output folder", command=self.open_out_folder).pack(side=tk.LEFT, padx=3)
        ttk.Button(bot, text="↺ Clear results", command=self._clear_results).pack(side=tk.LEFT, padx=3)
        self.theme_var = tk.StringVar(value="light")
        self.theme_btn = ttk.Button(bot, text="Theme: light", command=self.toggle_theme)
        self.theme_btn.pack(side=tk.LEFT, padx=3)
        self.prog = ttk.Progressbar(bot, mode="indeterminate", length=140)
        self.prog.pack(side=tk.LEFT, padx=5)
        self.status_var = tk.StringVar(value="idle")
        ttk.Label(bot, textvariable=self.status_var, font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=4)
        self.stats_var = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self.stats_var, font=("TkDefaultFont", 8), justify=tk.LEFT).pack(side=tk.RIGHT, padx=4)

        # ---- top file bar ----
        top = ttk.Frame(self, padding=(6, 3))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="STL / mesh:").grid(row=0, column=0, sticky="w")
        self.stl_var = tk.StringVar()
        # pre-fill with repo's sample if present
        default_sample = ""
        for cand in [
            os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "stl", "z.stl")),
            os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "stl", "letter_Z_WAAM.stl")),
            os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "stl", "cube_80mm.stl")),
        ]:
            if os.path.isfile(cand):
                default_sample = cand
                break
        if default_sample:
            self.stl_var.set(default_sample)
        ttk.Entry(top, textvariable=self.stl_var, width=46).grid(row=0, column=1, padx=4, sticky="ew")
        ttk.Button(top, text="Attach STL...", command=self.browse_stl).grid(row=0, column=2, padx=2)
        ttk.Button(top, text="⚡ Sample (Letter Z)", command=self._load_sample_letter_z).grid(row=0, column=3, padx=2)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Output G-code:").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.out_var = tk.StringVar(value=os.path.join(os.getcwd(), "output.gcode"))
        ttk.Entry(top, textvariable=self.out_var, width=46).grid(row=1, column=1, padx=4, pady=(2, 0), sticky="ew")
        ttk.Button(top, text="Save as...", command=self.browse_out).grid(row=1, column=2, padx=2, pady=(2, 0))

        # ---- main split ----
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # left: params (wrapped in vertical scrollable container)
        self.left_scroll = ScrollableFrame(paned, padding=2)
        paned.add(self.left_scroll, weight=1)
        self._build_params(self.left_scroll.scrollable_content)

        # right: notebook
        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill=tk.BOTH, expand=True)

        self.tab_log = ttk.Frame(self.nb, padding=4)
        self.tab_orient = ttk.Frame(self.nb, padding=4)
        self.tab_2d = ttk.Frame(self.nb, padding=4)
        self.tab_3d = ttk.Frame(self.nb, padding=4)
        self.tab_empirical = ttk.Frame(self.nb, padding=4)
        self.nb.add(self.tab_orient, text="3D Mesh & Orient View")
        self.nb.add(self.tab_2d, text="2D Layer preview")
        self.nb.add(self.tab_3d, text="3D Twin replay (kinematic)")
        self.nb.add(self.tab_log, text="Log / Report")
        self.nb.add(self.tab_empirical, text="Empirical Values")

        logbar = ttk.Frame(self.tab_log)
        logbar.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(logbar, text="Latest run is always at the bottom.", font=("TkDefaultFont", 8)).pack(side=tk.LEFT)
        ttk.Button(logbar, text="Clear log",
                   command=lambda: self.log_text.delete("1.0", tk.END)).pack(side=tk.RIGHT)
        self.log_text = tk.Text(self.tab_log, wrap=tk.WORD, height=18)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        sb = ttk.Scrollbar(self.tab_log, command=self.log_text.yview)
        sb.pack(fill=tk.Y, side=tk.RIGHT)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log("WAAM Slicer GUI ready. Attach an STL (or use the pre-filled sample from WAAM-Framework/stl) and press Slice.")
        self.log("Tip: if a relative path failed earlier (`string is not a file`), it was resolved against the")
        self.log("launch directory - the GUI always uses absolute paths, so prefer 'Attach STL...' to browse.")

        self._build_2d_tab()
        self._build_3d_tab()
        self._build_orient_tab()
        self._build_empirical_tab()

        if hasattr(self, "protocol"):
            try:
                self.protocol("WM_DELETE_WINDOW", self.on_close)
            except Exception:
                pass
        self.apply_theme()

    def on_close(self, destroy_top=False):
        """Tear down cleanly: a bare destroy()/Ctrl+C mid-draw can abort the
        interpreter inside matplotlib's C code (PyEval_RestoreThread fatal)."""
        try:
            if self._orient_after is not None:
                self.after_cancel(self._orient_after)
        except Exception:
            pass
        self._orient_after = None
        self._preview_gen += 1  # orphan any in-flight preview load
        for fig, _ax in self._mpl_axes():
            try:
                fig.clf()
            except Exception:
                pass
        if destroy_top:
            try:
                self.winfo_toplevel().destroy()
            except Exception:
                pass

    _on_close = on_close

    def _param_row(self, parent, row, label, var, width=8, tip=""):
        ttk.Label(parent, text=label, font=("TkDefaultFont", 8)).grid(row=row, column=0, sticky="w", pady=0)
        e = ttk.Entry(parent, textvariable=var, width=width, font=("TkDefaultFont", 8))
        e.grid(row=row, column=1, sticky="ew", padx=(3, 2), pady=0)
        if tip:
            ttk.Label(parent, text=tip, foreground="gray", font=("TkDefaultFont", 7)).grid(
                row=row, column=2, sticky="w", padx=2)
        return e

    def _build_params(self, f):
        ttk.Label(f, text="Process parameters", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 2))
        grid = ttk.Frame(f)
        grid.pack(fill=tk.X, pady=2)
        grid.columnconfigure(1, weight=1)

        def dv(v):
            return tk.StringVar(value=str(v))

        # Check if parent app has parameter bindings
        init_lh = 3.0
        init_bw = 5.0
        init_weld = 480.0
        init_dwell = 10.0
        init_v = 20.0
        init_i = 180.0
        init_dw = 1.2
        if self.app and hasattr(self.app, "_param_vars"):
            try:
                if "h_bead" in self.app._param_vars:
                    init_lh = float(self.app._param_vars["h_bead"][0].get() or "3.0")
                    if init_lh < 0.1: init_lh *= 1000.0
                if "ty_dep" in self.app._param_vars:
                    init_bw = float(self.app._param_vars["ty_dep"][0].get() or "5.0")
                    if init_bw < 0.1: init_bw *= 1000.0
                if "v_scan" in self.app._param_vars:
                    vs = float(self.app._param_vars["v_scan"][0].get() or "8.0")
                    if vs < 0.1: vs *= 1000.0
                    init_weld = vs * 60.0
                if "t_wait" in self.app._param_vars:
                    init_dwell = float(self.app._param_vars["t_wait"][0].get() or "10.0")
                if "U_weld" in self.app._param_vars:
                    init_v = float(self.app._param_vars["U_weld"][0].get() or "20.0")
                if "I_weld" in self.app._param_vars:
                    init_i = float(self.app._param_vars["I_weld"][0].get() or "180.0")
                if "d_wire" in self.app._param_vars:
                    init_dw = float(self.app._param_vars["d_wire"][0].get() or "1.2")
                    if init_dw < 0.1: init_dw *= 1000.0
            except Exception:
                pass

        self.p_layer_h = dv(init_lh)
        self.p_bead_w = dv(init_bw)
        self.p_perim = dv(2)
        self.p_travel = dv(3000.0)
        self.p_weld = dv(init_weld)
        self.p_wfs = tk.StringVar(value="")  # optional
        self.p_infill_step = dv(45.0)
        self.p_dwell = dv(init_dwell)
        self.p_lead = dv(0.0)
        self.p_arc_on = dv("M3")
        self.p_arc_off = dv("M5")
        self.p_wf_on = tk.StringVar(value="")
        self.p_wf_off = tk.StringVar(value="")
        self.p_xmin = dv(0.0); self.p_xmax = dv(800.0)
        self.p_ymin = dv(0.0); self.p_ymax = dv(800.0)
        self.p_zmin = dv(0.0); self.p_zmax = dv(400.0)
        self.p_maxfeed = dv(3000.0)
        self.p_stepmesh = dv(5.0)
        self.p_scale = dv(1.0)
        self.p_voltage = dv(init_v)
        self.p_current = dv(init_i)
        self.p_wire_eff = dv(0.8)
        self.p_wire_dia = dv(init_dw)
        self.p_material = tk.StringVar(value="steel")

        # Synchronize back to parent app
        if self.app and hasattr(self.app, "_param_vars"):
            def _sync_to_app(*_):
                if getattr(self, "_syncing_to_app", False): return
                self._syncing_to_app = True
                try:
                    lh = self.p_layer_h.get().strip()
                    bw = self.p_bead_w.get().strip()
                    weld = self.p_weld.get().strip()
                    dw = self.p_dwell.get().strip()
                    if lh and "h_bead" in self.app._param_vars:
                        self.app._param_vars["h_bead"][0].set(lh)
                    if bw and "ty_dep" in self.app._param_vars:
                        self.app._param_vars["ty_dep"][0].set(bw)
                    if weld and "v_scan" in self.app._param_vars:
                        v_mms = float(weld) / 60.0
                        self.app._param_vars["v_scan"][0].set(f"{v_mms:.2f}")
                    if dw and "t_wait" in self.app._param_vars:
                        self.app._param_vars["t_wait"][0].set(dw)
                except Exception:
                    pass
                finally:
                    self._syncing_to_app = False

            self.p_layer_h.trace_add("write", _sync_to_app)
            self.p_bead_w.trace_add("write", _sync_to_app)
            self.p_weld.trace_add("write", _sync_to_app)
            self.p_dwell.trace_add("write", _sync_to_app)

        rows = [
            ("Layer height (mm)", self.p_layer_h, "1.5-4 typical"),
            ("Bead width (mm)", self.p_bead_w, "4-8 typical"),
            ("Perimeters", self.p_perim, "auto-reduces if thin"),
            ("Travel speed (mm/min)", self.p_travel, ""),
            ("Weld speed (mm/min)", self.p_weld, ""),
            ("Wire feed (m/min, opt)", self.p_wfs, "3-10 m/min typical; blank = auto"),
            ("Infill angle step (deg)", self.p_infill_step, ""),
            ("Interlayer dwell (s)", self.p_dwell, "cooling pause"),
            ("Lead-in/out (mm)", self.p_lead, "0 = off"),
            ("Arc V (V)", self.p_voltage, "heat input calc"),
            ("Arc I (A)", self.p_current, "heat input calc"),
            ("Wire efficiency η", self.p_wire_eff, "0.7-0.9 GMAW"),
            ("Wire dia (mm)", self.p_wire_dia, "1.2 standard"),
            ("Arc ON M-code", self.p_arc_on, "confirm wiring!"),
            ("Arc OFF M-code", self.p_arc_off, ""),
            ("Wire ON M-code (opt)", self.p_wf_on, "blank = none"),
            ("Wire OFF M-code (opt)", self.p_wf_off, ""),
            ("X min", self.p_xmin, ""), ("X max", self.p_xmax, ""),
            ("Y min", self.p_ymin, ""), ("Y max", self.p_ymax, ""),
            ("Z min", self.p_zmin, ""), ("Z max", self.p_zmax, ""),
            ("Max feed (mm/min)", self.p_maxfeed, "nameplate 1000"),
            ("STEP mesh size (mm)", self.p_stepmesh, "STEP/IGES only"),
            ("Scale factor", self.p_scale, "1.0 = as-is"),
        ]
        for i, (lbl, var, tip) in enumerate(rows):
            self._param_row(grid, i, lbl, var, tip=tip)

        self.v_allow_damaged = tk.BooleanVar(value=False)
        self.v_skip_bounds = tk.BooleanVar(value=False)
        self.v_auto_place = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Auto-place part into envelope (center XY, Z=0)", variable=self.v_auto_place).pack(anchor="w", pady=1)
        ttk.Checkbutton(f, text="Allow damaged mesh (not recommended)", variable=self.v_allow_damaged).pack(anchor="w", pady=1)
        ttk.Checkbutton(f, text="Skip bounds check (simulation only!)", variable=self.v_skip_bounds).pack(anchor="w", pady=1)
        irow = ttk.Frame(f)
        irow.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(irow, text="Infill:", font=("TkDefaultFont", 8)).pack(side=tk.LEFT)
        self.p_infill_style = tk.StringVar(value="zigzag")
        ttk.Combobox(irow, textvariable=self.p_infill_style, values=list(INFILL_STYLES),
                     state="readonly", width=8, font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=3)
        ttk.Label(irow, text="zigzag / lines / contour",
                  foreground="gray", font=("TkDefaultFont", 7)).pack(side=tk.LEFT)
        mrow = ttk.Frame(f)
        mrow.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(mrow, text="Material:", font=("TkDefaultFont", 8)).pack(side=tk.LEFT)
        ttk.Combobox(mrow, textvariable=self.p_material,
                     values=["steel", "aluminium", "titanium"],
                     state="readonly", width=10, font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=3)
        ttk.Label(mrow, text="steel/aluminium/titanium",
                  foreground="gray", font=("TkDefaultFont", 7)).pack(side=tk.LEFT)
        ttk.Label(f, text="Machine: DDCS V2.1 (800x800x400mm).\nArc defaults M3/M5 - confirm on cold dry-run.",
                  foreground="#8a5a00", font=("TkDefaultFont", 7), justify=tk.LEFT, wraplength=260).pack(anchor="w", pady=(4, 6))

        # orientation state (owned by the Orient & View tab, read by the slice job)
        self.o_rx = tk.DoubleVar(value=0.0)
        self.o_ry = tk.DoubleVar(value=0.0)
        self.o_rz = tk.DoubleVar(value=0.0)
        self.o_dx = tk.StringVar(value="0")
        self.o_dy = tk.StringVar(value="0")
        self.o_dz = tk.StringVar(value="0")
        self.preview_base = None       # raw mesh (scale=1) for the live view
        self.preview_path = ""         # path it was loaded from
        self._preview_face_idx = None  # decimated draw subset (None = draw all)
        self._preview_loading_for = ""  # path with a load in flight
        self._orient_after = None      # coalesced redraw handle

    def _build_2d_tab(self):
        ctl = ttk.Frame(self.tab_2d)
        ctl.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(ctl, text="Layer:").pack(side=tk.LEFT)
        self.layer_idx = tk.IntVar(value=0)
        self.layer_slider = ttk.Scale(ctl, from_=0, to=0, variable=self.layer_idx,
                                      command=lambda *_: self.draw_layer())
        self.layer_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.layer_lbl = ttk.Label(ctl, text="0 / 0")
        self.layer_lbl.pack(side=tk.LEFT)
        ttk.Button(ctl, text="Redraw", command=self.draw_layer).pack(side=tk.LEFT, padx=6)

        self.fig2d = Figure(figsize=(4.5, 3.2), dpi=90)
        self.ax2d = self.fig2d.add_subplot(111)
        self.ax2d.set_aspect("equal", adjustable="datalim")
        self.ax2d.set_xlabel("X (mm)"); self.ax2d.set_ylabel("Y (mm)")
        self.canvas2d = FigureCanvasTkAgg(self.fig2d, master=self.tab_2d)
        self.canvas2d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _build_3d_tab(self):
        ctl = ttk.Frame(self.tab_3d)
        ctl.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(ctl, text="Layers 0..").pack(side=tk.LEFT)
        self.twin_n = tk.IntVar(value=0)
        self.twin_slider = ttk.Scale(ctl, from_=0, to=0, variable=self.twin_n,
                                     command=lambda *_: self.draw_twin())
        self.twin_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.twin_lbl = ttk.Label(ctl, text="0 / 0")
        self.twin_lbl.pack(side=tk.LEFT)
        ttk.Button(ctl, text="Show all", command=self.show_all_twin).pack(side=tk.LEFT, padx=6)
        ttk.Label(ctl, text="Kinematic replay (ordered beads)",
                  foreground="gray", font=("TkDefaultFont", 7)).pack(side=tk.LEFT, padx=6)

        self.fig3d = Figure(figsize=(4.5, 3.2), dpi=90)
        self.ax3d = self.fig3d.add_subplot(111, projection="3d")
        self.ax3d.set_xlabel("X (mm)"); self.ax3d.set_ylabel("Y (mm)"); self.ax3d.set_zlabel("Z (mm)")
        self.canvas3d = FigureCanvasTkAgg(self.fig3d, master=self.tab_3d)
        self.canvas3d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ---------------- orient & live view ----------------
    def _build_orient_tab(self):
        ctrl = ttk.Frame(self.tab_orient, width=230)
        ctrl.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        ctrl.pack_propagate(False)

        ttk.Label(ctrl, text="Rotate about centroid", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        self._rot_row(ctrl, "RX", self.o_rx)
        self._rot_row(ctrl, "RY", self.o_ry)
        self._rot_row(ctrl, "RZ", self.o_rz)
        ttk.Button(ctrl, text="Reset orientation", command=self._reset_orientation).pack(anchor="w", pady=(1, 4))

        ttk.Label(ctrl, text="Position & Zoom", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        ttk.Checkbutton(ctrl, text="Auto-place in envelope", variable=self.v_auto_place,
                        command=self._schedule_orient_redraw).pack(anchor="w")
        self.v_fit_part = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="Zoom to part (auto-focus)", variable=self.v_fit_part,
                        command=self._schedule_orient_redraw).pack(anchor="w")
        zrow = ttk.Frame(ctrl)
        zrow.pack(fill=tk.X, pady=(2, 4))
        ttk.Button(zrow, text="🔍 Zoom Part",
                   command=lambda: (self.v_fit_part.set(True), self._schedule_orient_redraw())).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(zrow, text="🌐 Full Bed",
                   command=lambda: (self.v_fit_part.set(False), self._schedule_orient_redraw())).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        shift = ttk.Frame(ctrl)
        shift.pack(fill=tk.X, pady=2)
        self._shift_row(shift, 0, "dX", self.o_dx)
        self._shift_row(shift, 1, "dY", self.o_dy)
        self._shift_row(shift, 2, "dZ", self.o_dz)
        ttk.Label(shift, text="Manual shift (mm, post auto-place)",
                  foreground="gray", font=("TkDefaultFont", 7)).grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(ctrl, text="Scale", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(3, 0))
        srow = ttk.Frame(ctrl)
        srow.pack(fill=tk.X)
        ttk.Entry(srow, textvariable=self.p_scale, width=7, font=("TkDefaultFont", 8)).pack(side=tk.LEFT)
        ttk.Label(srow, text="(same as params tab)", foreground="gray",
                  font=("TkDefaultFont", 7)).pack(side=tk.LEFT, padx=3)

        ttk.Label(ctrl, text="Mesh Visualization", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(4, 0))

        # 1. View Source Mode: FEA Conformal Mesh vs Raw CAD Surface
        src_row = ttk.Frame(ctrl)
        src_row.pack(fill=tk.X, pady=(1, 2))
        ttk.Label(src_row, text="Source:", font=("TkDefaultFont", 8, "bold")).pack(side=tk.LEFT)
        self.v_view_source = tk.StringVar(value="FEA Conformal Mesh")
        self.source_cb = ttk.Combobox(
            src_row, textvariable=self.v_view_source,
            values=["FEA Conformal Mesh", "Raw CAD Surface"],
            state="readonly", width=16, font=("TkDefaultFont", 8)
        )
        self.source_cb.pack(side=tk.LEFT, padx=3)
        self.source_cb.bind("<<ComboboxSelected>>", lambda *_: self._schedule_orient_redraw())

        # 2. Rendering Style
        m_row = ttk.Frame(ctrl)
        m_row.pack(fill=tk.X, pady=(1, 2))
        ttk.Label(m_row, text="Style:", font=("TkDefaultFont", 8)).pack(side=tk.LEFT)
        self.v_mesh_style = tk.StringVar(value="Nodes + Cells")
        style_cb = ttk.Combobox(
            m_row, textvariable=self.v_mesh_style,
            values=[
                "Nodes + Cells",
                "Shaded + Mesh",
                "Individual Nodes",
                "Wireframe Only",
                "Solid Shaded",
                "Cross-Section (Cut Tets)",
            ],
            state="readonly", width=16, font=("TkDefaultFont", 8)
        )
        style_cb.pack(side=tk.LEFT, padx=3)
        style_cb.bind("<<ComboboxSelected>>", lambda *_: self._schedule_orient_redraw())

        # 3. Feature Checkboxes
        chk_row1 = ttk.Frame(ctrl)
        chk_row1.pack(fill=tk.X, pady=1)
        self.v_show_nodes = tk.BooleanVar(value=True)
        ttk.Checkbutton(chk_row1, text="Show Nodes (●)", variable=self.v_show_nodes,
                        command=self._schedule_orient_redraw).pack(side=tk.LEFT)
        self.v_show_mesh = tk.BooleanVar(value=True)
        ttk.Checkbutton(chk_row1, text="Wireframe", variable=self.v_show_mesh,
                        command=self._schedule_orient_redraw).pack(side=tk.LEFT, padx=(6, 0))

        chk_row2 = ttk.Frame(ctrl)
        chk_row2.pack(fill=tk.X, pady=1)
        self.v_show_substrate = tk.BooleanVar(value=True)
        ttk.Checkbutton(chk_row2, text="Show Substrate Mesh", variable=self.v_show_substrate,
                        command=self._schedule_orient_redraw).pack(side=tk.LEFT)

        self.fit_var = tk.StringVar(value="Attach a model to preview.")
        self.fit_lbl = ttk.Label(ctrl, textvariable=self.fit_var, justify=tk.LEFT, wraplength=220, font=("TkDefaultFont", 8))
        self.fit_lbl.pack(anchor="w", pady=(4, 0))
        self.obounds_var = tk.StringVar(value="")
        ttk.Label(ctrl, textvariable=self.obounds_var, justify=tk.LEFT, wraplength=220,
                  foreground="gray", font=("TkDefaultFont", 7)).pack(anchor="w")
        btn_row = ttk.Frame(ctrl)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="Refresh", command=self._refresh_orient_view).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(btn_row, text="🚀 GPU 60 FPS", command=self._open_gpu_window).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        ttk.Label(ctrl, text="Drag to orbit - scroll to zoom.\nWhat you see is what slices.",
                  foreground="gray", font=("TkDefaultFont", 7), justify=tk.LEFT).pack(anchor="w", pady=(2, 0))

        view = ttk.Frame(self.tab_orient)
        view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.figO = Figure(figsize=(4.5, 3.2), dpi=90)
        self.axO = self.figO.add_subplot(111, projection="3d")
        self.canvasO = FigureCanvasTkAgg(self.figO, master=view)
        self.canvasO.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        for v in (self.o_rx, self.o_ry, self.o_rz):
            v.trace_add("write", lambda *_: self._schedule_orient_redraw())
        for v in (self.o_dx, self.o_dy, self.o_dz, self.p_scale):
            v.trace_add("write", lambda *_: self._schedule_orient_redraw())
        self.v_auto_place.trace_add("write", lambda *_: self._schedule_orient_redraw())
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _rot_row(self, parent, label, var):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=1)
        ttk.Label(row, text=label, width=3).pack(side=tk.LEFT)
        val = ttk.Label(row, text="0 deg", width=8)
        val.pack(side=tk.RIGHT)
        def on_move(*_):
            val.configure(text=f"{float(var.get()):.0f} deg")
        sc = ttk.Scale(row, from_=-180, to=180, variable=var, command=on_move)
        sc.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        var.trace_add("write", lambda *_: val.configure(text=f"{float(var.get()):.0f} deg"))

    def _shift_row(self, parent, r, label, var):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w")
        ttk.Entry(parent, textvariable=var, width=8).grid(row=r, column=1, padx=4, sticky="ew")
        ttk.Label(parent, text="mm", foreground="gray", font=("TkDefaultFont", 8)).grid(row=r, column=2, sticky="w")

    def _reset_orientation(self):
        self.o_rx.set(0.0); self.o_ry.set(0.0); self.o_rz.set(0.0)
        self.o_dx.set("0"); self.o_dy.set("0"); self.o_dz.set("0")
        self._schedule_orient_redraw()

    def _on_tab_changed(self, _event=None):
        try:
            if self.nb.select() == str(self.tab_orient):
                self._refresh_orient_view()
        except Exception:
            pass

    def _build_empirical_tab(self):
        """Build the Empirical Values tab with data from WAAM lecture slides."""
        import tkinter.font as tkfont
        nb = ttk.Notebook(self.tab_empirical)
        nb.pack(fill=tk.BOTH, expand=True)

        # --- Subtab 1: Metal Transfer Methods ---
        tab_transfer = ttk.Frame(nb, padding=8)
        nb.add(tab_transfer, text="Metal Transfer")
        ttk.Label(tab_transfer, text="MIG-WAAM Metal Transfer Methods & Deposit Rates",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        cols = ("Method", "Deposit Rate (kg/h)", "Current Range", "Notes")
        tree = ttk.Treeview(tab_transfer, columns=cols, show="headings", height=6)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=160 if c == "Method" else 130)
        data = [
            ("Short circuit / dip", "0.9 - 2.7", "Low (< 150A)", "Lowest heat input, good for thin walls"),
            ("Globular", "1.8 - 3.2", "Medium (150-200A)", "Gravity-dependent drop transfer"),
            ("Spray", "2.7 - 5.4", "High (> 200A)", "High deposition, directional"),
            ("Pulsed spray", "0.9 - 2.7", "Pulsed (varies)", "Controlled transfer, lower spatter"),
            ("Rotating spray", "6.3 - 13.5", "Very high (> 300A)", "Highest deposition rate"),
        ]
        for row in data:
            tree.insert("", tk.END, values=row)
        tree.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(tab_transfer, text="Source: IIT Goa WAAM Lecture slides (MIG-WAAM Deposition Process)",
                  foreground="gray", font=("TkDefaultFont", 8)).pack(anchor="w")

        # --- Subtab 2: Geometric Formulas ---
        tab_geom = ttk.Frame(nb, padding=8)
        nb.add(tab_geom, text="Bead Geometry")
        ttk.Label(tab_geom, text="Single Bead Geometric Modeling (Parabolic Profile)",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        formulas = [
            "Bead profile:    y = h [1 - (2x/w)^2]",
            "Bead area:       A = (2/3) h w",
            "Volume flow:     Q = (pi d^2 / 4) x v_wire  (v_wire in m/min)",
            "Bead width:      w = 3 pi v_wire(m/min) d^2 / (8 h v_torch(mm/min))",
            "Deposition rate: D_r = A_wire x v_wire x rho  (gm/min)",
            "",
            "Multi-bead stepover (optimal):  p/2 = w/3",
            "Contact angle:   theta = arcsin(4 h w / (4 h^2 + w^2))",
            "Layer height:    h_n = 2 R cos(theta_n)",
        ]
        for f in formulas:
            ttk.Label(tab_geom, text=f, font=("TkDefaultFont", 10),
                      foreground="#222" if f else "white").pack(anchor="w", pady=1)
        ttk.Label(tab_geom, text="Source: IIT Goa WAAM Lecture slides (Geometric Modeling)",
                  foreground="gray", font=("TkDefaultFont", 8)).pack(anchor="w", pady=(8, 0))

        # --- Subtab 3: Experimental Data ---
        tab_exp = ttk.Frame(nb, padding=8)
        nb.add(tab_exp, text="Experimental Data")
        ttk.Label(tab_exp, text="Experimental Parameter Sets (Champ Pulse 500)",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        cols2 = ("I (A)", "V (V)", "V_torch (mm/min)", "V_wire (m/min)", "Bead w (mm)", "Notes")
        tree2 = ttk.Treeview(tab_exp, columns=cols2, show="headings", height=6)
        for c in cols2:
            tree2.heading(c, text=c)
            tree2.column(c, width=90 if "mm" not in c else 110)
        exp_data = [
            ("70",  "25.9", "300", "0.0048",  "n/a", "Single bead, low current"),
            ("120", "19.0", "300", "0.0095",  "n/a", "Single bead"),
            ("140", "19.7", "400", "0.0119",  "n/a", "Higher speed"),
            ("200", "24.2", "300", "0.0199",  "n/a", "High current spray"),
        ]
        for row in exp_data:
            tree2.insert("", tk.END, values=row)
        tree2.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(tab_exp, text="Source: WhatsApp WAAM group (Pranay P, 14 Sep 2026)",
                  foreground="gray", font=("TkDefaultFont", 8)).pack(anchor="w")

        # --- Subtab 4: Power & Heat Input ---
        tab_power = ttk.Frame(nb, padding=8)
        nb.add(tab_power, text="Power & Heat Input")
        ttk.Label(tab_power, text="Power Calculation (Rosenthal-based)",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        power_formulas = [
            "P = [rho A_w v_w (c_p (T_m - T_0) + L)",
            "     + rho A_p v_t (c_p (T_m - T_0) + L)] / eta",
            "",
            "Where:",
            "  rho   = wire density (kg/m^3)",
            "  A_w   = pi d_w^2 / 4  (wire cross-section, mm^2)",
            "  v_w   = wire feed speed (m/min)",
            "  c_p   = specific heat capacity (J/kg K)",
            "  T_m   = melting temperature (K)",
            "  T_0   = ambient temperature (K)",
            "  L     = latent heat of fusion (J/kg)",
            "  A_p   = penetration area = (2/3) p_n w  (mm^2)",
            "  v_t   = torch speed (mm/min)",
            "  eta   = process efficiency",
            "",
            "Linear heat input:  HI = eta V I / v_torch  (J/mm)",
            "Arc power:          P  = V x I  (W)",
            "Net heat power:     P_net = eta x V x I  (W)",
        ]
        for f in power_formulas:
            ttk.Label(tab_power, text=f, font=("TkDefaultFont", 10),
                      foreground="#222" if f else "white").pack(anchor="w", pady=1)
        ttk.Label(tab_power, text="Example: V_t=800, h=2, p_n=0.5, d_w=0.8, i=100A, rho=7800, eta=0.9 => P=731.5 W",
                  foreground="gray", font=("TkDefaultFont", 8)).pack(anchor="w", pady=(8, 0))
        ttk.Label(tab_power, text="Source: IIT Goa WAAM Lecture slides (Slide 23)",
                  foreground="gray", font=("TkDefaultFont", 8)).pack(anchor="w")

        # --- Subtab 5: Material Properties ---
        tab_mat = ttk.Frame(nb, padding=8)
        nb.add(tab_mat, text="Material Properties")
        ttk.Label(tab_mat, text="Wire/Thermal Properties by Material",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        cols3 = ("Material", "Density (kg/m^3)", "c_p (J/kg K)", "k (W/m K)", "T_m (K)", "L (J/kg)")
        tree3 = ttk.Treeview(tab_mat, columns=cols3, show="headings", height=4)
        for c in cols3:
            tree3.heading(c, text=c)
            tree3.column(c, width=100)
        mat_data = [
            ("Steel (ER70S-6)", "7850", "500", "50",  "1800", "2.7e5"),
            ("Aluminium (ER4043)", "2700", "900", "237", "933",  "3.9e5"),
            ("Titanium (Ti-6Al-4V)", "4510", "520", "22",  "1941", "3.6e5"),
        ]
        for row in mat_data:
            tree3.insert("", tk.END, values=row)
        tree3.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(tab_mat, text="Source: IIT Goa WAAM Lecture slides + standard references",
                  foreground="gray", font=("TkDefaultFont", 8)).pack(anchor="w")

    def _current_limits_or_default(self):
        try:
            return MachineLimits(
                x_min=float(self.p_xmin.get()), x_max=float(self.p_xmax.get()),
                y_min=float(self.p_ymin.get()), y_max=float(self.p_ymax.get()),
                z_min=float(self.p_zmin.get()), z_max=float(self.p_zmax.get()),
                max_feed_rate=float(self.p_maxfeed.get() or 1000.0),
            )
        except Exception:
            return MachineLimits()

    def _read_orient(self):
        """Rotation/shift/scale from the UI, validated. Raises GCodeGenerationError."""
        import math
        try:
            rx, ry, rz = float(self.o_rx.get()), float(self.o_ry.get()), float(self.o_rz.get())
            dx, dy, dz = float(self.o_dx.get() or 0), float(self.o_dy.get() or 0), float(self.o_dz.get() or 0)
            sc = float(self.p_scale.get() or 1.0)
        except ValueError:
            raise GCodeGenerationError("Orientation/shift/scale fields must be numbers.")
        for name, val in (("rotation", rx), ("rotation", ry), ("rotation", rz),
                          ("shift", dx), ("shift", dy), ("shift", dz), ("scale", sc)):
            if not math.isfinite(val):
                raise GCodeGenerationError(f"Orientation {name} must be finite, got {val}.")
        if sc <= 0:
            raise GCodeGenerationError(f"Scale must be positive, got {sc}.")
        return rx, ry, rz, dx, dy, dz, sc

    def _place_mesh(self, mesh, rx, ry, rz, dx, dy, dz, limits, auto_place, log):
        """Shared placement pipeline: rotate -> auto-place -> manual shift. Used by preview AND slice job."""
        if rx or ry or rz:
            apply_orientation(mesh, rx, ry, rz)
            log(f"  Rotated ({rx:g}, {ry:g}, {rz:g})deg about centroid; bounds={mesh.bounds.tolist()}")
        if auto_place:
            place_warns: list = []
            shift = auto_place_mesh(mesh, limits, _warn=place_warns)
            for w in place_warns:
                log(f"  [warn] {w}")
            if shift is not None:
                log(f"  Auto-placed by ({shift[0]:.1f}, {shift[1]:.1f}, {shift[2]:.1f})mm")
        if dx or dy or dz:
            mesh.apply_translation([dx, dy, dz])
            log(f"  Manual shift ({dx:g}, {dy:g}, {dz:g})mm; bounds={mesh.bounds.tolist()}")

    PREVIEW_MAX_FACES = 8000  # live view draws a subset; slicing always uses the full mesh

    def _refresh_orient_view(self):
        """Start a BACKGROUND load of the preview mesh (complex parts take
        seconds - never block the UI thread). Result is picked up by the
        polling loop via _preview_result."""
        path = self.stl_var.get().strip()
        if not path or not os.path.isfile(path):
            self.preview_base = None
            self.preview_path = ""
            self._preview_loading_for = ""
            self._draw_parametric_mesh()
            return
        if path == self.preview_path and self.preview_base is not None:
            self._redraw_orient()
            return
        if path == getattr(self, "_preview_loading_for", ""):
            return  # load already in flight
        self._preview_loading_for = path
        self.preview_base = None  # mark stale so sliders can't draw the old part
        self._preview_gen += 1
        gen = self._preview_gen
        self._draw_orient_empty("Loading preview in background - watch here...")
        threading.Thread(target=self._preview_load_thread, args=(path, gen),
                         daemon=True).start()

    def _preview_load_thread(self, path, gen):
        try:
            base, _rep = load_mesh(path, strict=False, scale=1.0)
            n = len(base.faces)
            idx = None
            if n > self.PREVIEW_MAX_FACES:
                idx = list(np.random.default_rng(0).choice(
                    n, size=self.PREVIEW_MAX_FACES, replace=False))
            # hand off WITHOUT touching Tk (wrong thread) - the poll loop delivers it
            self._preview_result = (gen, path, base, idx, None)
        except Exception as e:  # noqa - surfaced in the fit label
            self._preview_result = (gen, path, None, None, str(e))

    def _preview_loaded(self, gen, path, base, idx, err):
        if gen != self._preview_gen:
            return  # superseded by a newer attach
        self._preview_loading_for = ""
        if err is not None or base is None:
            self.preview_base = None
            self.preview_path = ""
            self._preview_face_idx = None
            self._draw_parametric_mesh(f"Preview notice: {err}")
            return
        self.preview_base = base
        self.preview_path = path
        self._preview_face_idx = idx
        self._redraw_orient()

    def _open_gpu_window(self):
        """Launch the standalone hardware-accelerated PyVista / VTK GPU window (60 FPS C++ engine)."""
        try:
            if hasattr(self, "app") and self.app and hasattr(self.app, "_open_pyvista_window"):
                if self.fea_mesh_path:
                    self.app.loaded_mesh_path = self.fea_mesh_path
                    self.app.mesh_file_var.set(self.fea_mesh_path)
                self.app._open_pyvista_window()
            else:
                import subprocess
                cand_mesh = self.fea_mesh_path or self.stl_var.get().strip()
                if cand_mesh:
                    cmd = [
                        sys.executable, "-c",
                        f"import pyvista as pv; m = pv.read({repr(cand_mesh)}); "
                        f"p = pv.Plotter(title='WAAM Hardware GPU Viewport (VTK)'); "
                        f"p.add_mesh(m, show_edges=True, cmap='plasma'); p.show()"
                    ]
                    subprocess.Popen(cmd)
        except Exception as e:
            messagebox.showerror("GPU Window Error", f"Could not launch GPU 3D window: {e}")

    def _schedule_orient_redraw(self):
        if self._orient_after is not None:
            try:
                self.after_cancel(self._orient_after)
            except Exception:
                pass
        self._orient_after = self.after(160, self._redraw_orient)

    def _draw_orient_empty(self, msg):
        self.axO.clear()
        self.axO.set_title(msg)
        self.axO.set_xlabel("X (mm)"); self.axO.set_ylabel("Y (mm)"); self.axO.set_zlabel("Z (mm)")
        self._apply_mpl_theme(self.figO, self.axO)
        self.canvasO.draw()
        self.fit_var.set(msg)
        self.fit_lbl.configure(foreground="gray")
        self.obounds_var.set("")

    def _redraw_orient(self):
        self._orient_after = None
        source_mode = self.v_view_source.get() if hasattr(self, "v_view_source") and self.v_view_source else "Raw CAD Surface"
        if source_mode == "FEA Conformal Mesh" and self.fea_mesh is not None:
            try:
                self._redraw_fea_mesh_inner()
                return
            except Exception as e:
                self.fit_var.set(f"FEA Preview Notice: {e}")
                self.fit_lbl.configure(foreground="red")

        if self.preview_base is None:
            path = self.stl_var.get().strip()
            if path and os.path.isfile(path):
                self._refresh_orient_view()
            else:
                self._draw_parametric_mesh()
            return
        try:
            self._redraw_orient_inner()
        except GCodeGenerationError as e:
            self.fit_var.set(str(e))
            self.fit_lbl.configure(foreground="red")
        except Exception as e:  # noqa - a preview must never take down the GUI
            self.fit_var.set(f"Preview error (slice job unaffected): {e}")
            self.fit_lbl.configure(foreground="red")

    def _redraw_fea_mesh_inner(self):
        fea = self.fea_mesh
        if not fea:
            return
        # Signature dedup: parameter edits fire update_mesh() with unchanged
        # mesh/orientation/style; skip the expensive axO.clear() + full
        # matplotlib redraw when nothing visual actually changed.
        try:
            _sig = (
                os.path.abspath(fea.get("path", '')),
                fea.get("n_nodes", -1),
                self._read_orient(),
                str(self.v_view_source.get()),
                str(self.v_mesh_style.get()),
                bool(self.v_show_mesh.get()) if hasattr(self, "v_show_mesh") else True,
                bool(self.v_show_nodes.get()) if hasattr(self, "v_show_nodes") else True,
                bool(self.v_show_substrate.get()) if hasattr(self, "v_show_substrate") else True,
                bool(self.v_auto_place.get()),
                bool(self.v_fit_part.get()) if hasattr(self, "v_fit_part") else True,
            )
        except Exception:
            _sig = None
        if _sig is not None and _sig == getattr(self, "_last_fea_sig", None):
            return
        self._last_fea_sig = _sig
        try:
            rx, ry, rz, dx, dy, dz, sc = self._read_orient()
        except GCodeGenerationError as e:
            self.fit_var.set(str(e))
            self.fit_lbl.configure(foreground="red")
            return

        limits = self._current_limits_or_default()
        pts = fea["points"].copy()
        triangles = fea["triangles"]
        tets = fea["tetrahedra"]
        tri_labels = fea["tri_labels"]
        n_nodes = fea["n_nodes"]
        n_tets = fea["n_tets"]
        n_triangles = fea["n_triangles"]

        if abs(sc - 1.0) > 1e-12:
            pts *= sc

        # Auto-place: align center of substrate with bed center
        if bool(self.v_auto_place.get()):
            bed_cx = (limits.x_min + limits.x_max) / 2.0
            bed_cy = (limits.y_min + limits.y_max) / 2.0
            sub_cx = 75.0 * sc
            sub_cy = 75.0 * sc
            pts[:, 0] += (bed_cx - sub_cx) + dx
            pts[:, 1] += (bed_cy - sub_cy) + dy
            pts[:, 2] += dz
        else:
            pts[:, 0] += dx
            pts[:, 1] += dy
            pts[:, 2] += dz

        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        self.axO.clear()

        style_str = self.v_mesh_style.get() if hasattr(self, "v_mesh_style") else "Nodes + Cells"
        show_wire = getattr(self, "v_show_mesh", None) is None or bool(self.v_show_mesh.get())
        show_nodes = getattr(self, "v_show_nodes", None) is None or bool(self.v_show_nodes.get())
        show_sub = getattr(self, "v_show_substrate", None) is None or bool(self.v_show_substrate.get())

        # Distinguish deposit vs substrate facets & nodes
        tri_cz = pts[triangles, 2].mean(axis=1) if len(triangles) else np.array([])
        sub_h = 5.0 * sc + dz
        is_deposit_tri = (tri_cz > (sub_h + 0.05)) | (tri_labels == 5)
        is_sub_tri = ~is_deposit_tri

        # Cross-Section / Cut mode check
        if style_str == "Cross-Section (Cut Tets)" and len(tets):
            bmin_p = pts.min(axis=0)
            bmax_p = pts.max(axis=0)
            y_mid = (bmin_p[1] + bmax_p[1]) / 2.0
            tet_cy = pts[tets, 1].mean(axis=1)
            sel_tets = tets[tet_cy <= y_mid]
            if len(sel_tets):
                if len(sel_tets) > 5000:
                    sel_tets = sel_tets[:5000]
                f1 = sel_tets[:, [0, 1, 2]]
                f2 = sel_tets[:, [0, 2, 3]]
                f3 = sel_tets[:, [0, 3, 1]]
                f4 = sel_tets[:, [1, 3, 2]]
                all_cut_faces = np.vstack([f1, f2, f3, f4])
                cut_coords = pts[all_cut_faces]
                self.axO.add_collection3d(Poly3DCollection(
                    cut_coords, facecolor="#38bdf8",
                    edgecolor="#0284c7" if show_wire else (0.0, 0.0, 0.0, 0.0),
                    linewidths=0.4 if show_wire else 0.0, alpha=0.75))
        else:
            # 1. Deposit triangles
            if np.any(is_deposit_tri):
                dep_tris = triangles[is_deposit_tri]
                if style_str == "Wireframe Only":
                    dfc, dec, dlw, dalpha = (0.0, 0.0, 0.0, 0.0), "#0284c7", 0.7, 1.0
                elif style_str == "Solid Shaded":
                    dfc, dec, dlw, dalpha = "#38bdf8", (0.0, 0.0, 0.0, 0.0), 0.0, 0.88
                elif style_str == "Individual Nodes":
                    dfc, dec, dlw, dalpha = (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), 0.0, 0.0
                else:  # "Nodes + Cells" or "Shaded + Mesh"
                    dfc = "#38bdf8"
                    dec = "#0284c7" if show_wire else (0.0, 0.0, 0.0, 0.0)
                    dlw = 0.4 if show_wire else 0.0
                    dalpha = 0.75
                if dalpha > 0:
                    dep_coords = pts[dep_tris]
                    if len(dep_coords) > 2500:
                        idx_dt = np.random.default_rng(0).choice(len(dep_coords), size=2500, replace=False)
                        dep_coords = dep_coords[idx_dt]
                    self.axO.add_collection3d(Poly3DCollection(
                        dep_coords, facecolor=dfc, edgecolor=dec, linewidths=dlw, alpha=dalpha))

            # 2. Substrate triangles (if enabled)
            if show_sub and np.any(is_sub_tri) and style_str != "Individual Nodes":
                sub_tris = triangles[is_sub_tri]
                sfc = "#64748b" if style_str != "Wireframe Only" else (0.0, 0.0, 0.0, 0.0)
                sec = "#475569" if show_wire else (0.0, 0.0, 0.0, 0.0)
                slw = 0.3 if show_wire else 0.0
                salpha = 0.35 if style_str != "Wireframe Only" else 0.8
                sub_coords = pts[sub_tris]
                if len(sub_coords) > 800:
                    idx_st = np.random.default_rng(0).choice(len(sub_coords), size=800, replace=False)
                    sub_coords = sub_coords[idx_st]
                self.axO.add_collection3d(Poly3DCollection(
                    sub_coords, facecolor=sfc, edgecolor=sec, linewidths=slw, alpha=salpha))

        # 3. Individual FEA Nodes Rendering (Fast LOD for instant response)
        if (show_nodes or style_str in ("Nodes + Cells", "Individual Nodes")) and style_str != "Solid Shaded":
            try:
                is_dep_pt = pts[:, 2] > (sub_h + 0.05)
                part_pts = pts[is_dep_pt]
                if len(part_pts):
                    if len(part_pts) > 1000:
                        idx_pt = np.random.default_rng(0).choice(len(part_pts), 1000, replace=False)
                        plot_pts = part_pts[idx_pt]
                    else:
                        plot_pts = part_pts
                    self.axO.scatter(
                        plot_pts[:, 0], plot_pts[:, 1], plot_pts[:, 2],
                        c=plot_pts[:, 2], cmap="plasma", s=6, alpha=0.8,
                        depthshade=False, edgecolors="none")

                if show_sub:
                    sub_pts = pts[~is_dep_pt]
                    if len(sub_pts):
                        if len(sub_pts) > 300:
                            idx_sp = np.random.default_rng(0).choice(len(sub_pts), 300, replace=False)
                            sub_plot = sub_pts[idx_sp]
                        else:
                            sub_plot = sub_pts
                        self.axO.scatter(
                            sub_plot[:, 0], sub_plot[:, 1], sub_plot[:, 2],
                            c="#64748b", s=3, alpha=0.3, depthshade=False, edgecolors="none")
            except Exception:
                pass

        # Camera & Bounding Setup
        bmin = pts.min(axis=0)
        bmax = pts.max(axis=0)
        fit_part = getattr(self, "v_fit_part", None) is None or bool(self.v_fit_part.get())

        if fit_part:
            dep_pts = pts[pts[:, 2] > (sub_h + 0.05)]
            c_pts = dep_pts if len(dep_pts) else pts
            p_bmin = c_pts.min(axis=0)
            p_bmax = c_pts.max(axis=0)
            center = (p_bmin + p_bmax) / 2.0
            span = np.maximum(p_bmax - p_bmin, 8.0)
            max_span = float(np.max(span))
            half = max_span * 0.75
            self.axO.set_xlim(center[0] - half, center[0] + half)
            self.axO.set_ylim(center[1] - half, center[1] + half)
            self.axO.set_zlim(max(limits.z_min, center[2] - half), center[2] + half)
            try:
                self.axO.set_box_aspect((1, 1, 1))
            except Exception:
                pass
        else:
            self._draw_envelope(self.axO, limits)
            self.axO.set_xlim(limits.x_min, limits.x_max)
            self.axO.set_ylim(limits.y_min, limits.y_max)
            self.axO.set_zlim(limits.z_min, limits.z_max)
            try:
                self.axO.set_box_aspect((
                    limits.x_max - limits.x_min,
                    limits.y_max - limits.y_min,
                    limits.z_max - limits.z_min))
            except Exception:
                pass

        self.axO.set_xlabel("X (mm)")
        self.axO.set_ylabel("Y (mm)")
        self.axO.set_zlabel("Z (mm)")
        self.axO.set_title(
            f"3D FEA Mesh: {n_nodes:,} Nodes | {n_tets:,} Tets ({style_str})",
            fontsize=9)
        self._apply_mpl_theme(self.figO, self.axO)
        self.canvasO.draw()

        size = bmax - bmin
        dep_pts = pts[pts[:, 2] > (sub_h + 0.05)]
        part_size = (dep_pts.max(axis=0) - dep_pts.min(axis=0)) if len(dep_pts) else size
        self.obounds_var.set(
            f"FEA Conformal Mesh: {n_nodes:,} Nodes | {n_tets:,} Tets\n"
            f"Part Envelope: {part_size[0]:.1f} x {part_size[1]:.1f} x {part_size[2]:.1f} mm\n"
            f"Substrate Plate: {size[0]:.1f} x {size[1]:.1f} x 5.0 mm\n"
            f"Boundary Facets: {n_triangles:,} surface cells\n"
            f"Pos: [{bmin[0]:.1f}..{bmax[0]:.1f}] [{bmin[1]:.1f}..{bmax[1]:.1f}] [{bmin[2]:.1f}..{bmax[2]:.1f}]"
        )
        self.fit_var.set("FEA Conformal Mesh Active — Ready for Simulation & Slicing.")
        self.fit_lbl.configure(foreground="green")

    def _redraw_orient_inner(self):
        try:
            rx, ry, rz, dx, dy, dz, sc = self._read_orient()
        except GCodeGenerationError as e:
            self.fit_var.set(str(e))
            self.fit_lbl.configure(foreground="red")
            return
        limits = self._current_limits_or_default()
        mesh = self.preview_base.copy()
        if abs(sc - 1.0) > 1e-12:
            mesh.apply_scale(sc)
        self._place_mesh(mesh, rx, ry, rz, dx, dy, dz, limits,
                         bool(self.v_auto_place.get()), log=lambda *_: None)

        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        self.axO.clear()
        idx = getattr(self, "_preview_face_idx", None)
        if idx is not None:
            try:
                sub = mesh.submesh([idx], append=True)
            except Exception:
                sub = mesh
        else:
            sub = mesh
        tris = sub.triangles
        if len(tris):
            style = getattr(self, "v_mesh_style", None)
            style_str = style.get() if style else "Shaded + Mesh"
            show_wire = getattr(self, "v_show_mesh", None) is None or bool(self.v_show_mesh.get())
            if style_str == "Wireframe Only":
                fc = (0.0, 0.0, 0.0, 0.0)
                ec = "#2563eb"
                lw = 0.8
                alpha = 1.0
            elif style_str == "Solid Shaded":
                fc = "#38bdf8"
                ec = (0.0, 0.0, 0.0, 0.0)
                lw = 0.0
                alpha = 0.85
            else:  # "Shaded + Mesh"
                fc = "#38bdf8"
                ec = "#0f172a" if show_wire else (0.0, 0.0, 0.0, 0.0)
                lw = 0.5 if show_wire else 0.0
                alpha = 0.80
            self.axO.add_collection3d(Poly3DCollection(
                tris, facecolor=fc, edgecolor=ec, linewidths=lw, alpha=alpha))
        bmin, bmax = mesh.bounds
        fit_part = getattr(self, "v_fit_part", None) is None or bool(self.v_fit_part.get())
        if fit_part:
            import numpy as np
            center = (bmin + bmax) / 2.0
            span = np.maximum(bmax - bmin, 8.0)
            max_span = float(np.max(span))
            half = max_span * 0.75
            self.axO.set_xlim(center[0] - half, center[0] + half)
            self.axO.set_ylim(center[1] - half, center[1] + half)
            self.axO.set_zlim(max(limits.z_min, center[2] - half), center[2] + half)
            try:
                self.axO.set_box_aspect((1, 1, 1))
            except Exception:
                pass
            sub_w = max_span * 1.4
            sx0, sx1 = center[0] - sub_w / 2, center[0] + sub_w / 2
            sy0, sy1 = center[1] - sub_w / 2, center[1] + sub_w / 2
            sz0 = limits.z_min
            bed_corners = [
                [[sx0, sy0, sz0], [sx1, sy0, sz0], [sx1, sy1, sz0], [sx0, sy1, sz0]]
            ]
            self.axO.add_collection3d(Poly3DCollection(
                bed_corners, facecolor="#64748b", edgecolor="#94a3b8", alpha=0.35, linewidths=1.0))
            self.axO.plot([sx0, sx1, sx1, sx0, sx0], [sy0, sy0, sy1, sy1, sy0], [sz0, sz0, sz0, sz0, sz0],
                          color="#777777", linestyle="--", linewidth=1.0, alpha=0.7)
        else:
            self._draw_envelope(self.axO, limits)
            self.axO.set_xlim(limits.x_min, limits.x_max)
            self.axO.set_ylim(limits.y_min, limits.y_max)
            self.axO.set_zlim(limits.z_min, limits.z_max)
            try:
                self.axO.set_box_aspect((
                    limits.x_max - limits.x_min,
                    limits.y_max - limits.y_min,
                    limits.z_max - limits.z_min))
            except Exception:
                pass
        self.axO.set_xlabel("X (mm)"); self.axO.set_ylabel("Y (mm)"); self.axO.set_zlabel("Z (mm)")
        self.axO.set_title(f"3D Mesh View: rx={rx:g} ry={ry:g} rz={rz:g}  scale={sc:g}" + (" (zoom: part)" if fit_part else " (zoom: envelope)"))
        self._apply_mpl_theme(self.figO, self.axO)
        self.canvasO.draw()

        import numpy as np
        size = bmax - bmin
        env = np.array([limits.x_max - limits.x_min, limits.y_max - limits.y_min,
                        limits.z_max - limits.z_min])
        self.obounds_var.set(
            f"Mesh: {len(mesh.vertices):,} Vertices | {len(mesh.faces):,} Triangles\n"
            f"Size: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm\n"
            f"Pos: [{bmin[0]:.1f}..{bmax[0]:.1f}] [{bmin[1]:.1f}..{bmax[1]:.1f}] [{bmin[2]:.1f}..{bmax[2]:.1f}]"
            + (f"\nPreview decimated to {self.PREVIEW_MAX_FACES} faces (slice uses all {len(mesh.faces)})."
               if getattr(self, "_preview_face_idx", None) is not None else ""))
        if bool((size > env + 1e-6).any()):
            self.fit_var.set("TOO BIG for envelope - increase scale-down or split the part.")
            self.fit_lbl.configure(foreground="red")
        elif bool(((bmin < [limits.x_min, limits.y_min, limits.z_min]) |
                   (bmax > [limits.x_max, limits.y_max, limits.z_max])).any()):
            self.fit_var.set("Fits in size but sits OUTSIDE the envelope - enable auto-place.")
            self.fit_lbl.configure(foreground="orange")
        else:
            self.fit_var.set("FITS - ready to slice.")
            self.fit_lbl.configure(foreground="green")

    def _draw_parametric_mesh(self, custom_msg: str = ""):
        """Render the parametric WAAM workpiece and FE mesh domain when no external STL is loaded."""
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import numpy as np

        self.axO.clear()
        try:
            lx = float(getattr(self, "p_lx_val", 150.0))
            ly = float(getattr(self, "p_ly_val", 150.0))
            hz_base = float(getattr(self, "p_hz_val", 5.0))
            hb = float(self.p_layer_h.get() or 2.0)
            w = float(self.p_bead_w.get() or 5.0)
            nl = int(getattr(self, "p_nl_val", 8))
        except Exception:
            lx, ly, hz_base, hb, w, nl = 150.0, 150.0, 5.0, 2.0, 5.0, 8

        hz_dep = nl * hb
        y_mid = ly / 2.0
        y_min = max(0.0, y_mid - w / 2.0)
        y_max = min(ly, y_mid + w / 2.0)

        show_wire = getattr(self, "v_show_mesh", None) is None or bool(self.v_show_mesh.get())
        style = getattr(self, "v_mesh_style", None)
        style_str = style.get() if style else "Shaded + Mesh"
        ec = "#0f172a" if show_wire else (0.0, 0.0, 0.0, 0.0)
        lw = 0.5 if show_wire else 0.0

        # Substrate plate box
        v_sub = np.array([
            [0, 0, 0], [lx, 0, 0], [lx, ly, 0], [0, ly, 0],
            [0, 0, hz_base], [lx, 0, hz_base], [lx, ly, hz_base], [0, ly, hz_base]
        ])
        sub_faces = [
            [v_sub[0], v_sub[1], v_sub[2], v_sub[3]],
            [v_sub[4], v_sub[5], v_sub[6], v_sub[7]],
            [v_sub[0], v_sub[1], v_sub[5], v_sub[4]],
            [v_sub[2], v_sub[3], v_sub[7], v_sub[6]],
            [v_sub[0], v_sub[3], v_sub[7], v_sub[4]],
            [v_sub[1], v_sub[2], v_sub[6], v_sub[5]],
        ]
        self.axO.add_collection3d(Poly3DCollection(
            sub_faces, facecolor="#475569", edgecolor="#64748b" if show_wire else (0.0, 0.0, 0.0, 0.0),
            linewidths=0.6, alpha=0.35))

        # Substrate mesh grid lines
        nx_b, ny_b = 6, 6
        for xi in np.linspace(0, lx, nx_b + 1):
            self.axO.plot([xi, xi], [0, ly], [hz_base, hz_base], color="#94a3b8", linewidth=0.5, alpha=0.5)
        for yi in np.linspace(0, ly, ny_b + 1):
            self.axO.plot([0, lx], [yi, yi], [hz_base, hz_base], color="#94a3b8", linewidth=0.5, alpha=0.5)

        # Deposited Bead Layers
        layer_colors = ["#38bdf8", "#0284c7", "#0ea5e9", "#0369a1"]
        for i in range(nl):
            z0 = hz_base + i * hb
            z1 = hz_base + (i + 1) * hb
            v_lay = np.array([
                [0, y_min, z0], [lx, y_min, z0], [lx, y_max, z0], [0, y_max, z0],
                [0, y_min, z1], [lx, y_min, z1], [lx, y_max, z1], [0, y_max, z1]
            ])
            lay_faces = [
                [v_lay[4], v_lay[5], v_lay[6], v_lay[7]],
                [v_lay[0], v_lay[1], v_lay[5], v_lay[4]],
                [v_lay[2], v_lay[3], v_lay[7], v_lay[6]],
                [v_lay[0], v_lay[3], v_lay[7], v_lay[4]],
                [v_lay[1], v_lay[2], v_lay[6], v_lay[5]],
            ]
            fc = (0.0, 0.0, 0.0, 0.0) if style_str == "Wireframe Only" else layer_colors[i % len(layer_colors)]
            self.axO.add_collection3d(Poly3DCollection(
                lay_faces, facecolor=fc, edgecolor=ec, linewidths=lw, alpha=0.82))

        # Torch and travel centerline on top layer
        z_top = hz_base + hz_dep
        self.axO.plot([0, lx], [y_mid, y_mid], [z_top, z_top], color="#ef4444", linestyle="--", linewidth=1.5, alpha=0.9)
        self.axO.scatter([lx * 0.6], [y_mid], [z_top], color="#f59e0b", s=60, edgecolors="#b45309", linewidths=1.5)

        margin = max(lx, ly) * 0.1
        self.axO.set_xlim(-margin, lx + margin)
        self.axO.set_ylim(-margin, ly + margin)
        self.axO.set_zlim(0, max(z_top + 20.0, 30.0))
        try:
            self.axO.set_box_aspect((1, 1, 0.45))
        except Exception:
            pass

        self.axO.set_xlabel("X (mm)"); self.axO.set_ylabel("Y (mm)"); self.axO.set_zlabel("Z (mm)")
        title_str = custom_msg if custom_msg else f"Parametric WAAM Mesh: {nl} Layers | Lx={lx:.0f}mm, W={w:.1f}mm, H={hz_dep:.1f}mm"
        self.axO.set_title(title_str)
        self._apply_mpl_theme(self.figO, self.axO)
        self.canvasO.draw()

        self.obounds_var.set(
            f"Parametric Workpiece:\n"
            f"Substrate: {lx:.0f} x {ly:.0f} x {hz_base:.1f} mm\n"
            f"Deposit Wall: {lx:.0f} x {w:.1f} x {hz_dep:.1f} mm ({nl} Layers)\n"
            f"Grid: Conformal Hex/Tet bonded interface"
        )
        self.fit_var.set("Parametric Workpiece active. Ready to slice or attach CAD STL above.")
        self.fit_lbl.configure(foreground="#0284c7")

    @staticmethod
    def _draw_envelope(ax, limits):
        x0, x1 = limits.x_min, limits.x_max
        y0, y1 = limits.y_min, limits.y_max
        z0, z1 = limits.z_min, limits.z_max
        corners = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        for a, b in edges:
            ax.plot([corners[a][0], corners[b][0]],
                    [corners[a][1], corners[b][1]],
                    [corners[a][2], corners[b][2]], color="gray", lw=0.8)
        # build plate
        ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], [z0] * 5, color="black", lw=1.2)

    # ---------------- file dialogs ----------------
    def browse_stl(self):
        p = filedialog.askopenfilename(title="Attach mesh file",
                                       filetypes=[("Mesh / CAD", "*.stl *.3mf *.obj *.step *.stp *.iges *.igs"),
                                                  ("All", "*.*")],
                                       initialdir=_THIS_DIR)
        if p:
            old = self.stl_var.get().strip()
            self.stl_var.set(p)
            self.log(f"Attached: {p}")
            self.preview_base = None  # force preview reload
            if p != old:
                # transforms belong to the previous file - a stale 0.1 scale on a
                # new part is exactly how silent mis-slices happen (cf. rocket_v2).
                self.p_scale.set("1.0")
                self._reset_orientation()
                self.log("Scale/orientation reset for the new file.")
                try:
                    self.nb.select(self.tab_orient)  # show the model immediately
                except Exception:
                    pass
            self._schedule_orient_redraw()

    def browse_out(self):
        p = filedialog.asksaveasfilename(title="Output G-code",
                                         defaultextension=".gcode",
                                         filetypes=[("G-code", "*.gcode *.tap *.nc"), ("All", "*.*")],
                                         initialfile="output.gcode")
        if p:
            self.out_var.set(p)

    def open_out_folder(self):
        import subprocess
        d = os.path.dirname(os.path.abspath(self.out_var.get())) or os.getcwd()
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", d])
            elif sys.platform.startswith("win"):
                os.startfile(d)  # noqa
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception as e:
            messagebox.showinfo("Output folder", f"{d}\n({e})")

    # ---------------- theme ----------------
    THEMES = {
        "light": dict(bg="#f0f0f0", fg="#111111", field="#ffffff", text_bg="#ffffff",
                      text_fg="#111111", fig="#ffffff", ax="#ffffff", txt="#111111",
                      grid="#cccccc", accent="#0066cc"),
        "dark": dict(bg="#2b2b2b", fg="#e8e8e8", field="#3a3a3a", text_bg="#1e1e1e",
                     text_fg="#e8e8e8", fig="#1e1e1e", ax="#242424", txt="#e8e8e8",
                     grid="#555555", accent="#4da3ff"),
    }

    def toggle_theme(self):
        self.theme_var.set("dark" if self.theme_var.get() == "light" else "light")
        self.apply_theme()

    def apply_theme(self):
        name = self.theme_var.get()
        if hasattr(self, "theme_btn"):
            self.theme_btn.configure(text=f"Theme: {name}")
        t = self.THEMES.get(name, self.THEMES["light"])
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=t["bg"], foreground=t["fg"])
        st.configure("TFrame", background=t["bg"])
        st.configure("TLabel", background=t["bg"], foreground=t["fg"])
        st.configure("TButton", background=t["field"], foreground=t["fg"])
        st.configure("TCheckbutton", background=t["bg"], foreground=t["fg"])
        st.configure("TEntry", fieldbackground=t["field"], foreground=t["fg"])
        st.configure("TCombobox", fieldbackground=t["field"], foreground=t["fg"],
                     background=t["field"])
        st.configure("TNotebook", background=t["bg"])
        st.configure("TNotebook.Tab", background=t["field"], foreground=t["fg"])
        st.configure("Horizontal.TProgressbar", background=t["accent"])
        if hasattr(self, "left_scroll"):
            try:
                self.left_scroll.canvas.configure(bg=t["bg"])
            except Exception:
                pass
        if hasattr(self, "log_text"):
            self.log_text.configure(bg=t["text_bg"], fg=t["text_fg"],
                                    insertbackground=t["text_fg"])
        for fig, ax in self._mpl_axes():
            self._apply_mpl_theme(fig, ax)

    def _mpl_axes(self):
        out = []
        for fig_name, ax_name in (("fig2d", "ax2d"), ("fig3d", "ax3d"), ("figO", "axO")):
            fig = getattr(self, fig_name, None)
            ax = getattr(self, ax_name, None)
            if fig is not None and ax is not None:
                out.append((fig, ax))
        return out

    def _apply_mpl_theme(self, fig, ax):
        t = self.THEMES.get(self.theme_var.get(), self.THEMES["light"])
        try:
            fig.patch.set_facecolor(t["fig"])
            ax.set_facecolor(t["ax"])
            ax.title.set_color(t["txt"])
            ax.xaxis.label.set_color(t["txt"])
            ax.yaxis.label.set_color(t["txt"])
            try:
                ax.zaxis.label.set_color(t["txt"])
            except Exception:
                pass
            ax.tick_params(colors=t["txt"])
            for spine in ax.spines.values():
                spine.set_color(t["grid"])
            for pane in ("xaxis", "yaxis", "zaxis"):
                try:
                    getattr(ax, pane).pane.set_facecolor(t["ax"])
                    getattr(ax, pane).pane.set_edgecolor(t["grid"])
                except Exception:
                    pass
            fig.canvas.draw_idle()
        except Exception:
            pass

    # ---------------- results ----------------
    def _clear_results(self):
        """Wipe generated data (toolpaths, previews, stats) - also called on each new run."""
        self.toolpaths = []
        self.layers = []
        self.mesh = None
        self.mesh_report = None
        self.last_gcode_path = ""
        self.stats_var.set("")
        if hasattr(self, "status_var") and (self.worker is None or not self.worker.is_alive()):
            self.status_var.set("idle")
        for slider, var in ((getattr(self, "layer_slider", None), getattr(self, "layer_idx", None)),
                            (getattr(self, "twin_slider", None), getattr(self, "twin_n", None))):
            try:
                if slider is not None:
                    slider.configure(to=0)
                if var is not None:
                    var.set(0)
            except Exception:
                pass
        try:
            self.draw_layer()
        except Exception:
            pass
        try:
            self.draw_twin()
        except Exception:
            pass

    # ---------------- logging ----------------
    def log(self, msg):
        self.log_text.insert(tk.END, str(msg) + "\n")
        self.log_text.see(tk.END)

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self.log_q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self._on_job_done(payload)
                elif kind == "fail":
                    self._on_job_fail(payload)
        except queue.Empty:
            pass
        if self._preview_result is not None:  # background preview-load handoff (main thread)
            res, self._preview_result = self._preview_result, None
            try:
                self._preview_loaded(*res)
            except Exception:
                pass
        self.after(120, self._poll_log_queue)

    # ---------------- job ----------------
    def _read_params(self):
        def f(var, name, allow_blank_none=False, is_int=False):
            s = var.get().strip()
            if allow_blank_none and s == "":
                return None
            try:
                return int(s) if is_int else float(s)
            except ValueError:
                raise GCodeGenerationError(f"Parameter `{name}` is not a number: `{s}`.")

        bead_w = f(self.p_bead_w, "bead-width")
        raw_wfs = f(self.p_wfs, "wire-feed-speed", allow_blank_none=True)
        if raw_wfs is not None and raw_wfs > 100.0:
            # User entered mm/min (e.g. 3000 mm/min = 3.0 m/min); auto-convert
            raw_wfs = raw_wfs / 1000.0
        return dict(
            layer_height=f(self.p_layer_h, "layer-height"),
            bead_width=bead_w,
            perimeters=f(self.p_perim, "perimeters", is_int=True),
            travel_speed=f(self.p_travel, "travel-speed"),
            weld_speed=f(self.p_weld, "weld-speed"),
            wire_feed_speed=raw_wfs,
            infill_angle_step=f(self.p_infill_step, "infill-angle-step"),
            interlayer_dwell=f(self.p_dwell, "interlayer-dwell"),
            lead_in_out=f(self.p_lead, "lead-in-out"),
            arc_on=self.p_arc_on.get().strip() or "M3",
            arc_off=self.p_arc_off.get().strip() or "M5",
            wf_on=self.p_wf_on.get().strip() or None,
            wf_off=self.p_wf_off.get().strip() or None,
            x_min=f(self.p_xmin, "x-min"), x_max=f(self.p_xmax, "x-max"),
            y_min=f(self.p_ymin, "y-min"), y_max=f(self.p_ymax, "y-max"),
            z_min=f(self.p_zmin, "z-min"), z_max=f(self.p_zmax, "z-max"),
            max_feed=f(self.p_maxfeed, "max-feed-rate"),
            step_mesh=f(self.p_stepmesh, "step-mesh-size"),
            scale=f(self.p_scale, "scale"),
            infill_style=self._read_infill_style(),
            voltage=f(self.p_voltage, "voltage"),
            current=f(self.p_current, "current"),
            wire_efficiency=f(self.p_wire_eff, "wire-efficiency"),
            wire_diameter=f(self.p_wire_dia, "wire-diameter"),
            material=self.p_material.get().strip() or "steel",
            rot=(self._finite(float(self.o_rx.get()), "rotate-x"),
                 self._finite(float(self.o_ry.get()), "rotate-y"),
                 self._finite(float(self.o_rz.get()), "rotate-z")),
            shift=(self._finite(float(self.o_dx.get() or 0), "shift-x"),
                   self._finite(float(self.o_dy.get() or 0), "shift-y"),
                   self._finite(float(self.o_dz.get() or 0), "shift-z")),
        )

    def _read_infill_style(self):
        style = self.p_infill_style.get().strip()
        if style not in INFILL_STYLES:
            raise GCodeGenerationError(f"Infill style must be one of {list(INFILL_STYLES)}, got `{style}`.")
        return style

    @staticmethod
    def _finite(val, name):
        import math
        try:
            v = float(val)
        except (TypeError, ValueError):
            raise GCodeGenerationError(f"Parameter `{name}` is not a number: `{val}`.")
        if not math.isfinite(v):
            raise GCodeGenerationError(f"Parameter `{name}` must be finite, got `{val}`.")
        return v

    def start_job(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "A slicing job is already running.")
            return
        stl = self.stl_var.get().strip()
        out = self.out_var.get().strip()
        if not stl:
            messagebox.showerror("No input", "Attach an STL file first (top-left button).")
            return
        if not os.path.isfile(stl):
            messagebox.showerror("File not found",
                                 f"`{stl}` does not exist.\nPick it with Attach STL (absolute path).")
            return
        try:
            params = self._read_params()
        except GCodeGenerationError as e:
            messagebox.showerror("Bad parameter", str(e))
            return
        self._clear_results()  # wipe stale previews/stats so a failed run can't masquerade as old data
        self.run_btn.configure(state=tk.DISABLED)
        self.prog.start(12)
        self.status_var.set("slicing...")
        self.log(f"\n=== Job started {time.strftime('%H:%M:%S')} ===")
        self.log(f"Input:  {stl}")
        self.log(f"Output: {out}")
        args = (stl, out, params,
                bool(self.v_allow_damaged.get()), bool(self.v_skip_bounds.get()),
                bool(self.v_auto_place.get()))
        self.worker = threading.Thread(target=self._job_thread, args=args, daemon=True)
        self.worker.start()

    def _job_thread(self, stl, out, p, allow_damaged, skip_bounds, auto_place=True):
        Q = self.log_q
        try:
            Q.put(("log", "[1/4] Loading mesh..."))
            mesh, report = load_mesh(stl, strict=not allow_damaged,
                                     step_mesh_size=p.get("step_mesh", 5.0),
                                     scale=p.get("scale", 1.0))
            Q.put(("log", f"  Watertight={report.watertight} bodies={report.body_count} "
                          f"non-manifold={report.non_manifold_edges} bounds={report.bounds}"))
            for w in report.warnings:
                Q.put(("log", f"  [warn] {w}"))

            limits = MachineLimits(
                x_min=p["x_min"], x_max=p["x_max"], y_min=p["y_min"],
                y_max=p["y_max"], z_min=p["z_min"], z_max=p["z_max"],
                max_feed_rate=p["max_feed"],
            )
            rx, ry, rz = p.get("rot", (0.0, 0.0, 0.0))
            dx, dy, dz = p.get("shift", (0.0, 0.0, 0.0))
            _msgs: list = []
            self._place_mesh(mesh, rx, ry, rz, dx, dy, dz, limits, auto_place,
                             log=_msgs.append)
            for m in _msgs:
                Q.put(("log", m))

            Q.put(("log", f"[2/4] Slicing at {p['layer_height']}mm..."))
            layers = slice_mesh(mesh, layer_height=p["layer_height"])
            Q.put(("log", f"  -> {len(layers)} layers"))

            Q.put(("log", f"[3/4] Planning toolpaths (bead={p['bead_width']}mm, {p['perimeters']} perim, infill={p.get('infill_style', 'zigzag')})..."))
            toolpaths = plan_all_layers(layers, bead_width=p["bead_width"],
                                        num_perimeters=p["perimeters"],
                                        infill_angle_step=p["infill_angle_step"],
                                        infill_style=p.get("infill_style", "zigzag"))
            n_beads = sum(len(tp.beads) for tp in toolpaths)
            Q.put(("log", f"  -> {n_beads} beads across {len(toolpaths)} layers"))
            warns = summarize_warnings(toolpaths)
            for w in warns[:15]:
                Q.put(("log", f"  [warn] {w}"))
            if len(warns) > 15:
                Q.put(("log", f"  ... and {len(warns) - 15} more"))

            Q.put(("log", "[4/4] Generating G-code (bounds-checked)..."))
            params = WAAMParams(
                travel_speed=p["travel_speed"], weld_speed=p["weld_speed"],
                wire_feed_speed=p["wire_feed_speed"],
                interlayer_dwell=p["interlayer_dwell"], lead_in_out=p["lead_in_out"],
                arc_on_mcode=p["arc_on"], arc_off_mcode=p["arc_off"],
                wire_feed_on_mcode=p["wf_on"], wire_feed_off_mcode=p["wf_off"],
            )
            stats = compute_job_stats(toolpaths, params,
                                      bead_width=p["bead_width"],
                                      layer_height=p["layer_height"],
                                      voltage=p.get("voltage", 28.0),
                                      current=p.get("current", 180.0),
                                      wire_efficiency=p.get("wire_efficiency", 0.8),
                                      wire_diameter=p.get("wire_diameter", 1.2),
                                      wire_feed_speed=p.get("wire_feed_speed"),
                                      material=p.get("material", "steel"))
            gcode = generate_gcode(toolpaths, params, bead_width=p["bead_width"],
                                   layer_height=p["layer_height"],
                                   header_comment=f"WAAM slice of {os.path.basename(stl)}",
                                   machine_limits=limits, skip_bounds_check=skip_bounds,
                                   job_stats=stats,
                                   voltage=p.get("voltage", 28.0),
                                   current=p.get("current", 180.0))
            write_gcode_file(gcode, out)
            Q.put(("done", dict(out=out, n_layers=len(layers), n_beads=n_beads,
                                n_warn=len(warns), n_lines=gcode.count("\n"),
                                report=report, mesh=mesh, toolpaths=toolpaths, layers=layers,
                                stats=stats)))
        except Exception as e:  # noqa - surface everything to the GUI
            Q.put(("fail", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"))

    def _on_job_done(self, d):
        self.prog.stop()
        self.run_btn.configure(state=tk.NORMAL)
        self.status_var.set("done")
        self.mesh, self.mesh_report = d["mesh"], d["report"]
        self.toolpaths, self.layers = d["toolpaths"], d["layers"]
        self.last_gcode_path = d["out"]
        self.log(f"Done -> {d['out']} ({d['n_lines']} lines, {d['n_layers']} layers, {d['n_beads']} beads).")
        if d["n_warn"]:
            self.log(f"Remember: {d['n_warn']} warning(s) - review before hardware. See README dry-run steps.")
        else:
            self.log("No toolpath warnings.")
        self.stats_var.set(f"{d['n_layers']} layers | {d['n_beads']} beads | {d['n_lines']} lines")
        # Show full job stats in log
        st = d.get("stats")
        if st:
            self.log("")
            self.log("=" * 50)
            self.log("  JOB STATISTICS")
            self.log("=" * 50)
            self.log(f"  Weld path:       {st.weld_distance_mm:.0f} mm ({st.weld_distance_mm/1000:.2f} m)")
            self.log(f"  Weld time:       {_fmt_t(st.weld_time_s)}")
            self.log(f"  Travel time:     {_fmt_t(st.travel_time_s)}")
            self.log(f"  Arc dwell:       {_fmt_t(st.arc_dwell_s)}")
            if st.interlayer_dwell_s > 0:
                self.log(f"  Interlayer:      {_fmt_t(st.interlayer_dwell_s)}")
            self.log(f"  TOTAL BUILD:     {_fmt_t(st.total_build_time_s)}")
            self.log(f"  Wire from spool: {st.wire_length_m:.1f} m ({st.wire_mass_g:.0f} g)")
            self.log(f"  Deposited vol:   {st.deposited_volume_mm3:.0f} mm³ ({st.deposited_volume_mm3/1000:.1f} cm³)")
            self.log(f"  Mass dep. rate:  {st.mass_deposition_rate_kg_hr:.3f} kg/hr")
            self.log(f"  Arc power:       {st.arc_power_w:.0f} W  (V·I)")
            self.log(f"  Net heat power:  {st.net_heat_power_w:.0f} W  (η·V·I)")
            self.log(f"  Linear HI:       {st.heat_input_j_per_mm:.1f} J/mm")
            self.log(f"  Bead width (calc): {st.bead_width_calc:.2f} mm")
            self.log("=" * 50)
        # set sliders
        n = max(len(self.toolpaths) - 1, 0)
        self.layer_slider.configure(to=n)
        self.twin_slider.configure(to=n)
        self.twin_n.set(n)
        self.layer_idx.set(min(self.layer_idx.get(), n))
        self.draw_layer()
        self.draw_twin()
        self.nb.select(self.tab_2d)

        # Export solver-compatible toolpath.txt and layer_pass_times.txt
        try:
            out_gcode = d["out"]
            p_dir = os.path.dirname(os.path.abspath(out_gcode)) or os.getcwd()
            weld_f = float(self.p_weld.get() or 150.0)
            travel_f = float(self.p_travel.get() or 400.0)
            dwell_s = float(self.p_dwell.get() or 0.0)
            lead_io = float(self.p_lead.get() or 0.0)

            sub_lx = getattr(self, "p_lx_val", 150.0)
            sub_ly = getattr(self, "p_ly_val", 150.0)
            sub_hz = getattr(self, "p_hz_val", 5.0)
            target_cx = sub_lx / 2.0
            target_cy = sub_ly / 2.0

            all_x, all_y, all_z = [], [], []
            for l_tp in d["toolpaths"]:
                for bead in l_tp.beads:
                    for px, py in bead.points:
                        all_x.append(px)
                        all_y.append(py)
                        all_z.append(l_tp.z)

            shift_x = 0.0
            shift_y = 0.0
            shift_z = 0.0
            if all_x and all_y and all_z:
                cx_tp = (min(all_x) + max(all_x)) / 2.0
                cy_tp = (min(all_y) + max(all_y)) / 2.0
                min_z = min(all_z)
                # Auto-align XY if sliced in machine envelope rather than substrate center
                if abs(cx_tp - target_cx) > 1.0 or abs(cy_tp - target_cy) > 1.0:
                    shift_x = target_cx - cx_tp
                    shift_y = target_cy - cy_tp
                # Auto-align Z if sliced resting on Z=0 without substrate plate offset
                if min_z < sub_hz * 0.7:
                    shift_z = sub_hz

            txt_lines = []
            t_curr = 0.0
            layer_pass_times = []
            last_pt = (0.0, 0.0)
            last_z = 0.0

            # Initial point
            z_init = (d["toolpaths"][0].z + shift_z) if d["toolpaths"] else sub_hz
            txt_lines.append(f"{t_curr:.3f} 0.00000 0.00000 {z_init/1000.0:.5f} 0")

            for l_tp in d["toolpaths"]:
                l_start_time = t_curr
                lz = l_tp.z + shift_z
                for bead in l_tp.beads:
                    pts = _apply_lead_in_out(bead.points, lead_io)
                    if not pts:
                        continue
                    # Rapid move to start of bead
                    sx = pts[0][0] + shift_x
                    sy = pts[0][1] + shift_y
                    dist_rap = math.hypot(sx - last_pt[0], sy - last_pt[1], lz - last_z)
                    dt_rap = (dist_rap / (travel_f / 60.0)) if travel_f > 0 else 0.0
                    t_curr += dt_rap
                    txt_lines.append(f"{t_curr:.3f} {sx/1000.0:.5f} {sy/1000.0:.5f} {lz/1000.0:.5f} 0")
                    last_pt = (sx, sy)
                    last_z = lz

                    # Weld along points
                    for px, py in pts[1:]:
                        px_s = px + shift_x
                        py_s = py + shift_y
                        dist_w = math.hypot(px_s - last_pt[0], py_s - last_pt[1])
                        dt_w = (dist_w / (weld_f / 60.0)) if weld_f > 0 else 0.0
                        t_curr += dt_w
                        txt_lines.append(f"{t_curr:.3f} {px_s/1000.0:.5f} {py_s/1000.0:.5f} {lz/1000.0:.5f} 1")
                        last_pt = (px_s, py_s)

                if dwell_s > 0:
                    t_curr += dwell_s
                    txt_lines.append(f"{t_curr:.3f} {last_pt[0]/1000.0:.5f} {last_pt[1]/1000.0:.5f} {last_z/1000.0:.5f} 0")

                layer_pass_times.append(max(t_curr - l_start_time, 0.01))

            if abs(shift_x) > 1e-4 or abs(shift_y) > 1e-4 or abs(shift_z) > 1e-4:
                self.log(f"[SOLVER SYNC] Auto-aligned toolpath to substrate: shift=({shift_x:+.1f}, {shift_y:+.1f}, {shift_z:+.1f}) mm -> Substrate center=({target_cx:.1f}, {target_cy:.1f}) mm, hz_base={sub_hz:.1f} mm")

            txt_path = str(Path(out_gcode).with_suffix(".txt"))
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"{len(txt_lines)}\n")
                f.write("\n".join(txt_lines) + "\n")

            lt_path = str(Path(out_gcode).with_suffix(".layer_times.txt"))
            with open(lt_path, "w", encoding="utf-8") as f:
                f.write(f"{len(layer_pass_times)}\n")
                for li, lt in enumerate(layer_pass_times):
                    f.write(f"{li+1} {lt:.6f}\n")

            # Canonical solver artifact sync
            target_dirs = [p_dir]
            framework_out = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "WAAM-Framework", "waam_output"))
            if os.path.isdir(framework_out):
                target_dirs.append(framework_out)
            cwd_out = os.path.abspath("./waam_output")
            if os.path.isdir(cwd_out) and cwd_out not in target_dirs:
                target_dirs.append(cwd_out)

            import shutil
            for td in target_dirs:
                for src_f, dst_name in (
                    (out_gcode, "toolpath.gcode"),
                    (txt_path, "toolpath.txt"),
                    (lt_path, "layer_pass_times.txt")
                ):
                    try:
                        dst_f = os.path.join(td, dst_name)
                        if os.path.exists(src_f) and Path(src_f).resolve() != Path(dst_f).resolve():
                            shutil.copy2(src_f, dst_f)
                    except Exception:
                        pass

            self.log(f"[SOLVER ARTIFACTS] Exported toolpath.txt ({len(txt_lines):,} pts) & layer_pass_times.txt ({len(layer_pass_times)} layers) for FreeFEM.")
            if self.app:
                self.app.loaded_gcode_path = out_gcode
                if hasattr(self.app, "mesh_source_var"):
                    self.app.mesh_source_var.set("gcode_file")
                if hasattr(self.app, "_param_vars") and "n_layers" in self.app._param_vars:
                    self.app._param_vars["n_layers"][0].set(str(len(layer_pass_times)))
                if hasattr(self.app, "slicer_h_var") and hasattr(self, "p_layer_h"):
                    try:
                        self.app.slicer_h_var.set(str(self.p_layer_h.get()))
                    except Exception:
                        pass
                if hasattr(self.app, "slicer_w_var") and hasattr(self, "p_bead_w"):
                    try:
                        self.app.slicer_w_var.set(str(self.p_bead_w.get()))
                    except Exception:
                        pass
                if hasattr(self.app, "_log"):
                    self.app._log(f"[SLICER] Synchronized G-code toolpath ({len(txt_lines):,} points, {len(layer_pass_times)} layers) -> Main Simulation heat source.\n")
                if hasattr(self.app, "_auto_fix_mesh_rules"):
                    self.app._auto_fix_mesh_rules()
        except Exception as ex:
            self.log(f"[SOLVER ARTIFACTS NOTE] {ex}")

        messagebox.showinfo("Done", f"G-code written:\n{d['out']}\n{d['n_layers']} layers, {d['n_beads']} beads.")

    def _on_job_fail(self, msg):
        self.prog.stop()
        self.run_btn.configure(state=tk.NORMAL)
        self.status_var.set("FAILED - see log")
        self.log(f"[FAILED]\n{msg}")
        self.nb.select(self.tab_log)
        first = msg.splitlines()[0] if msg else "Unknown error"
        messagebox.showerror("Slicing failed", first)

    # ---------------- previews ----------------
    def draw_layer(self):
        self.ax2d.clear()
        self.ax2d.set_aspect("equal", adjustable="datalim")
        self.ax2d.set_xlabel("X (mm)"); self.ax2d.set_ylabel("Y (mm)")
        if not self.toolpaths:
            self.ax2d.set_title("Run a slice to preview layers")
            self._apply_mpl_theme(self.fig2d, self.ax2d)
            self.canvas2d.draw()
            return
        i = int(round(float(self.layer_idx.get())))
        i = max(0, min(i, len(self.toolpaths) - 1))
        tp = self.toolpaths[i]
        self.layer_lbl.configure(text=f"{i} / {len(self.toolpaths) - 1}")
        for b in tp.beads:
            pts = np.asarray(b.points)
            if len(pts) < 2:
                continue
            self.ax2d.plot(pts[:, 0], pts[:, 1], color=BEAD_COLORS.get(b.kind, "k"), lw=1.2)
        # faint layer outline from sliced polygons
        if i < len(self.layers):
            for poly in self.layers[i].polygons:
                try:
                    x, y = poly.exterior.xy
                    self.ax2d.plot(x, y, color="gray", lw=0.6, alpha=0.5)
                except Exception:
                    pass
        # legend (proxy)
        for kind, c in BEAD_COLORS.items():
            self.ax2d.plot([], [], color=c, label=kind)
        self.ax2d.legend(fontsize=8, loc="best")
        self.ax2d.set_title(f"Layer {tp.index}  Z={tp.z:.2f}mm  ({len(tp.beads)} beads)")
        self.fig2d.tight_layout()
        self._apply_mpl_theme(self.fig2d, self.ax2d)
        self.canvas2d.draw()

    def draw_twin(self):
        self.ax3d.clear()
        self.ax3d.set_xlabel("X (mm)"); self.ax3d.set_ylabel("Y (mm)"); self.ax3d.set_zlabel("Z (mm)")
        if not self.toolpaths:
            self.ax3d.set_title("Kinematic twin - run a slice first")
            self._apply_mpl_theme(self.fig3d, self.ax3d)
            self.canvas3d.draw()
            return
        limits = self._current_limits_or_default()
        n = int(round(float(self.twin_n.get())))
        n = max(0, min(n, len(self.toolpaths) - 1))
        self.twin_lbl.configure(text=f"{n} / {len(self.toolpaths) - 1}")
        segs, cols = [], []
        for tp in self.toolpaths[:n + 1]:
            c = plt_color_for_z(tp.index, len(self.toolpaths))
            for b in tp.beads:
                pts = np.asarray(b.points)
                if len(pts) < 2:
                    continue
                z = np.full(len(pts), tp.z)
                xyz = np.column_stack([pts, z])
                segs.append(xyz[:-1])
                # per-segment colours not needed; one colour per layer band
                cols.append(c)
                # draw as line (cheap): plot each bead directly
                self.ax3d.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color=c, lw=0.9)
        self.ax3d.set_title(f"Build replay: layers 0..{n}  (kinematic, no thermal)")
        if segs:
            all_pts = np.vstack(segs)
            pmin = np.min(all_pts, axis=0)
            pmax = np.max(all_pts, axis=0)
            pcenter = (pmin + pmax) / 2.0
            pspan = np.maximum(pmax - pmin, 8.0)
            max_pspan = float(np.max(pspan))
            phalf = max_pspan * 0.75
            self.ax3d.set_xlim(pcenter[0] - phalf, pcenter[0] + phalf)
            self.ax3d.set_ylim(pcenter[1] - phalf, pcenter[1] + phalf)
            self.ax3d.set_zlim(max(0.0, pcenter[2] - phalf), pcenter[2] + phalf)
            try:
                self.ax3d.set_box_aspect((1, 1, 1))
            except Exception:
                pass
        else:
            try:
                self.ax3d.set_box_aspect((
                    limits.x_max - limits.x_min,
                    limits.y_max - limits.y_min,
                    limits.z_max - limits.z_min))
            except Exception:
                pass
        self._apply_mpl_theme(self.fig3d, self.ax3d)
        self.canvas3d.draw()

    def show_all_twin(self):
        if self.toolpaths:
            self.twin_n.set(len(self.toolpaths) - 1)
            self.draw_twin()


def _fmt_t(seconds):
    """Format seconds as human-readable string for the GUI log."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h = m // 60
    m = m % 60
    return f"{h}h {m:02d}m {s:02d}s"


def plt_color_for_z(i, total):
    # simple blue->orange ramp by layer index
    t = i / max(total - 1, 1)
    r = 0.12 + 0.88 * t
    b = 0.70 - 0.55 * t
    return (r, 0.45, max(b, 0.08))


class SlicerGUI(tk.Tk):
    """Standalone desktop window wrapping WAAMSlicerFrame."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("WAAM Slicer - Vashishtha Research cell (DDCS V2.1 + Champ Pulse 500)")
        self.geometry("1080x660")
        self.minsize(900, 520)

        self.widget = WAAMSlicerFrame(self)
        self.widget.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self.widget.on_close(destroy_top=True)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.widget, name)


WAAMSlicerWidget = WAAMSlicerFrame
SlicerFrame = WAAMSlicerFrame


def main():
    import signal
    app = SlicerGUI()
    try:
        # Route Ctrl+C through the Tk event loop instead of raising
        # KeyboardInterrupt wherever the interpreter happens to be (often
        # inside matplotlib's C draw code, where it aborts the process).
        signal.signal(signal.SIGINT, lambda *_: app.after(0, app._on_close))
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
