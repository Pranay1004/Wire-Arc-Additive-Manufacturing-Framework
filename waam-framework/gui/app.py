#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulation Framework — GUI Application

A Tkinter-based desktop interface for configuring and running
FreeFEM++ WAAM simulations with multi-physics coupling.
Features:
  - Default Light Theme with instantaneous Light/Dark Theme toggle
  - Vertical layout: Configuration Notebook on Left, Tall Live Solver Stream on Right
  - Direct structured mesh sizing inputs (dx, dy, dz in mm) + Live Element Size Readout
  - 6 selectable heat source models with dynamic parameter panels
  - Material database with T-dependent property auto-fill
  - Slicing & CAD toolpath integration
  - Real-time FreeFEM++ console output stream
  - OpenFOAM 2412 and ParaView one-click integration
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import threading
import json
import os
import sys
import re
import datetime
import shutil
import glob
import math
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Pin the matplotlib backend to TkAgg BEFORE any pyplot import. Without this,
# matplotlib auto-selects QtAgg (PyQt5 is installed) and the embedded
# FigureCanvasTkAgg widgets end up pulling in a second GUI toolkit.
import matplotlib
matplotlib.use("TkAgg")

from codegen.edp_builder import EDPBuilder
from core.platform_adapter import (
    find_freefem_serial, find_freefem_mpi, find_paraview, find_gmsh,
    configure_parallel_environment, to_solver_path, open_path_in_file_manager,
    open_url_in_browser, build_unbuffered_command, HOST_ARCH, resolve_output_dir
)


def safe_copy_file(src: str, dst: str, retries: int = 5, delay: float = 0.05) -> bool:
    """
    Safely copy src to dst across platforms (especially Windows).
    Guards against:
      1. Same-file copy attempts (which trigger [WinError 32] / SameFileError on Windows)
      2. Transient file locks held by directory indexers or sync tools (Syncthing, Defender)
      3. Missing target directory creation
    """
    if not src or not os.path.exists(src) or not os.path.isfile(src):
        return False
    try:
        p_src = Path(src).resolve()
        p_dst = Path(dst).resolve()
        if str(p_src).lower() == str(p_dst).lower():
            return True
        if p_dst.exists() and os.path.samefile(str(p_src), str(p_dst)):
            return True
    except Exception:
        pass

    target_dir = os.path.dirname(dst)
    if target_dir:
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass

    for attempt in range(retries):
        try:
            shutil.copy2(src, dst)
            return True
        except (PermissionError, OSError):
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                return False
        except Exception:
            return False
    return False


class Tooltip:
    """Minimal hover tooltip (no dependency). Usage: Tooltip(widget, text)."""

    def __init__(self, widget, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip = None
        self._job = None
        try:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")
        except Exception:
            pass

    def _schedule(self, _event=None):
        try:
            self._hide()
            self._job = self.widget.after(self.delay, self._show)
        except Exception:
            pass

    def _show(self):
        if self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self._tip = tk.Toplevel(self.widget)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry(f"+{x}+{y}")
            lbl = tk.Label(
                self._tip, text=self.text, justify=tk.LEFT,
                bg="#111827", fg="#f9fafc", font=("TkDefaultFont", 9),
                padx=8, pady=5, wraplength=320,
            )
            lbl.pack()
        except Exception:
            pass

    def _hide(self, _event=None):
        try:
            if self._job is not None:
                self.widget.after_cancel(self._job)
        except Exception:
            pass
        self._job = None
        try:
            if self._tip is not None:
                self._tip.destroy()
        except Exception:
            pass
        self._tip = None


# ============================================================
# THEME PALETTES & DIMENSION KEYS (gui/presets.py)
# ============================================================
from gui.presets import THEMES, MM_DIMENSION_KEYS, MM_SPEED_KEYS, PARAMETER_PRESETS



# Font definitions — OS-aware native stacks (see gui/fonts.py).
# Detects macOS / Windows / Linux and picks Helvetica Neue-Menlo,
# Segoe UI-Consolas, or DejaVu Sans(-Mono) with per-OS size nudges.
# Imported names stay backward compatible; apply_os_typography() rebinds
# them to installed families at window creation.
try:
    from gui.fonts import (
        FONT_TITLE, FONT_SUBTITLE, FONT_SECTION, FONT_LABEL, FONT_ENTRY,
        FONT_CONSOLE, FONT_STATUS, FONT_BTN_RUN, FONT_BTN, FONT_TAB,
        FONT_MONO_SM, FONT_SMALL, FONT_SMALL_BOLD, FONT_UNIT,
        FONT_MONO, FONT_INFO, FONT_TINY, FONT_COMBO,
        FONT_DLG_TITLE, FONT_MONO_LG,
        OS_TYPE, UI_FONT_FAMILY, MONO_FONT_FAMILY,
        apply_os_typography,
    )
except ImportError:  # fallback when run as script without package context
    try:
        from fonts import (
            FONT_TITLE, FONT_SUBTITLE, FONT_SECTION, FONT_LABEL, FONT_ENTRY,
            FONT_CONSOLE, FONT_STATUS, FONT_BTN_RUN, FONT_BTN, FONT_TAB,
            FONT_MONO_SM, FONT_SMALL, FONT_SMALL_BOLD, FONT_UNIT,
            FONT_MONO, FONT_INFO, FONT_TINY, FONT_COMBO,
            FONT_DLG_TITLE, FONT_MONO_LG,
            OS_TYPE, UI_FONT_FAMILY, MONO_FONT_FAMILY,
            apply_os_typography,
        )
    except ImportError:
        OS_TYPE = "other"
        UI_FONT_FAMILY = "Helvetica Neue"
        MONO_FONT_FAMILY = "Menlo"
        FONT_TITLE   = ("Helvetica Neue", 16, "bold")
        FONT_SUBTITLE= ("Helvetica Neue", 10)
        FONT_SECTION = ("Helvetica Neue", 10, "bold")
        FONT_LABEL   = ("Helvetica Neue", 10)
        FONT_ENTRY   = ("Menlo", 10)
        FONT_CONSOLE = ("Menlo", 10)
        FONT_STATUS  = ("Helvetica Neue", 11, "bold")
        FONT_BTN_RUN = ("Helvetica Neue", 12, "bold")
        FONT_BTN     = ("Helvetica Neue", 10)
        FONT_TAB     = ("Helvetica Neue", 10, "bold")
        FONT_MONO_SM = ("Menlo", 9)
        FONT_SMALL = ("Helvetica Neue", 9)
        FONT_SMALL_BOLD = ("Helvetica Neue", 9, "bold")
        FONT_UNIT = ("Helvetica Neue", 9)
        FONT_MONO = ("Menlo", 9)
        FONT_INFO = ("Menlo", 9)
        FONT_TINY = ("Menlo", 8)
        FONT_COMBO = ("Helvetica Neue", 9)
        FONT_DLG_TITLE = ("Helvetica Neue", 13, "bold")
        FONT_MONO_LG = ("Menlo", 11)
        def apply_os_typography(root, style=None, verbose=False):
            return {}




class WAAMApp:
    """Main application window with dynamic theme switching and vertical solver layout."""

    def __init__(self, initial_preset=None):
        self.root = tk.Tk()
        self.root.title("WAAM Multi-Physics Simulator — FreeFEM++ and OpenFOAM 2412")
        # OS-aware typography: resolve native UI/mono families before any
        # widget is built so all font= references use the right stack.
        try:
            self.font_info = apply_os_typography(self.root)
        except Exception:
            self.font_info = {}
        # Adaptive geometry: scale comfortably to 13"-16" laptop panels (1366x768, 1440x900, 1512x982)
        # without overflowing screen borders or hiding action bars.
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            target_w = min(1280, max(sw - 60, 960))
            target_h = min(730, max(sh - 100, 560))
            self.root.geometry(f"{target_w}x{target_h}")
        except Exception:
            self.root.geometry("1220x680")
        self.root.minsize(960, 540)

        # Theme state: defaults to 'light' per user preference
        self.current_theme = "light"
        self.colors = THEMES[self.current_theme]

        # Simulation state
        self.params = EDPBuilder.default_params()
        self.process = None
        self.running = False
        self.active_run_dir = None
        self.active_run_executed = False
        self._param_vars = {}
        self.param_entries = {}
        self.registered_widgets = []
        self._applying_preset = False

        # Load material database
        self.materials = {}
        db_path = Path(__file__).parent.parent / "core" / "multimaterial" / "material_database.json"
        if db_path.exists():
            try:
                with open(db_path) as f:
                    self.materials = json.load(f).get("alloys", {})
            except Exception:
                pass

        self._build_ui()
        preset_to_load = initial_preset if (initial_preset and initial_preset in PARAMETER_PRESETS) else "DEFAULT"
        if preset_to_load in PARAMETER_PRESETS:
            self.preset_var.set(preset_to_load)
            self._apply_preset()
        self._apply_theme()
        self._update_mesh_calc()
        self._update_heat_calc()
        def _on_tab_changed(event=None):
            try:
                selected_tab = self.notebook.select()
                if hasattr(self, "viewport_tab") and selected_tab == str(self.viewport_tab):
                    self._ensure_viewport_loaded()
                    self._refresh_embedded_viewport()
                elif hasattr(self, "default_case_tab") and selected_tab == str(self.default_case_tab):
                    self._refresh_generated_edp_preview()
            except Exception:
                pass
        self.notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)
        # Keyboard shortcuts: Cmd/Ctrl+Enter runs, Esc stops, Ctrl/Cmd+F finds in log.
        try:
            self.root.bind_all("<Control-Return>", lambda e: self._run_simulation())
            self.root.bind_all("<Command-Return>", lambda e: self._run_simulation())
            self.root.bind_all("<Escape>", lambda e: self._stop_simulation())
        except Exception:
            pass

    def _build_ui(self):
        """Build UI structure with horizontal split (Tabs on Left, Live Solver on Right)."""
        # Fix macOS Copy/Paste bindings
        if self.root.tk.call('tk', 'windowingsystem') == 'aqua':
            self.root.bind_all('<Command-c>', lambda e: e.widget.event_generate('<<Copy>>'))
            self.root.bind_all('<Command-v>', lambda e: e.widget.event_generate('<<Paste>>'))
            self.root.bind_all('<Command-x>', lambda e: e.widget.event_generate('<<Cut>>'))
            self.root.bind_all('<Command-a>', lambda e: e.widget.event_generate('<<SelectAll>>'))

        self.style = ttk.Style()
        self.style.theme_use("clam")
        # Re-apply with style so ttk "." / TNotebook.Tab / TButton inherit OS fonts.
        try:
            self.font_info = apply_os_typography(self.root, self.style)
        except Exception:
            pass
        self.style.configure("TNotebook.Tab", padding=[8, 3], font=FONT_TAB)

        # Top Header Bar
        self.header = tk.Frame(self.root)
        self.header.pack(fill=tk.X, padx=14, pady=(8, 4))

        self.title_frame = tk.Frame(self.header)
        self.title_frame.pack(side=tk.LEFT)
        self.title_label = tk.Label(
            self.title_frame, text="WAAM Multi-Physics Simulator",
            font=FONT_TITLE
        )
        self.title_label.pack(side=tk.TOP, anchor=tk.W)
        # Subtitle removed per user request

        # Header Right: Preset selector + Status + Theme Toggle
        self.header_right = tk.Frame(self.header)
        self.header_right.pack(side=tk.RIGHT)

        self.theme_btn = tk.Button(
            self.header_right, text="[ Dark Theme ]",
            font=FONT_BTN, relief=tk.GROOVE,
            command=self._toggle_theme, padx=10, pady=3
        )
        self.theme_btn.pack(side=tk.RIGHT, padx=6)

        self.status_var = tk.StringVar(value="Status: Ready")
        self.status_label = tk.Label(
            self.header_right, textvariable=self.status_var,
            font=FONT_STATUS
        )
        self.status_label.pack(side=tk.RIGHT, padx=10)

        # Preset Selector
        preset_frame = tk.Frame(self.header_right)
        preset_frame.pack(side=tk.RIGHT, padx=12)
        self._reg(preset_frame, "card_frame")
        tk.Label(preset_frame, text="Preset:", font=FONT_BTN).pack(side=tk.LEFT, padx=(0, 4))
        self._reg(preset_frame.winfo_children()[0], "label")
        self.preset_var = tk.StringVar(value="DEFAULT")
        preset_names = list(PARAMETER_PRESETS.keys())
        self.preset_combo = ttk.Combobox(
            preset_frame, textvariable=self.preset_var,
            values=preset_names, width=30, state="readonly", font=FONT_BTN
        )
        self.preset_combo.pack(side=tk.LEFT)
        self.preset_combo.bind("<<ComboboxSelected>>", self._apply_preset)

        # Main Paned Area: LEFT (Tabs) + RIGHT (Vertical Live Solver & Actions)
        self.main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=4)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        # Left Notebook (Parameters & 3D Viewport)
        self.notebook = ttk.Notebook(self.main_pane)
        self.main_pane.add(self.notebook, width=980, minsize=900)

        self._build_geometry_tab()
        self._build_process_tab()
        self._build_material_tab()
        self._build_mesh_cad_tab()
        self._build_physics_tab()
        self._build_solver_tab()
        self._build_openfoam_tab()
        self._build_parametric_tab()
        self._build_viewport_tab()
        self._build_default_case_tab()
        self._build_claude_tab()
        self._build_sim_log_tab()

        # File menu bar
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Project (.waam)...", command=self._save_project)
        file_menu.add_command(label="Load Project (.waam)...", command=self._load_project)
        file_menu.add_separator()
        file_menu.add_command(label="Open Output Folder", command=self._open_output)
        file_menu.add_command(label="Open Report", command=self._open_report)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._confirm_quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # Multi-Material & Ultrasonic menu
        claude_menu = tk.Menu(menubar, tearoff=0)
        claude_menu.add_command(label="Open Ultrasonic & Multi-Material Tab", command=lambda: self.notebook.select(self.claude_tab))
        claude_menu.add_separator()
        claude_menu.add_command(label="Open Results in ParaView", command=self._open_paraview)
        claude_menu.add_command(label="Open Output Directory", command=self._open_output)
        menubar.add_cascade(label="Ultrasonic", menu=claude_menu)

        self.root.config(menu=menubar)

        # Right Panel: Action Toolbar + Tall Vertical Live Solver Console
        self.right_panel = tk.Frame(self.main_pane)
        self.main_pane.add(self.right_panel, width=540, minsize=420)
        self._reg(self.right_panel, "card_frame")

        # Top Action Button Bar inside Right Panel
        self.btn_bar = tk.Frame(self.right_panel, pady=4)
        self.btn_bar.pack(fill=tk.X, padx=6, pady=(2, 4))
        self._reg(self.btn_bar, "card_frame")

        # Main Run & Stop Buttons
        run_stop_frame = tk.Frame(self.btn_bar)
        run_stop_frame.pack(fill=tk.X, pady=(0, 4))
        self._reg(run_stop_frame, "card_frame")

        self.run_btn = tk.Button(
            run_stop_frame, text="▶ Run Simulation",
            font=FONT_BTN_RUN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._run_simulation, padx=16, pady=6
        )
        self.run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.stop_btn = tk.Button(
            run_stop_frame, text="⏹ Stop",
            font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._stop_simulation, padx=12, pady=6,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.RIGHT, padx=(4, 0))

        # Primary Results & Post-Processing Bar
        res_bar = tk.Frame(self.btn_bar)
        res_bar.pack(fill=tk.X, pady=(2, 2))
        self._reg(res_bar, "card_frame")

        self.view_results_btn = tk.Button(
            res_bar, text="📄 View Report",
            font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            bg=self.colors["button_primary"], fg=self.colors["button_primary_fg"],
            activebackground=self.colors["button_primary_active"],
            activeforeground=self.colors["button_primary_fg"],
            command=self._open_report, padx=10, pady=4
        )
        self.view_results_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.report_btn = self.view_results_btn

        self.pv_btn = tk.Button(
            res_bar, text="📊 ParaView", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._open_paraview, padx=8, pady=4
        )
        self.pv_btn.pack(side=tk.LEFT, padx=2)

        self.out_btn = tk.Button(
            res_bar, text="📁 Run Folder", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._open_output, padx=8, pady=4
        )
        self.out_btn.pack(side=tk.LEFT, padx=(2, 0))

        # Secondary Modeling & Case Generation Bar (2 balanced buttons, no truncation!)
        sec_bar = tk.Frame(self.btn_bar)
        sec_bar.pack(fill=tk.X, pady=(2, 2))
        self._reg(sec_bar, "card_frame")

        self.gen_btn = tk.Button(
            sec_bar, text="⚡ Generate Simulation Script", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._generate_script, padx=6, pady=4
        )
        self.gen_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self.foam_btn = tk.Button(
            sec_bar, text="🌊 Generate CFD Case", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._openfoam_dialog, padx=6, pady=4
        )
        self.foam_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))

        # Viewport & Multi-Material Toolbar Row (3 buttons, cleanly distributed!)
        vis_bar = tk.Frame(self.btn_bar)
        vis_bar.pack(fill=tk.X, pady=(2, 2))
        self._reg(vis_bar, "card_frame")

        self.mesh3d_btn = tk.Button(
            vis_bar, text="🌐 Slicer", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            bg=self.colors["button_info"], fg=self.colors["button_info_fg"],
            command=self._open_3d_mesh_viewer, padx=6, pady=4
        )
        self.mesh3d_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self.pv_gpu_btn = tk.Button(
            vis_bar, text="🧊 Open 3D Window", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            command=self._open_pyvista_window, padx=6, pady=4
        )
        self.pv_gpu_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.claude_btn = tk.Button(
            vis_bar, text="🔬 Ultrasonic Tab", font=FONT_BTN, relief=tk.FLAT, bd=0, highlightthickness=0,
            bg=self.colors["button_violet"], fg=self.colors["button_violet_fg"],
            activebackground=self.colors["button_violet_active"],
            activeforeground=self.colors["button_violet_fg"],
            command=lambda: self.notebook.select(self.claude_tab), padx=6, pady=4
        )
        self.claude_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))
        self.claude_pv_btn = self.pv_btn

        # Live Simulation Stage & Progress Tracker
        self.tracker_frame = tk.LabelFrame(
            self.right_panel, text="Simulation Progress",
            font=FONT_SECTION, padx=8, pady=4
        )
        self.tracker_frame.pack(fill=tk.X, padx=6, pady=(2, 4))
        self._reg(self.tracker_frame, "card_labelframe")
        self._add_info_btn_to_labelframe(self.tracker_frame, self._show_physics_info)

        self.progress_bar = ttk.Progressbar(self.tracker_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, padx=4, pady=(2, 3))

        self.stage_label = tk.Label(
            self.tracker_frame, text="Ready to Run",
            font=FONT_SECTION, fg="#0d6efd"
        )
        self.stage_label.pack(anchor=tk.W, padx=4)
        self._reg(self.stage_label, "label")

        self.step_detail_label = tk.Label(
            self.tracker_frame, text="Progress: 0%  |  Peak Temp: 25.0 C",
            font=FONT_MONO_SM, fg="#64748b"
        )
        self.step_detail_label.pack(anchor=tk.W, padx=4)
        self._reg(self.step_detail_label, "label_dim")

        # Full-height Vertical Console Frame
        self.console_frame = tk.LabelFrame(
            self.right_panel, text="Solver Output Stream",
            font=FONT_SECTION
        )
        self.console_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))
        self._reg(self.console_frame, "card_labelframe")
        self._add_info_btn_to_labelframe(self.console_frame, self._show_physics_info)

        # Sleek mini-toolbar with live status, auto-scroll toggle, copy and clear
        self.console_toolbar = tk.Frame(self.console_frame, bg=self.colors["bg_card"])
        self.console_toolbar.pack(fill=tk.X, padx=6, pady=(2, 4))
        self._reg(self.console_toolbar, "card_frame")

        self.console_status_dot = tk.Label(
            self.console_toolbar, text="● IDLE",
            font=FONT_TINY, fg="#64748b", bg=self.colors["bg_card"]
        )
        self.console_status_dot.pack(side=tk.LEFT, padx=(2, 8))
        self._reg(self.console_status_dot, "label_dim")

        self.console_autoscroll_var = tk.BooleanVar(value=True)
        self.console_autoscroll_chk = ttk.Checkbutton(
            self.console_toolbar, text="Auto-Scroll",
            variable=self.console_autoscroll_var
        )
        self.console_autoscroll_chk.pack(side=tk.LEFT, padx=4)

        self.console_copy_btn = tk.Button(
            self.console_toolbar, text="Copy Output",
            font=FONT_SMALL, relief=tk.FLAT, bd=0, padx=6, pady=2,
            bg=self.colors["button"], fg=self.colors["button_fg"],
            command=self._console_copy
        )
        self.console_copy_btn.pack(side=tk.RIGHT, padx=2)
        self._reg(self.console_copy_btn, "button")

        self.console_clear_btn = tk.Button(
            self.console_toolbar, text="Clear Stream",
            font=FONT_SMALL, relief=tk.FLAT, bd=0, padx=6, pady=2,
            bg=self.colors["button"], fg=self.colors["button_fg"],
            command=self._console_clear
        )
        self.console_clear_btn.pack(side=tk.RIGHT, padx=2)
        self._reg(self.console_clear_btn, "button")

        self.console = scrolledtext.ScrolledText(
            self.console_frame,
            font=FONT_CONSOLE, wrap=tk.WORD, state=tk.DISABLED,
            spacing1=3, spacing2=1, spacing3=3,
            padx=12, pady=8
        )
        self.console.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self._init_console_tags()
        self._add_tooltips()

    def _add_tooltips(self):
        """Hover help for jargon fields and ambiguous actions."""
        try:
            Tooltip(self.run_btn, "Run FreeFEM simulation for the active case.\nShortcut: Ctrl/Cmd+Enter")
            Tooltip(self.stop_btn, "Stop the running simulation.\nShortcut: Esc. Keeps partial results.")
            Tooltip(self.view_results_btn, "Open the HTML report for the active run folder.")
            Tooltip(self.pv_btn, "Open the active run (FreeFEM visual outputs) in ParaView.")
            Tooltip(self.out_btn, "Reveal the active timestamped run folder in Finder/Explorer.")
            Tooltip(self.gen_btn, "Generate waam_simulation.edp + parameters.json without solving.")
            Tooltip(self.mesh3d_btn, "Switch to the embedded WAAM Slicer & 3D Twin tab.")
            Tooltip(self.pv_gpu_btn, "Open an isolated PyVista 3D window (avoids Tk/VTK event clash).")
            Tooltip(self.foam_btn, "Generate a BeamWeldFoam CFD case from Process + Material tabs.")
            Tooltip(self.claude_btn, "Open custom multi-material stack configuration.")
            Tooltip(self.claude_100mm_btn, "Run the 50-layer 100 mm multi-material wall.")
            Tooltip(self.claude_pv_btn, "Open multi-material results (waam.pvd) in ParaView.")
            Tooltip(self.theme_btn, "Toggle light/dark theme. All panels follow.")
            Tooltip(self.console_clear_btn, "Clear the active solver output stream.")
            Tooltip(self.console_copy_btn, "Copy all solver output text to clipboard.")
            Tooltip(self.console_autoscroll_chk, "Toggle auto-scrolling to the bottom as new lines stream in.")
        except Exception:
            pass

    def _build_openfoam_tab(self):
        """Dedicated OpenFOAM CFD (beamWeldFoam) tab with melt pool simulation controls."""
        from gui.tabs.openfoam_tab import build_openfoam_tab
        return build_openfoam_tab(self)

    def _collect_cfd_params(self) -> dict:
        from gui.controllers.openfoam_controller import collect_cfd_params
        return collect_cfd_params(self)

    def _cfd_case_subdir(self, run_dir: str) -> str:
        from gui.controllers.openfoam_controller import cfd_case_subdir
        return cfd_case_subdir(run_dir)

    def _find_cfd_case_dir(self, run_dir: str):
        from gui.controllers.openfoam_controller import find_cfd_case_dir
        return find_cfd_case_dir(run_dir)

    def _openfoam_generate_case(self):
        from gui.controllers.openfoam_controller import openfoam_generate_case
        return openfoam_generate_case(self)

    def _openfoam_run(self):
        from gui.controllers.openfoam_controller import openfoam_run
        return openfoam_run(self)

    def _open_cfd_report(self):
        from gui.controllers.openfoam_controller import open_cfd_report
        return open_cfd_report(self)

    def _openfoam_paraview(self):
        from gui.controllers.openfoam_controller import openfoam_paraview
        return openfoam_paraview(self)

    def _build_parametric_tab(self):
        """Dedicated Parametric Sweep & Design of Experiments (DOE) Tab."""
        from gui.tabs.parametric_tab import build_parametric_tab
        return build_parametric_tab(self)

    def _parse_csv_num_list(self, text: str, default_val: float) -> list:
        from gui.controllers.parametric_controller import parse_csv_num_list
        return parse_csv_num_list(text, default_val)

    def _generate_doe_matrix(self):
        from gui.controllers.parametric_controller import generate_doe_matrix
        return generate_doe_matrix(self)

    def _run_parametric_sweep(self):
        from gui.controllers.parametric_controller import run_parametric_sweep
        return run_parametric_sweep(self)

    def _build_viewport_tab(self):
        """Dedicated full-size 3D Slicer & Twin Viewport Tab (lazy loaded for high responsiveness)."""
        from gui.tabs.viewport_tab import build_viewport_tab
        return build_viewport_tab(self)

    def _ensure_viewport_loaded(self):
        """Instantiate the heavy 3D Slicer / Viewport only on first user activation."""
        from gui.tabs.viewport_tab import ensure_viewport_loaded
        return ensure_viewport_loaded(self)

    def _build_default_case_tab(self):
        """Dedicated tab to view the live FreeFEM++ .edp script generated dynamically by EDPBuilder."""
        from gui.tabs.default_case_tab import build_default_case_tab
        return build_default_case_tab(self)

    def _refresh_generated_edp_preview(self):
        """Dynamically render the exact FreeFEM++ .edp script that EDPBuilder generates from current inputs."""
        from gui.tabs.default_case_tab import refresh_generated_edp_preview
        return refresh_generated_edp_preview(self)

    
    def _build_claude_tab(self):
        """Dedicated tab for Ultrasonic and Multi-Material WAAM Solver."""
        from gui.tabs.ultrasonic_tab import build_ultrasonic_tab
        return build_ultrasonic_tab(self)

    def _on_ultrasonic_physics_toggle(self):
        """Update ultrasonic status badge when physics checkbox is toggled."""
        self._update_ultrasonic_status_badge()

    def _toggle_ultrasonic_from_tab(self):
        """Toggle ultrasonic physics checkbox directly from Ultrasonic tab."""
        if hasattr(self, "enable_ultrasonic_var"):
            new_val = not self.enable_ultrasonic_var.get()
            self.enable_ultrasonic_var.set(new_val)
            self._update_ultrasonic_status_badge()

    def _update_ultrasonic_status_badge(self):
        """Refresh badge in Ultrasonic tab reflecting whether physics is enabled."""
        if hasattr(self, "us_physics_status_lbl") and hasattr(self, "enable_ultrasonic_var"):
            is_on = bool(self.enable_ultrasonic_var.get())
            if is_on:
                self.us_physics_status_lbl.config(
                    text="✓ Ultrasonic Physics Module: ACTIVE (Coupled 20 kHz Acoustic Softening ON)",
                    fg="#16a34a"
                )
                if hasattr(self, "us_toggle_btn"):
                    self.us_toggle_btn.config(text="Disable in Physics Tab", fg="#dc2626")
            else:
                self.us_physics_status_lbl.config(
                    text="⚠ Ultrasonic Physics Module: DISABLED (Physics Tab OFF — Zero Acoustic Softening Applied)",
                    fg="#ea580c"
                )
                if hasattr(self, "us_toggle_btn"):
                    self.us_toggle_btn.config(text="Enable in Physics Tab", fg="#2563eb")
    def _add_us_zone(self, layers: int = None, material: str = None):
        from gui.controllers.ultrasonic_controller import add_us_zone
        return add_us_zone(self, layers, material)

    def _remove_us_zone(self, row_frame: tk.Frame):
        from gui.controllers.ultrasonic_controller import remove_us_zone
        return remove_us_zone(self, row_frame)

    def _auto_balance_us_zones(self):
        from gui.controllers.ultrasonic_controller import auto_balance_us_zones
        return auto_balance_us_zones(self)

    def _refresh_us_zones(self):
        from gui.controllers.ultrasonic_controller import refresh_us_zones
        return refresh_us_zones(self)

    def _build_sim_log_tab(self):
        """Dedicated Simulation Log Viewer Tab with search, color tags, and export."""
        from gui.tabs.sim_log_tab import build_sim_log_tab
        return build_sim_log_tab(self)

    def _log_reload(self):
        """Reload sim.log from the FreeFEM side (legacy flat layout as fallback)."""
        from gui.tabs.sim_log_tab import log_reload
        return log_reload(self)

    def _log_search(self):
        """Highlight all occurrences of the search term in the log viewer."""
        from gui.tabs.sim_log_tab import log_search
        return log_search(self)

    def _log_export(self):
        """Export the current log content to a user-chosen file."""
        from gui.tabs.sim_log_tab import log_export
        return log_export(self)

    def _log_clear(self):
        """Clear the log viewer content (with confirm)."""
        from gui.tabs.sim_log_tab import log_clear
        return log_clear(self)

    def _console_clear(self):
        """Clear the active solver output stream console."""
        self.console.config(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.config(state=tk.DISABLED)

    def _console_copy(self):
        """Copy active solver output stream contents to system clipboard."""
        try:
            content = self.console.get("1.0", tk.END).strip()
            if content:
                self.root.clipboard_clear()
                self.root.clipboard_append(content)
                if hasattr(self, "console_copy_btn"):
                    old_text = self.console_copy_btn.cget("text")
                    self.console_copy_btn.config(text="✓ Copied")
                    self.root.after(1500, lambda: self.console_copy_btn.config(text=old_text))
        except Exception:
            pass

    def _init_console_tags(self):
        """Configure syntax tags for solver output stream highlighting and typography."""
        if not hasattr(self, "console"):
            return
        is_dark = (getattr(self, "current_theme", "light") == "dark")
        tag_colors = {
            "banner": {
                "foreground": "#38bdf8" if is_dark else "#0284c7",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold")
            },
            "layer": {
                "foreground": "#67e8f9" if is_dark else "#0369a1",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold"),
                "spacing1": 5
            },
            "phase": {
                "foreground": "#c084fc" if is_dark else "#7c3aed",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold"),
                "spacing1": 4
            },
            "step": {
                "foreground": "#cbd5e1" if is_dark else "#334155"
            },
            "ok": {
                "foreground": "#4ade80" if is_dark else "#16a34a",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold")
            },
            "warn": {
                "foreground": "#fbbf24" if is_dark else "#d97706",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold")
            },
            "error": {
                "foreground": "#f87171" if is_dark else "#dc2626",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold")
            },
            "info": {
                "foreground": "#38bdf8" if is_dark else "#0284c7"
            },
            "bullet": {
                "foreground": "#a78bfa" if is_dark else "#6366f1",
                "font": (FONT_CONSOLE[0], FONT_CONSOLE[1], "bold")
            },
            "dim": {
                "foreground": "#64748b"
            },
        }
        for tag_name, opts in tag_colors.items():
            try:
                self.console.tag_configure(tag_name, **opts)
            except Exception:
                pass


    def _refresh_embedded_viewport(self):
        """Update the embedded 3D mesh viewport with current parameters if currently viewed."""
        try:
            if not getattr(self, "_viewport_loaded", False):
                return
            selected_tab = self.notebook.select()
            if hasattr(self, "viewport_tab") and selected_tab != str(self.viewport_tab):
                return
            params = self._collect_params()
            if hasattr(self, "loaded_stl_path") and self.loaded_stl_path and os.path.exists(self.loaded_stl_path):
                params["stl_file"] = self.loaded_stl_path
            if hasattr(self, "mesh_file_var") and self.mesh_file_var.get():
                mpath = self.mesh_file_var.get().strip()
                if os.path.exists(mpath):
                    if mpath.lower().endswith(('.gcode', '.nc')):
                        params["gcode_file"] = mpath
                    else:
                        params["mesh_file"] = mpath
            if hasattr(self, "viewport") and self.viewport:
                self.viewport.update_mesh(params)
            elif hasattr(self, "viewport_3d") and self.viewport_3d:
                self.viewport_3d.update_mesh(params)
        except Exception:
            pass

    def _mark_custom_preset(self):
        """Auto-switch the preset selector to Custom on any manual edit.

        Programmatic .set() on preset_var does NOT fire the combobox
        <<ComboboxSelected>> event, so this never re-triggers _apply_preset.
        Suppressed while _apply_preset itself is writing values.
        """
        try:
            if getattr(self, "_applying_preset", False):
                return
            if not hasattr(self, "preset_var"):
                return
            if "Custom" not in PARAMETER_PRESETS:
                return
            if self.preset_var.get() != "Custom":
                self.preset_var.set("Custom")
        except Exception:
            pass

    def _apply_preset(self, event=None):
        """Apply a named parameter preset to all relevant GUI fields."""
        name = self.preset_var.get()
        # "Custom" bypasses every hardcoded preset: keep UI values verbatim.
        if name == "Custom":
            try:
                self._log("[PRESET] Custom configuration: using current UI values verbatim (no preset override).\n")
            except Exception:
                pass
            return
        preset = PARAMETER_PRESETS.get(name)
        if not preset:
            return

        self._applying_preset = True
        try:
            # 1. Heat source first so its dimensions widgets exist
            if "heat_source" in preset and hasattr(self, "source_var"):
                self.source_var.set(str(preset["heat_source"]))
                self._update_source_params()

            # 2. Materials
            if "material_base" in preset and hasattr(self, "material_base_var"):
                self.material_base_var.set(str(preset["material_base"]))
            if "material_dep" in preset and hasattr(self, "material_dep_var"):
                self.material_dep_var.set(str(preset["material_dep"]))

            # 3. Geometry & Mesh source mode
            if "mesh_source" in preset and hasattr(self, "mesh_source_var"):
                self.mesh_source_var.set(str(preset["mesh_source"]))
                if hasattr(self, "_update_mesh_ui"):
                    self._update_mesh_ui()

            # 4. Mechanical BC option
            if "mechanical_bc" in preset and hasattr(self, "mech_bc_var"):
                bc_val = str(preset["mechanical_bc"]).lower()
                if "cantilever" in bc_val:
                    self.mech_bc_var.set("Cantilever (x=0 Face Fixed)")
                elif "clamped" in bc_val or "fixture" in bc_val:
                    self.mech_bc_var.set("Clamped Fixture (Full Baseplate Fixed)")
                else:
                    self.mech_bc_var.set("Isostatic 3-2-1 / Elastic Support (Recommended)")

            # 5. Physics checkboxes
            if "enable_radiation" in preset and hasattr(self, "rad_var"):
                self.rad_var.set(bool(preset["enable_radiation"]))
            if "enable_latent" in preset and hasattr(self, "latent_var"):
                self.latent_var.set(bool(preset["enable_latent"]))
            if "enable_mechanical" in preset and hasattr(self, "mech_var"):
                self.mech_var.set(bool(preset["enable_mechanical"]))
            if "enable_microstructure" in preset and hasattr(self, "micro_var"):
                self.micro_var.set(bool(preset["enable_microstructure"]))

            if hasattr(self, "_on_multi_material_change"):
                self._on_multi_material_change()

            # 6. Parameters in _param_vars
            for key, val in preset.items():
                if key in ("material_base", "material_dep", "heat_source", "mesh_source", "mechanical_bc",
                           "enable_radiation", "enable_latent", "enable_mechanical", "enable_microstructure"):
                    continue
                if key in self._param_vars:
                    self._param_vars[key][0].set("" if val is None else str(val))
                self.params[key] = val

        finally:
            self._applying_preset = False

        # A preset rewrites N_layer / h_bead / remelt: re-apply the active
        # dimensioning driver so H_build and N_layer can never go stale.
        try:
            self._sync_layer_mode()
        except Exception:
            pass
        self._update_mesh_calc()
        self._update_heat_calc()
        try:
            self._update_geom_fusion_label()
        except Exception:
            pass
        try:
            self._auto_sync_probe_points()
        except Exception:
            pass
        try:
            self._auto_update_wall_gcode()
        except Exception:
            pass
        self._log(f"[PRESET] Applied preset: {name}\n")

    def _toggle_theme(self):
        """Toggle between light and dark themes."""
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.colors = THEMES[self.current_theme]
        self._apply_theme()

    def _apply_theme(self):
        """Apply colors of the active theme to all UI elements."""
        if not hasattr(self, "btn_bar"):
            return

        c = self.colors
        bg = c["bg"]
        card = c["bg_card"]
        fg = c["fg"]
        accent = c["accent"]
        border = c["border"]

        self.root.configure(bg=bg)
        self.header.configure(bg=bg)
        self.title_frame.configure(bg=bg)
        self.header_right.configure(bg=bg)
        self.title_label.configure(bg=bg, fg=accent)
        if hasattr(self, "subtitle_label") and self.subtitle_label:
            self.subtitle_label.configure(bg=bg, fg=c["fg_dim"])
        self.status_label.configure(bg=bg, fg=c["accent2"])
        self.theme_btn.configure(
            bg=c["button"], fg=c["button_fg"],
            text="[ Dark Theme ]" if self.current_theme == "light" else "[ Light Theme ]"
        )
        self.right_panel.configure(bg=card)
        self.btn_bar.configure(bg=card)
        self.main_pane.configure(bg=bg)
        self.console_frame.configure(bg=card, fg=accent)
        if hasattr(self, "console_toolbar"):
            self.console_toolbar.configure(bg=card)
        if hasattr(self, "console_status_dot"):
            self.console_status_dot.configure(bg=card)
        if hasattr(self, "console_clear_btn"):
            self.console_clear_btn.configure(bg=c["button"], fg=c["button_fg"])
        if hasattr(self, "console_copy_btn"):
            self.console_copy_btn.configure(bg=c["button"], fg=c["button_fg"])
        self.console.configure(
            bg=c["console_bg"], fg=c["console_fg"],
            insertbackground=c["console_fg"]
        )
        self._init_console_tags()

        # Style standard ttk elements
        self.style.configure(".", background=bg, foreground=fg)
        self.style.configure("TNotebook", background=bg)
        self.style.configure(
            "TNotebook.Tab",
            background=c["tab_unselected_bg"],
            foreground=c["tab_unselected_fg"],
            padding=[10, 5],
            font=FONT_TAB
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", c["tab_selected_bg"])],
            foreground=[("selected", c["tab_selected_fg"])]
        )

        # Action buttons - all theme-aware (no hardcoded hex).
        # Standard grey buttons follow the theme button palette.
        _std_btns = [self.gen_btn, self.out_btn, self.pv_btn, self.foam_btn, self.pv_gpu_btn]
        for _extra in ("claude_100mm_btn", "claude_pv_btn"):
            if hasattr(self, _extra):
                _std_btns.append(getattr(self, _extra))
        for btn in _std_btns:
            try:
                btn.configure(
                    bg=c["button"], fg=c["button_fg"],
                    activebackground=border, activeforeground=c["button_fg"],
                    highlightbackground=border, relief=tk.FLAT, bd=0, highlightthickness=0
                )
            except Exception:
                pass

        # Accent buttons keep their hue per theme (light saturated / dark pastel)
        try:
            self.view_results_btn.configure(
                bg=c["button_primary"], fg=c["button_primary_fg"],
                activebackground=c["button_primary_active"],
                activeforeground=c["button_primary_fg"],
                relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass
        try:
            self.mesh3d_btn.configure(
                bg=c["button_info"], fg=c["button_info_fg"],
                activebackground=c["accent"],
                activeforeground=c["button_info_fg"],
                relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass
        if hasattr(self, "claude_btn"):
            try:
                self.claude_btn.configure(
                    bg=c["button_violet"], fg=c["button_violet_fg"],
                    activebackground=c["button_violet_active"],
                    activeforeground=c["button_violet_fg"],
                    relief=tk.FLAT, bd=0, highlightthickness=0
                )
            except Exception:
                pass
        for _b in ("claude_b1", "claude_b2"):
            if hasattr(self, _b):
                try:
                    _w = getattr(self, _b)
                    _is_primary = (_b == "claude_b1")
                    _w.configure(
                        bg=c["button_primary"] if _is_primary else c["button_violet"],
                        fg=c["button_primary_fg"] if _is_primary else c["button_violet_fg"],
                        activebackground=c["button_primary_active"] if _is_primary else c["button_violet_active"],
                        relief=tk.FLAT, bd=0, highlightthickness=0
                    )
                except Exception:
                    pass
        # CFD + Claude tab action buttons stored as refs where available.
        for _b in ("cfd_gen_btn", "cfd_run_btn", "claude_b3", "claude_pv_btn2", "claude_out_btn2"):
            if hasattr(self, _b):
                try:
                    getattr(self, _b).configure(
                        bg=c["button"], fg=c["button_fg"],
                        activebackground=border, activeforeground=c["button_fg"],
                        relief=tk.FLAT, bd=0, highlightthickness=0
                    )
                except Exception:
                    pass

        self.run_btn.configure(
            bg=c["button_run"], fg=c["button_run_fg"],
            activebackground=c["accent2"], activeforeground=c["button_run_fg"],
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
        self.stop_btn.configure(
            bg=c["error"], fg=c.get("button_run_fg", "#000000"),
            activebackground=border,
            relief=tk.FLAT, bd=0, highlightthickness=0
        )

        # Recursively apply to registered frames & labels.
        # NOTE: several Buttons were historically registered as "card_frame".
        # Treat those as theme buttons (bg + fg), otherwise text stays black
        # on a dark card and the theme looks "not changing".
        for widget, role in self.registered_widgets:
            try:
                if role == "card_frame":
                    try:
                        if widget.winfo_class() == "Button":
                            widget.configure(
                                bg=c["button"], fg=c["button_fg"],
                                activebackground=border, activeforeground=c["button_fg"],
                                highlightbackground=border,
                            )
                        else:
                            widget.configure(bg=card)
                    except Exception:
                        widget.configure(bg=card)
                elif role == "card_labelframe":
                    widget.configure(bg=card, fg=accent)
                elif role == "label":
                    widget.configure(bg=card, fg=fg)
                elif role == "label_dim":
                    widget.configure(bg=card, fg=c["fg_dim"])
                elif role == "entry":
                    widget.configure(
                        bg=c["bg_input"], fg=fg, insertbackground=fg,
                        readonlybackground=c["bg_input"], disabledbackground=c["bg_input"],
                        disabledforeground=c["fg_dim"], highlightbackground=border
                    )
                elif role == "button":
                    widget.configure(
                        bg=c["button"], fg=c["button_fg"],
                        activebackground=border, activeforeground=c["button_fg"],
                        highlightbackground=border,
                    )
                elif role == "radio":
                    widget.configure(bg=card, fg=fg, selectcolor=c["bg_input"], activebackground=card, activeforeground=accent)
                elif role == "check":
                    widget.configure(bg=card, fg=fg, selectcolor=c["bg_input"], activebackground=card)
            except Exception:
                pass

        # Text / Canvas / extra views that are otherwise stuck light.
        for _t in ("dissimilar_info", "default_case_text", "log_viewer"):
            if hasattr(self, _t):
                try:
                    getattr(self, _t).configure(
                        bg=c["bg_input"], fg=fg, insertbackground=fg,
                        highlightbackground=border, selectbackground=accent,
                    )
                except Exception:
                    pass
        # Scrollable tab canvases (Mesh / OpenFOAM) + viewport canvas frames.
        for _cv in ("mesh_canvas", "openfoam_canvas"):
            if hasattr(self, _cv):
                try:
                    getattr(self, _cv).configure(bg=card, highlightbackground=border)
                except Exception:
                    pass
        # Embedded 3D viewport follows the app theme (light/dark chrome).
        for _vp in ("viewport", "viewport_3d"):
            if hasattr(self, _vp):
                try:
                    _obj = getattr(self, _vp)
                    if hasattr(_obj, "apply_theme"):
                        _obj.apply_theme(self.current_theme)
                except Exception:
                    pass
        # Log level colors per theme (amber/green need dark variants for contrast).
        if hasattr(self, "log_viewer"):
            try:
                if self.current_theme == "dark":
                    self.log_viewer.tag_configure("error", foreground="#f38ba8")
                    self.log_viewer.tag_configure("warn", foreground="#f9e2af")
                    self.log_viewer.tag_configure("warning", foreground="#f9e2af")
                    self.log_viewer.tag_configure("ok", foreground="#a6e3a1")
                    self.log_viewer.tag_configure("info", foreground="#89b4fa")
                else:
                    self.log_viewer.tag_configure("error", foreground="#dc3545")
                    self.log_viewer.tag_configure("warn", foreground="#b45309")
                    self.log_viewer.tag_configure("warning", foreground="#b45309")
                    self.log_viewer.tag_configure("ok", foreground="#198754")
                    self.log_viewer.tag_configure("info", foreground="#0d6efd")
                self.log_viewer.tag_configure("search", background="#facc15", foreground="#1e1e2e")
            except Exception:
                pass

    def _reg(self, widget, role):
        self.registered_widgets.append((widget, role))
        return widget

    def _make_param_row(self, parent, label, key, row, unit="", type_="float", width=10, on_change=None):
        lbl = tk.Label(parent, text=label, font=FONT_LABEL)
        lbl.grid(row=row, column=0, sticky=tk.W, padx=(8, 4), pady=2)
        self._reg(lbl, "label")

        raw_val = self.params.get(key, "")
        if key in MM_DIMENSION_KEYS and isinstance(raw_val, (int, float)):
            display_val = round(raw_val * 1000.0, 2)
            raw_val = int(display_val) if display_val == int(display_val) else display_val
        elif key in MM_SPEED_KEYS and isinstance(raw_val, (int, float)):
            display_val = round(raw_val * 1000.0, 2)
            raw_val = int(display_val) if display_val == int(display_val) else display_val

        var = tk.StringVar(value=str(raw_val))
        entry = tk.Entry(parent, textvariable=var, width=width, font=FONT_ENTRY, relief=tk.SOLID, bd=1)
        entry.grid(row=row, column=1, padx=4, pady=2, sticky=tk.W)
        self._reg(entry, "entry")

        if unit:
            u_lbl = tk.Label(parent, text=unit, font=FONT_SMALL)
            u_lbl.grid(row=row, column=2, sticky=tk.W, padx=4)
            self._reg(u_lbl, "label_dim")

        self._param_vars[key] = (var, type_)
        if not hasattr(self, "param_entries"):
            self.param_entries = {}
        self.param_entries[key] = entry

        if key == "n_layers":
            entry.bind("<FocusIn>", lambda e: self._on_n_layers_focus())
            entry.bind("<KeyRelease>", lambda e: self._on_n_layers_key())

        if on_change:
            var.trace_add("write", lambda *args: on_change())
        else:
            # Central fan-out: EVERY parameter change refreshes every dependent readout
            var.trace_add("write", lambda *args: self._on_any_param_change(key))

        return var

    def _on_any_param_change(self, key):
        """Single refresh path for any parameter edit (window A -> window B)."""
        if getattr(self, "_applying_preset", False) or getattr(self, "_batch_updating", False):
            return
        try:
            self._mark_custom_preset()
            if key == "n_layers":
                if not getattr(self, "_syncing_layer_mode", False):
                    if hasattr(self, "_layer_mode") and self._layer_mode.get() != "n_layers":
                        self._layer_mode.set("n_layers")
                    self._sync_from_n_layers()
            elif key in ("h_bead", "remelt_ratio"):
                self._sync_layer_mode()
            if key in ("n_layers", "h_bead", "remelt_ratio", "ty_dep"):
                self._sync_geometry_to_ultrasonic()
            if key == "n_layers" and "nz_dep" in self._param_vars:
                nl_v = self._param_vars["n_layers"][0].get().strip()
                if nl_v:
                    try:
                        nl_int = int(float(nl_v))
                        # RULE: Mesh must have at least twice the number of cells than height!
                        self._param_vars["nz_dep"][0].set(str(max(2 * nl_int, 2)))
                    except Exception:
                        self._param_vars["nz_dep"][0].set(nl_v)
                try:
                    self._last_n_layers = int(float(nl_v))
                except (TypeError, ValueError):
                    pass
            # Inter-module synchronizations (Geometry/Process -> Mesh)
            if key == "h_bead":
                self._sync_h_bead_to_mesh()
            elif key == "ty_dep":
                self._sync_ty_dep_to_mesh()
            elif key == "v_scan":
                self._sync_feedrate_to_mesh()
            elif key == "t_wait":
                self._sync_dwell_to_mesh()
            elif key in ("U_weld", "I_weld"):
                self._sync_power_to_mesh()

            # Debounce heavy downstream calculations & disk I/O to avoid UI lag
            self._schedule_full_refresh()
        except Exception:
            pass

    def _schedule_full_refresh(self):
        """Debounce downstream UI readouts and file generation."""
        if hasattr(self, "_refresh_timer") and self._refresh_timer:
            try:
                self.root.after_cancel(self._refresh_timer)
            except Exception:
                pass
        self._refresh_timer = self.root.after(150, self._do_full_refresh)

    def _do_full_refresh(self):
        """Execute debounced recalculations and schedule G-code disk write."""
        try:
            self._update_mesh_calc()
            self._update_heat_calc()
            self._update_geom_fusion_label()
            self._update_material_wire_readout()
            self._auto_sync_probe_points()
            self._schedule_gcode_update()
        except Exception:
            pass

    def _schedule_gcode_update(self):
        """Debounce toolpath synthesis and file writes to eliminate typing latency."""
        if hasattr(self, "_gcode_timer") and self._gcode_timer:
            try:
                self.root.after_cancel(self._gcode_timer)
            except Exception:
                pass
        self._gcode_timer = self.root.after(350, self._auto_update_wall_gcode)

    def _sync_layer_mode(self):
        """Apply whichever of N_layer / target build height is currently the driver."""
        if not hasattr(self, "_layer_mode"):
            return
        if self._layer_mode.get() == "n_layers":
            self._sync_from_n_layers()
        else:
            self._sync_from_h_bead()

    def _sync_geometry_to_ultrasonic(self):
        from gui.controllers.ultrasonic_controller import sync_geometry_to_ultrasonic
        return sync_geometry_to_ultrasonic(self)

    def _sync_ultrasonic_to_geometry(self):
        from gui.controllers.ultrasonic_controller import sync_ultrasonic_to_geometry
        return sync_ultrasonic_to_geometry(self)


    def _sync_h_bead_to_mesh(self):
        """Keep Mesh Slicer layer height and target dz in sync with Geometry h_bead."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            h_str = self._param_vars["h_bead"][0].get().strip() if "h_bead" in self._param_vars else ""
            if h_str and hasattr(self, "slicer_h_var") and self.slicer_h_var.get() != h_str:
                self.slicer_h_var.set(h_str)
            try:
                h_val = float(h_str)
                dz_val = f"{h_val / 2.0:.3f}"
                if hasattr(self, "target_dz_var") and self.target_dz_var.get() != dz_val:
                    self.target_dz_var.set(dz_val)
            except Exception:
                pass
        finally:
            self._syncing_mesh_vars = False

    def _sync_ty_dep_to_mesh(self):
        """Keep Mesh Slicer bead width and target dy in sync with Geometry ty_dep."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            w_str = self._param_vars["ty_dep"][0].get().strip() if "ty_dep" in self._param_vars else ""
            if w_str and hasattr(self, "slicer_w_var") and self.slicer_w_var.get() != w_str:
                self.slicer_w_var.set(w_str)
            try:
                w_val = float(w_str)
                dy_val = f"{w_val / 4.0:.3f}"
                if hasattr(self, "target_dy_var") and self.target_dy_var.get() != dy_val:
                    self.target_dy_var.set(dy_val)
            except Exception:
                pass
        finally:
            self._syncing_mesh_vars = False

    def _sync_feedrate_to_mesh(self):
        """Keep Mesh Slicer weld feedrate (mm/min) in sync with Process v_scan (mm/s)."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            v_val = float(self._param_vars["v_scan"][0].get().strip() or "0") if "v_scan" in self._param_vars else 0.0
            v_mms = v_val if v_val > 0.05 else v_val * 1000.0
            feed = f"{v_mms * 60.0:.1f}"
            if hasattr(self, "slicer_feedrate_var") and self.slicer_feedrate_var.get() != feed:
                self.slicer_feedrate_var.set(feed)
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _sync_dwell_to_mesh(self):
        """Keep Mesh Slicer inter-layer dwell time in sync with Process t_wait."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            dw_str = self._param_vars["t_wait"][0].get().strip() if "t_wait" in self._param_vars else ""
            if hasattr(self, "slicer_dwell_var") and self.slicer_dwell_var.get() != dw_str:
                self.slicer_dwell_var.set(dw_str)
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _sync_power_to_mesh(self):
        """Keep Mesh Slicer arc power in sync with Process U_weld * I_weld."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            u = float(self._param_vars["U_weld"][0].get().strip() or "20") if "U_weld" in self._param_vars else 20.0
            i = float(self._param_vars["I_weld"][0].get().strip() or "180") if "I_weld" in self._param_vars else 180.0
            p = f"{u * i:.1f}"
            if hasattr(self, "slicer_power_var") and self.slicer_power_var.get() != p:
                self.slicer_power_var.set(p)
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _on_slicer_h_change(self, *args):
        """Callback when user edits Layer Height in Mesh Slicer."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            val = self.slicer_h_var.get().strip()
            if val and "h_bead" in self._param_vars and self._param_vars["h_bead"][0].get() != val:
                self._param_vars["h_bead"][0].set(val)
                self._sync_layer_mode()
                self._sync_geometry_to_ultrasonic()
                self._update_geom_fusion_label()
                self._update_mesh_calc()
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _on_slicer_w_change(self, *args):
        """Callback when user edits Bead Width in Mesh Slicer."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            val = self.slicer_w_var.get().strip()
            if val and "ty_dep" in self._param_vars and self._param_vars["ty_dep"][0].get() != val:
                self._param_vars["ty_dep"][0].set(val)
                self._sync_geometry_to_ultrasonic()
                self._update_geom_fusion_label()
                self._update_mesh_calc()
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _on_slicer_feedrate_change(self, *args):
        """Callback when user edits Weld Feedrate (mm/min) in Mesh Slicer."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            val = float(self.slicer_feedrate_var.get().strip() or "0")
            v_mms = val / 60.0
            if "v_scan" in self._param_vars:
                cur_v = float(self._param_vars["v_scan"][0].get().strip() or "0")
                new_v_str = f"{v_mms / 1000.0:.4f}" if (0.0 < cur_v < 0.1) else f"{v_mms:.2f}"
                if self._param_vars["v_scan"][0].get() != new_v_str:
                    self._param_vars["v_scan"][0].set(new_v_str)
                    self._update_heat_calc()
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _on_slicer_dwell_change(self, *args):
        """Callback when user edits Dwell Time in Mesh Slicer."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            val = self.slicer_dwell_var.get().strip()
            if "t_wait" in self._param_vars and self._param_vars["t_wait"][0].get() != val:
                self._param_vars["t_wait"][0].set(val)
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _on_slicer_power_change(self, *args):
        """Callback when user edits Arc Power (W) in Mesh Slicer."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            val = float(self.slicer_power_var.get().strip() or "0")
            if val > 0:
                u = float(self._param_vars["U_weld"][0].get().strip() or "20") if "U_weld" in self._param_vars else 20.0
                if u > 0 and "I_weld" in self._param_vars:
                    new_i = f"{val / u:.1f}"
                    if self._param_vars["I_weld"][0].get() != new_i:
                        self._param_vars["I_weld"][0].set(new_i)
                        self._update_heat_calc()
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    def _on_slicer_pattern_change(self, *args):
        """Callback when user edits Infill Pattern in Mesh Slicer."""
        if getattr(self, "_syncing_mesh_vars", False): return
        self._syncing_mesh_vars = True
        try:
            spat = self.slicer_pattern_var.get()
            if hasattr(self, "deposition_pattern_var") and self.deposition_pattern_var.get() != spat:
                self.deposition_pattern_var.set(spat)
                self._update_geom_fusion_label()
                self._auto_update_wall_gcode()
        except Exception:
            pass
        finally:
            self._syncing_mesh_vars = False

    # ============================================================
    # TABS IMPLEMENTATION
    # ============================================================

    def _build_geometry_tab(self):
        from gui.tabs.geometry_tab import build_geometry_tab
        return build_geometry_tab(self)

    # -- numeric helpers ---------------------------------------------------
    @staticmethod
    def _f(var_name, default):
        try:
            raw = var_name.get().strip()
            return float(raw) if raw else float(default)
        except Exception:
            return float(default)

    def _current_build_height_mm(self):
        # In CAD mode, CAD bounding box height is ground truth:
        if getattr(self, "_cad_bbox_z", 0) > 0 and getattr(self, "mesh_source_var", None) and self.mesh_source_var.get() == "cad_file":
            return float(self._cad_bbox_z)
        h1 = self._f(self._param_vars["h_bead"][0], 4.0) if "h_bead" in self._param_vars else 4.0
        remelt = (self._f(self._param_vars["remelt_ratio"][0], 0.8)
                  if "remelt_ratio" in self._param_vars else 0.8)
        nl = 1
        if "n_layers" in self._param_vars:
            try:
                nl = max(int(float(self._param_vars["n_layers"][0].get().strip() or "1")), 1)
            except Exception:
                nl = 1
        return h1 if nl <= 1 else (h1 + (nl - 1) * h1 * remelt)

    def _on_n_layers_focus(self):
        if hasattr(self, "_layer_mode") and self._layer_mode.get() != "n_layers":
            self._layer_mode.set("n_layers")
            self._on_layer_mode_change()

    def _on_n_layers_key(self):
        if hasattr(self, "_layer_mode") and self._layer_mode.get() != "n_layers":
            self._layer_mode.set("n_layers")
        self._sync_from_n_layers()
        self._update_geom_fusion_label()
        self._update_mesh_calc()
        self._update_heat_calc()
        self._auto_sync_probe_points()

    def _on_build_height_focus(self):
        if hasattr(self, "_layer_mode") and self._layer_mode.get() != "height":
            self._layer_mode.set("height")
            self._on_layer_mode_change()

    def _on_build_height_key(self):
        if hasattr(self, "_layer_mode") and self._layer_mode.get() != "height":
            self._layer_mode.set("height")
        self._sync_from_h_bead()
        self._update_geom_fusion_label()
        self._update_mesh_calc()
        self._update_heat_calc()
        self._auto_sync_probe_points()

    def _sync_from_n_layers(self):
        """Total layer count N_layer drives the build: compute the resulting total wall height."""
        if not hasattr(self, "_param_vars") or "n_layers" not in self._param_vars:
            return
        if getattr(self, "_syncing_layer_mode", False):
            return
        self._syncing_layer_mode = True
        try:
            if getattr(self, "_cad_bbox_z", 0) > 0 and getattr(self, "mesh_source_var", None) and self.mesh_source_var.get() == "cad_file":
                if hasattr(self, "_build_height_var"):
                    self._build_height_var.set(f"{self._cad_bbox_z:.2f}")
                return
            h1 = self._f(self._param_vars["h_bead"][0], 4.0) if "h_bead" in self._param_vars else 4.0
            remelt = (self._f(self._param_vars["remelt_ratio"][0], 0.8)
                      if "remelt_ratio" in self._param_vars else 0.8)
            try:
                nl = max(int(float(self._param_vars["n_layers"][0].get().strip() or "1")), 1)
            except Exception:
                return
            h_sub = max(h1 * remelt, 1e-4)
            total_h = h1 if nl <= 1 else (h1 + (nl - 1) * h_sub)
            if hasattr(self, "_build_height_var"):
                cur_h = self._build_height_var.get().strip()
                new_h = f"{total_h:.2f}"
                if cur_h != new_h:
                    self._build_height_var.set(new_h)
        finally:
            self._syncing_layer_mode = False

    def _sync_from_h_bead(self):
        """Target build height H_build drives the build: compute the required N_layer."""
        if not hasattr(self, "_build_height_var") or not hasattr(self, "_param_vars"):
            return
        if getattr(self, "_syncing_layer_mode", False):
            return
        self._syncing_layer_mode = True
        try:
            h1 = self._f(self._param_vars["h_bead"][0], 4.0) if "h_bead" in self._param_vars else 4.0
            remelt = (self._f(self._param_vars["remelt_ratio"][0], 0.8)
                      if "remelt_ratio" in self._param_vars else 0.8)
            target_h = self._f(self._build_height_var, 0.0)
            if target_h <= 0 or h1 <= 0:
                return
            if getattr(self, "_cad_bbox_z", 0) > 0 and getattr(self, "mesh_source_var", None) and self.mesh_source_var.get() == "cad_file":
                nl = max(int(round(target_h / h1)), 1)
            else:
                h_sub = max(h1 * remelt, 1e-4)
                if target_h <= h1:
                    nl = 1
                else:
                    nl = 1 + int(math.ceil((target_h - h1) / h_sub - 1e-6))
            nl = max(1, nl)
            if "n_layers" in self._param_vars:
                cur_nl = self._param_vars["n_layers"][0].get().strip()
                if cur_nl != str(nl):
                    self._param_vars["n_layers"][0].set(str(nl))
        finally:
            self._syncing_layer_mode = False

    def _effective_layer_count(self):
        """Single source of truth for N_layer under the active driver.

        Returns (nl, target_h_mm_or_None, actual_h_mm).
        """
        try:
            h1 = self._f(self._param_vars["h_bead"][0], 4.0) if "h_bead" in self._param_vars else 4.0
        except Exception:
            h1 = 4.0
        try:
            remelt = self._f(self._param_vars["remelt_ratio"][0], 0.8) if "remelt_ratio" in self._param_vars else 0.8
        except Exception:
            remelt = 0.8
        try:
            raw_nl = self._param_vars["n_layers"][0].get().strip() if "n_layers" in self._param_vars else ""
            nl_entry = max(int(float(raw_nl)), 1) if raw_nl else 1
        except Exception:
            nl_entry = 1

        if getattr(self, "_cad_bbox_z", 0) > 0 and getattr(self, "mesh_source_var", None) and self.mesh_source_var.get() == "cad_file":
            cad_h = float(self._cad_bbox_z)
            return nl_entry, cad_h, cad_h

        mode = getattr(self, "_layer_mode", None)
        mode_val = mode.get() if mode is not None else "n_layers"
        h_sub = max(h1 * remelt, 1e-4)
        if mode_val in ("height", "h_bead"):
            try:
                target_h = self._f(getattr(self, "_build_height_var", None), 0.0)
            except Exception:
                target_h = 0.0
            if target_h > 0 and h1 > 0:
                nl = 1 if target_h <= h1 else 1 + int(math.ceil((target_h - h1) / h_sub - 1e-6))
                nl = max(1, nl)
                actual_h = h1 if nl <= 1 else (h1 + (nl - 1) * h_sub)
                return nl, target_h, actual_h
            actual_h = h1 if nl_entry <= 1 else (h1 + (nl_entry - 1) * h_sub)
            return nl_entry, None, actual_h
        actual_h = h1 if nl_entry <= 1 else (h1 + (nl_entry - 1) * h_sub)
        return nl_entry, None, actual_h

    def _on_layer_mode_change(self):
        try:
            self._mark_custom_preset()
        except Exception:
            pass
        mode = getattr(self, "_layer_mode", None)
        if mode is None:
            return
        is_n = (mode.get() == "n_layers")
        # Both fields remain editable at all times; syncing aligns them
        if is_n:
            self._sync_from_n_layers()
        else:
            self._sync_from_h_bead()
        self._update_geom_fusion_label()
        self._update_mesh_calc()
        self._update_heat_calc()
        self._auto_sync_probe_points()

    def _on_build_height_change(self):
        try:
            self._mark_custom_preset()
        except Exception:
            pass
        if getattr(self, "_syncing_layer_mode", False):
            return
        mode = getattr(self, "_layer_mode", None)
        if mode is None or mode.get() not in ("h_bead", "height"):
            return
        self._sync_from_h_bead()
        self._update_geom_fusion_label()
        self._update_mesh_calc()
        self._update_heat_calc()
        self._auto_sync_probe_points()

    def _auto_sync_probe_points(self):
        """Auto-update probe points and paths in Solver tab from Geometry window unless user custom coordinates active."""
        if hasattr(self, "probe_points_text") and not getattr(self, "_user_custom_probes", False):
            try:
                default_txt = self._get_default_probe_points_text()
                self.probe_points_text.delete("1.0", tk.END)
                self.probe_points_text.insert("1.0", default_txt)
            except Exception:
                pass
        if hasattr(self, "probe_paths_text") and not getattr(self, "_user_custom_paths", False):
            try:
                path_txt = self._get_default_probe_paths_text()
                self.probe_paths_text.delete("1.0", tk.END)
                self.probe_paths_text.insert("1.0", path_txt)
            except Exception:
                pass
        self._update_probe_geom_badge()

    def _update_geom_fusion_label(self):
        """Update dynamic info label in Geometry tab for Layer 1, subsequent layers, total build height, and pattern."""
        if not hasattr(self, "geom_fusion_info_lbl"):
            return
        try:
            h1 = 4.0
            if "h_bead" in self._param_vars:
                raw = self._param_vars["h_bead"][0].get().strip()
                if raw:
                    h1 = float(raw)
            remelt = 0.80
            if "remelt_ratio" in self._param_vars:
                raw_r = self._param_vars["remelt_ratio"][0].get().strip()
                if raw_r:
                    remelt = float(raw_r)
            nl_eff, target_h, h_total = self._effective_layer_count()
            nl = nl_eff
            h_sub = h1 * remelt
            pat_str = self.deposition_pattern_var.get().capitalize() if hasattr(self, "deposition_pattern_var") else "Zigzag"
            if getattr(self, "_cad_bbox_z", 0) > 0 and getattr(self, "mesh_source_var", None) and self.mesh_source_var.get() == "cad_file":
                cad_n = getattr(self, "_cad_name", "Loaded CAD")
                txt = (
                    f"ℹ CAD Model: {cad_n} (BBox: {getattr(self, '_cad_bbox_x', 0):.1f} × {getattr(self, '_cad_bbox_y', 0):.1f} × {self._cad_bbox_z:.1f} mm) | "
                    f"Build Height = {self._cad_bbox_z:.2f} mm | N_layer = {nl} (h = {h1:.2f} mm) | Pattern: {pat_str}"
                )
            else:
                mode = getattr(self, "_layer_mode", None)
                mode_val = mode.get() if mode is not None else "n_layers"
                if mode_val in ("height", "h_bead") and target_h:
                    txt = (
                        f"ℹ Fusion Profile: Layer 1 = {h1:.2f} mm | Subsequent = {h_sub:.2f} mm "
                        f"({remelt*100.0:.0f}% height retention) | Driver: Target H_build = {target_h:.2f} mm → "
                        f"N_layer = {nl} | Actual Wall Height = {h_total:.2f} mm | Pattern: {pat_str}"
                    )
                else:
                    txt = (
                        f"ℹ Fusion Profile: Layer 1 = {h1:.2f} mm | Subsequent = {h_sub:.2f} mm "
                        f"({remelt*100.0:.0f}% height retention) | Driver: N_layer = {nl} | "
                        f"Total Wall Height = {h_total:.2f} mm | Pattern: {pat_str}"
                    )
            self.geom_fusion_info_lbl.config(text=txt)
        except Exception:
            pass

    def _on_deposition_pattern_change(self):
        """Callback when user toggles deposition pattern in Geometry tab."""
        try:
            self._mark_custom_preset()
        except Exception:
            pass
        if not getattr(self, "_syncing_mesh_vars", False):
            self._syncing_mesh_vars = True
            try:
                gpat = self.deposition_pattern_var.get()
                if hasattr(self, "slicer_pattern_var") and self.slicer_pattern_var.get() != gpat:
                    self.slicer_pattern_var.set(gpat)
            except Exception:
                pass
            finally:
                self._syncing_mesh_vars = False
    def _auto_update_wall_gcode(self, run_dir=None):
        """
        Dynamically synthesize and auto-update toolpath G-code (toolpath.gcode),
        FreeFEM++ toolpath reader array (toolpath.txt), and per-layer pass times (layer_pass_times.txt)
        for the active straight wall geometry and chosen deposition pattern.
        """
        try:
            # 1. Retrieve active geometry & kinematics parameters
            lx_mm = self._f(self._param_vars.get("lx", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "lx" in self._param_vars else 150.0
            ly_base_mm = self._f(self._param_vars.get("ly_base", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "ly_base" in self._param_vars else 150.0
            hz_base_mm = self._f(self._param_vars.get("hz_base", (None,))[0], 10.0) if hasattr(self, "_param_vars") and "hz_base" in self._param_vars else 10.0
            w_bead_mm = self._f(self._param_vars.get("ty_dep", (None,))[0], 5.0) if hasattr(self, "_param_vars") and "ty_dep" in self._param_vars else 5.0
            h1_mm = self._f(self._param_vars.get("h_bead", (None,))[0], 4.0) if hasattr(self, "_param_vars") and "h_bead" in self._param_vars else 4.0
            remelt = self._f(self._param_vars.get("remelt_ratio", (None,))[0], 0.8) if hasattr(self, "_param_vars") and "remelt_ratio" in self._param_vars else 0.8
            
            nl = 10
            if hasattr(self, "_param_vars") and "n_layers" in self._param_vars:
                try:
                    nl = max(int(float(self._param_vars["n_layers"][0].get().strip() or "1")), 1)
                except Exception:
                    nl = 10

            v_scan_mms = self._f(self._param_vars.get("v_scan", (None,))[0], 10.0) if hasattr(self, "_param_vars") and "v_scan" in self._param_vars else 10.0
            if v_scan_mms < 0.05:
                v_scan_mms *= 1000.0  # convert m/s to mm/s if in metres
            v_scan_mms = max(v_scan_mms, 0.1)
            feedrate_mmpm = v_scan_mms * 60.0
            rapid_mmpm = max(feedrate_mmpm * 5.0, 3000.0)

            t_dwell = self._f(self._param_vars.get("t_wait", (None,))[0], 10.0) if hasattr(self, "_param_vars") and "t_wait" in self._param_vars else 10.0
            i_weld = self._f(self._param_vars.get("I_weld", (None,))[0], 200.0) if hasattr(self, "_param_vars") and "I_weld" in self._param_vars else 200.0
            u_weld = self._f(self._param_vars.get("U_weld", (None,))[0], 24.0) if hasattr(self, "_param_vars") and "U_weld" in self._param_vars else 24.0
            power_w = i_weld * u_weld

            pattern = self.deposition_pattern_var.get() if hasattr(self, "deposition_pattern_var") else "bidirectional"
            is_bidi = (pattern.lower() == "bidirectional")

            # 2. Determine target directories
            target_dirs = []
            if run_dir:
                target_dirs.append(run_dir)
                fem_sub = os.path.join(run_dir, "FreeFEM")
                if os.path.exists(fem_sub):
                    target_dirs.append(fem_sub)
            else:
                # Active case or default case directory
                cur_out = self._get_current_run_dir() if hasattr(self, "_get_current_run_dir") else None
                if cur_out and os.path.exists(cur_out):
                    target_dirs.append(cur_out)
                    fem_sub = os.path.join(cur_out, "FreeFEM")
                    if os.path.exists(fem_sub):
                        target_dirs.append(fem_sub)
                if hasattr(self, "case_dir") and self.case_dir and os.path.exists(self.case_dir):
                    target_dirs.append(self.case_dir)

            if not target_dirs:
                base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "waam_output")
                os.makedirs(base_dir, exist_ok=True)
                target_dirs.append(base_dir)

            # 3. Synthesize G-code, toolpath.txt, and layer_pass_times.txt
            y_center_mm = ly_base_mm / 2.0
            x_min_mm = 0.0
            x_max_mm = lx_mm

            gcode_lines = [
                "; ============================================================",
                "; WAAM PRODUCTION TOOLPATH — AUTO-GENERATED BY WAAM-FRAMEWORK",
                "; ============================================================",
                f"; Deposition Pattern:       {pattern.upper()}",
                f"; Substrate Dimensions:     {lx_mm:.1f} x {ly_base_mm:.1f} x {hz_base_mm:.1f} mm",
                f"; Number of Layers:         {nl}",
                f"; Layer 1 Height:           {h1_mm:.2f} mm",
                f"; Subsequent Bead Height:   {h1_mm * remelt:.2f} mm (remelt={remelt*100:.0f}%)",
                f"; Bead Width:               {w_bead_mm:.2f} mm",
                f"; Torch Travel Speed:       {v_scan_mms:.1f} mm/s ({feedrate_mmpm:.0f} mm/min)",
                f"; Inter-pass Dwell Time:    {t_dwell:.1f} s",
                f"; Welding Power:            {power_w:.0f} W",
                "; ============================================================",
                "G90 ; Absolute Coordinates",
                "G21 ; Millimeter Units",
                "M82 ; Absolute Extruder / Wire Feed",
                f"M3 S{power_w:.0f} ; Arc ON",
                ""
            ]

            txt_lines = []
            layer_pass_times = []
            t_curr = 0.0

            z_curr_mm = hz_base_mm + h1_mm
            txt_lines.append(f"{t_curr:.3f} 0.00000 {y_center_mm/1000.0:.5f} {z_curr_mm/1000.0:.5f} 0")

            n_substeps = max(10, int(lx_mm / 2.0))

            for layer_idx in range(1, nl + 1):
                if layer_idx == 1:
                    z_curr_mm = hz_base_mm + h1_mm
                else:
                    z_curr_mm += h1_mm * remelt

                forward = True if (not is_bidi or layer_idx % 2 == 1) else False
                x_start = x_min_mm if forward else x_max_mm
                x_end = x_max_mm if forward else x_min_mm

                gcode_lines.append(f"; --- LAYER {layer_idx} (Z = {z_curr_mm:.3f} mm, {'FWD' if forward else 'REV'}) ---")
                
                if not forward or (not is_bidi and layer_idx > 1):
                    gcode_lines.append(f"G0 X{x_start:.3f} Y{y_center_mm:.3f} Z{z_curr_mm:.3f} F{rapid_mmpm:.0f}")
                    rapid_dist = abs(x_max_mm - x_min_mm)
                    dt_rapid = rapid_dist / (rapid_mmpm / 60.0)
                    t_curr += dt_rapid
                    txt_lines.append(f"{t_curr:.3f} {x_start/1000.0:.5f} {y_center_mm/1000.0:.5f} {z_curr_mm/1000.0:.5f} 0")
                else:
                    gcode_lines.append(f"G0 Z{z_curr_mm:.3f} F{rapid_mmpm:.0f}")

                gcode_lines.append(f"G1 X{x_end:.3f} Y{y_center_mm:.3f} F{feedrate_mmpm:.0f}")

                t_pass = abs(x_end - x_start) / v_scan_mms
                layer_pass_times.append(t_pass)

                for step in range(1, n_substeps + 1):
                    frac = step / float(n_substeps)
                    x_sub = x_start + frac * (x_end - x_start)
                    t_sub = t_curr + frac * t_pass
                    txt_lines.append(f"{t_sub:.3f} {x_sub/1000.0:.5f} {y_center_mm/1000.0:.5f} {z_curr_mm/1000.0:.5f} 1")

                t_curr += t_pass

                if t_dwell > 0:
                    gcode_lines.append(f"G4 P{int(t_dwell * 1000)} ; Inter-pass dwell ({t_dwell:.1f}s)")
                    t_curr += t_dwell
                    txt_lines.append(f"{t_curr:.3f} {x_end/1000.0:.5f} {y_center_mm/1000.0:.5f} {z_curr_mm/1000.0:.5f} 0")
                
                gcode_lines.append("")

            gcode_lines.append("M5 ; Arc OFF")
            gcode_lines.append(f"G0 Z{z_curr_mm + 25.0:.3f} F{rapid_mmpm:.0f} ; Safe Retract")
            gcode_lines.append("; End of WAAM G-code")

            gcode_text = "\n".join(gcode_lines) + "\n"
            tp_text = f"{len(txt_lines)}\n" + "\n".join(txt_lines) + "\n"
            lt_lines = [f"{len(layer_pass_times)}"] + [f"{i+1} {pt:.6f}" for i, pt in enumerate(layer_pass_times)]
            lt_text = "\n".join(lt_lines) + "\n"

            for d in set(target_dirs):
                try:
                    os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d, "toolpath.gcode"), "w", encoding="utf-8") as f:
                        f.write(gcode_text)
                    with open(os.path.join(d, "toolpath.txt"), "w", encoding="utf-8") as f:
                        f.write(tp_text)
                    with open(os.path.join(d, "layer_pass_times.txt"), "w", encoding="utf-8") as f:
                        f.write(lt_text)
                except Exception:
                    pass

            return True
        except Exception as e:
            print(f"[GUI] Auto-update wall G-code warning: {e}")
            return False

    def _build_process_tab(self):
        from gui.tabs.process_tab import build_process_tab
        return build_process_tab(self)

    def _update_source_params(self):
        from gui.tabs.process_tab import update_source_params
        return update_source_params(self)

    def _build_material_tab(self):
        from gui.tabs.material_tab import build_material_tab
        return build_material_tab(self)

    def _update_material_wire_readout(self):
        """Update live wire feedstock cross section, mass deposition, and bead continuity readout."""
        if not hasattr(self, "material_feed_info"):
            return
        try:
            dep_key = self.material_dep_var.get() if hasattr(self, "material_dep_var") else "SS308L"
            mat_dep = self.materials.get(dep_key, {})
            rho_val = float(mat_dep.get("density", 7850.0))
            if "rho" in self._param_vars:
                try:
                    rho_val = float(self._param_vars["rho"][0].get())
                except Exception:
                    pass

            d_w_val = float(self._param_vars["d_wire"][0].get()) if "d_wire" in self._param_vars else 1.2
            d_w_mm = d_w_val * 1000.0 if d_w_val < 0.05 else d_w_val

            wfs_val = float(self._param_vars["v_wire"][0].get()) if "v_wire" in self._param_vars else 5.0
            v_scan_val = float(self._param_vars["v_scan"][0].get()) if "v_scan" in self._param_vars else 8.0
            v_scan_mms = v_scan_val * 1000.0 if v_scan_val < 0.05 else v_scan_val

            a_wire_mm2 = (math.pi * (d_w_mm ** 2)) / 4.0
            q_wire_mm3_min = a_wire_mm2 * (wfs_val * 1000.0)
            q_wire_cm3_s = q_wire_mm3_min / 60000.0
            m_dep_kg_h = (q_wire_mm3_min * (rho_val * 1e-9)) * 60.0
            m_dep_g_s = (m_dep_kg_h * 1000.0) / 3600.0

            v_travel_mm_min = v_scan_mms * 60.0
            a_bead_theo_mm2 = (q_wire_mm3_min / v_travel_mm_min) if v_travel_mm_min > 0 else 0.0

            w_bead = float(self._param_vars["ty_dep"][0].get()) if "ty_dep" in self._param_vars else 8.0
            w_bead_mm = w_bead * 1000.0 if w_bead < 0.05 else w_bead
            h_bead = float(self._param_vars["h_bead"][0].get()) if "h_bead" in self._param_vars else 3.0
            h_bead_mm = h_bead * 1000.0 if h_bead < 0.05 else h_bead
            a_bead_cad_mm2 = w_bead_mm * h_bead_mm

            txt = (
                f"• Feedstock Wire:  ∅ {d_w_mm:.2f} mm | Aw = {a_wire_mm2:.3f} mm² | Vol Feed: {q_wire_cm3_s:.3f} cm³/s\n"
                f"• Mass Deposition: ṁ = {m_dep_kg_h:.2f} kg/h ({m_dep_g_s:.2f} g/s) [{dep_key}, ρ={rho_val:.0f} kg/m³]\n"
                f"• Bead Continuity: A_theo = {a_bead_theo_mm2:.2f} mm² vs CAD = {a_bead_cad_mm2:.2f} mm² (w={w_bead_mm:.1f}mm, h={h_bead_mm:.1f}mm)"
            )
            self.material_feed_info.config(text=txt)
        except Exception:
            pass

    def _on_multi_material_change(self, event=None):
        base_key = self.material_base_var.get()
        dep_key = self.material_dep_var.get()

        mat_base = self.materials.get(base_key, {})
        mat_dep = self.materials.get(dep_key, {})

        def get_cte(m):
            te = m.get("thermal_expansion", {}).get("alpha", [1.2e-5])
            return te[0] if te else 1.2e-5

        def get_k(m):
            cd = m.get("conductivity", {}).get("k", [30.0])
            return cd[0] if cd else 30.0

        alpha_b = get_cte(mat_base)
        alpha_d = get_cte(mat_dep)
        delta_alpha = (alpha_d - alpha_b) * 1e6

        k_b = get_k(mat_base)
        k_d = get_k(mat_dep)

        tliq_b = mat_base.get("liquidus", 1520)
        tliq_d = mat_dep.get("liquidus", 1440)
        delta_tliq = tliq_d - tliq_b

        is_dissimilar = (base_key != dep_key)
        if is_dissimilar:
            if abs(delta_alpha) >= 4.0:
                risk_status = f"[WARN] HIGH CTE MISMATCH (Δα = {delta_alpha:+.2f}×10⁻⁶/K)\n   Severe interfacial shear & delamination risk upon cooling!"
            elif abs(delta_alpha) >= 2.0:
                risk_status = f"MODERATE CTE MISMATCH (Δα = {delta_alpha:+.2f}×10⁻⁶/K)\n   Interface thermal stress will produce pronounced bimetallic bending."
            else:
                risk_status = f"[OK] LOW CTE MISMATCH (Δα = {delta_alpha:+.2f}×10⁻⁶/K)\n   Excellent thermomechanical compatibility at the fusion boundary."
        else:
            risk_status = "[OK] MONOLITHIC PRINTING (Substrate and Deposit are identical alloy)"

        info = (
            f"Substrate: {mat_base.get('name', base_key)} [α={alpha_b*1e6:.1f}×10⁻⁶/K, k={k_b:.1f}W/mK, Tliq={tliq_b}°C]\n"
            f"Deposit:   {mat_dep.get('name', dep_key)} [α={alpha_d*1e6:.1f}×10⁻⁶/K, k={k_d:.1f}W/mK, Tliq={tliq_d}°C]\n"
            f"Differential: Δα={delta_alpha:+.2f}×10⁻⁶/K | ΔTliq={delta_tliq:+.0f}°C | k_sub/k_dep={k_b/max(k_d, 0.1):.2f}\n"
            f"{risk_status}"
        )

        self.dissimilar_info.config(state=tk.NORMAL)
        self.dissimilar_info.delete("1.0", tk.END)
        self.dissimilar_info.insert("1.0", info)
        self.dissimilar_info.config(state=tk.DISABLED)

        # Update deposit overrides
        if mat_dep:
            for k in ["rho", "T_sol", "T_liq", "latent_heat", "emissivity"]:
                val = mat_dep.get("density" if k == "rho" else ("solidus" if k == "T_sol" else ("liquidus" if k == "T_liq" else k)))
                if val is not None and k in self._param_vars:
                    self._param_vars[k][0].set(str(val))
            std_wire = mat_dep.get("wire_diameter_default_mm")
            if std_wire and "d_wire" in self._param_vars:
                cur_dw = self._param_vars["d_wire"][0].get().strip()
                if cur_dw in ("", "1.2", "1.20"):
                    self._param_vars["d_wire"][0].set(str(std_wire))
        self._update_material_wire_readout()

    def _build_mesh_cad_tab(self):
        from gui.tabs.mesh_cad_tab import build_mesh_cad_tab
        return build_mesh_cad_tab(self)

    def _on_discretize_mode_change(self):
        """Switch between the 3 mutually exclusive discretization modes (OR button)."""
        m = self.mesh_discretize_mode_var.get()
        if m == "auto_rule":
            self.mode_auto_frame.pack(fill=tk.X, pady=2)
            self.mode_size_frame.pack_forget()
            self.mode_counts_frame.pack_forget()
        elif m == "by_size":
            self.mode_size_frame.pack(fill=tk.X, pady=2)
            self.mode_auto_frame.pack_forget()
            self.mode_counts_frame.pack_forget()
        else:  # by_counts
            self.mode_counts_frame.pack(fill=tk.X, pady=2)
            self.mode_auto_frame.pack_forget()
            self.mode_size_frame.pack_forget()

    def _load_sample_cad(self, filepath: str):
        """Quickly load workspace CAD file sample."""
        if os.path.exists(filepath):
            self._handle_cad_stl_selected(filepath, auto_mesh=False)
        else:
            alt_path = str(Path.home() / "Desktop" / os.path.basename(filepath))
            if os.path.exists(alt_path):
                self._handle_cad_stl_selected(alt_path, auto_mesh=False)
            else:
                messagebox.showwarning("File Not Found", f"Sample CAD file was not found at:\n{filepath}\n\nPlease click 'Browse CAD...' to select your model.")

    def _auto_enforce_node_budget(self):
        """Intelligently calculates mesh divisions or meshes loaded CAD file based on geometry rules."""
        try:
            target = int(self.mesh_budget_var.get())
        except Exception:
            target = 2500

        strategy = getattr(self, "mesh_strategy_var", tk.StringVar(value="physics_adaptive")).get()

        mesh_src = self.mesh_source_var.get()
        cad_path = getattr(self, "loaded_stl_path", "") or self.mesh_file_var.get().strip()
        if mesh_src == "cad_file" and cad_path and os.path.exists(cad_path):
            if cad_path.lower().endswith(".mesh") and hasattr(self, "loaded_stl_path") and self.loaded_stl_path and os.path.exists(self.loaded_stl_path):
                cad_path = self.loaded_stl_path
            self._start_stl_meshing_thread(cad_path)
            return

        try:
            from mesh.intelligent_mesher import calculate_intelligent_structured_mesh
            m = calculate_intelligent_structured_mesh(self._collect_params(), target_nodes=target, strategy=strategy)
            self._param_vars["nx_dep"][0].set(str(m["nx_dep"]))
            self._param_vars["ny_dep"][0].set(str(m["ny_dep"]))
            self._param_vars["nz_dep"][0].set(str(m["nz_dep"]))
            self._param_vars["nx_base"][0].set(str(m["nx_base"]))
            self._param_vars["ny_base"][0].set(str(m["ny_base"]))
            self._param_vars["nz_base"][0].set(str(m["nz_base"]))

            # Update element sizes accordingly
            lx_mm = self._get_dim_mm("lx", 150.0)
            ty_dep_mm = self._get_dim_mm("ty_dep", 5.0)
            h_bead_mm = self._get_dim_mm("h_bead", 3.0)
            nl = max(int(float(self._param_vars.get("n_layers", (None,))[0].get().strip() or "1")), 1)
            remelt = self._f(self._param_vars.get("remelt_ratio", (None,))[0], 0.8)
            hz_dep_mm = h_bead_mm if nl <= 1 else (h_bead_mm + (nl - 1) * h_bead_mm * remelt)

            self.target_dx_var.set(f"{lx_mm / max(m['nx_dep'], 1):.2f}")
            self.target_dy_var.set(f"{ty_dep_mm / max(m['ny_dep'], 1):.2f}")
            self.target_dz_var.set(f"{hz_dep_mm / max(m['nz_dep'], 1):.2f}")

            self._update_mesh_calc()
            self._log(
                f"[AUTO-MESH] Applied {strategy.replace('_', ' ').title()} rule:\n"
                f"[AUTO-MESH] Target budget: ~{target} nodes -> Actual: {m['total_nodes']:,} nodes | {m['total_tets']:,} tets\n"
                f"[AUTO-MESH] Deposit Divisions: Nx={m['nx_dep']}, Ny={m['ny_dep']}, Nz={m['nz_dep']} ({m['nz_dep']/nl:.1f} cells/layer, AR = {m['aspect_ratio_dep']:.2f})\n"
                f"[AUTO-MESH] Substrate Divisions: Nx={m['nx_base']}, Ny={m['ny_base']}, Nz={m['nz_base']} (AR = {m['aspect_ratio_base']:.2f})\n"
            )
            self.status_var.set(f"Status: Auto-Mesh ({m['total_nodes']:,} nodes, AR={m['aspect_ratio_dep']:.2f})")
        except Exception as e:
            messagebox.showerror("Auto-Mesh Error", str(e))

    def _open_3d_mesh_viewer(self):
        """Switch to the dedicated 3D Slicer & Twin Viewport tab."""
        try:
            if hasattr(self, "viewport_tab"):
                self._ensure_viewport_loaded()
                self.notebook.select(self.viewport_tab)
                if hasattr(self, "slicer_widget") and self.slicer_widget:
                    mesh_p = getattr(self, "loaded_mesh_path", "") or self.mesh_file_var.get().strip()
                    if mesh_p and os.path.isfile(mesh_p) and hasattr(self.slicer_widget, "load_fea_mesh"):
                        self.slicer_widget.load_fea_mesh(mesh_p, auto_switch=True)
                    elif hasattr(self.slicer_widget, "_refresh_orient_view"):
                        self.slicer_widget._refresh_orient_view()
                elif hasattr(self, "_refresh_embedded_viewport"):
                    self._refresh_embedded_viewport()
        except Exception as e:
            self._log(f"[3D VIEWER] Error: {e}\n")

    def _open_pyvista_window(self):
        """Launch the standalone hardware-accelerated PyVista GPU 3D window."""
        try:
            from gui.widgets.mesh_viewer_3d import launch_pyvista_gpu_window
            params = self._collect_params()
            launch_pyvista_gpu_window(params)
            self._log("[3D MESH] [OK] Launched native PyVista GPU 3D viewport window.\n")
        except Exception as e:
            self._log(f"[3D MESH] [ERROR] Could not launch PyVista window: {e}\n")
            messagebox.showerror("PyVista GPU Error", str(e))

    def _get_dim_mm(self, key: str, default: float = 0.0) -> float:
        """Helper to get dimension parameter in millimeters."""
        if not hasattr(self, "_param_vars") or key not in self._param_vars:
            return float(default)
        try:
            val = float(self._param_vars[key][0].get().strip() or default)
            return val if val > 0.05 else val * 1000.0
        except Exception:
            return float(default)

    def _apply_element_size_to_divisions(self):
        """Calculate Nx, Ny, Nz from target element sizes dx, dy, dz using axis loops."""
        try:
            lx_mm = self._get_dim_mm("lx", 150.0)
            ty_dep_mm = self._get_dim_mm("ty_dep", 5.0)
            h_bead_mm = self._get_dim_mm("h_bead", 3.0)
            nl = max(int(float(self._param_vars.get("n_layers", (None,))[0].get().strip() or "1")), 1)
            remelt = self._f(self._param_vars.get("remelt_ratio", (None,))[0], 0.8)
            hz_dep_mm = h_bead_mm if nl <= 1 else (h_bead_mm + (nl - 1) * h_bead_mm * remelt)

            dx_dep_mm = max(float(self.target_dx_var.get().strip() or "4.0"), 0.1)
            dy_dep_mm = max(float(self.target_dy_var.get().strip() or "1.33"), 0.1)
            dz_dep_mm = max(float(self.target_dz_var.get().strip() or "1.5"), 0.1)

            # Loop over deposit axes (Enforcing >= 2 cells per layer in Z)
            deposit_axes = [
                ("x", lx_mm, dx_dep_mm, "nx_dep", 2),
                ("y", ty_dep_mm, dy_dep_mm, "ny_dep", 2),
                ("z", hz_dep_mm, dz_dep_mm, "nz_dep", 2 * nl),
            ]
            for axis, length, elem_size, key, min_div in deposit_axes:
                n = max(int(round(length / elem_size)), min_div)
                if key in self._param_vars:
                    self._param_vars[key][0].set(str(n))

            # Substrate axes
            ly_base_mm = self._get_dim_mm("ly_base", 150.0)
            hz_base_mm = self._get_dim_mm("hz_base", 5.0)
            dx_base_mm = max(float(self.base_dx_var.get().strip() or "5.0"), 0.1)
            dy_base_mm = max(float(self.base_dy_var.get().strip() or "7.5"), 0.1)
            dz_base_mm = max(float(self.base_dz_var.get().strip() or "1.0"), 0.1)

            substrate_axes = [
                ("x", lx_mm, dx_base_mm, "nx_base", 2),
                ("y", ly_base_mm, dy_base_mm, "ny_base", 4),
                ("z", hz_base_mm, dz_base_mm, "nz_base", 2),
            ]
            for axis, length, elem_size, key, min_div in substrate_axes:
                n = max(int(round(length / elem_size)), min_div)
                if key in self._param_vars:
                    self._param_vars[key][0].set(str(n))

            self._update_mesh_calc()
            self._log(f"[MESH] Element sizes applied via axis loops -> Nx_dep={self._param_vars['nx_dep'][0].get()}, Ny_dep={self._param_vars['ny_dep'][0].get()}, Nz_dep={self._param_vars['nz_dep'][0].get()} (≥2 cells/layer enforced)\n")
        except Exception as e:
            messagebox.showerror("Mesh Sizing Error", str(e))

    def _apply_division_counts_to_sizes(self):
        """Calculate element sizes dx, dy, dz from division counts Nx, Ny, Nz using axis loops."""
        try:
            lx_mm = self._get_dim_mm("lx", 150.0)
            ty_dep_mm = self._get_dim_mm("ty_dep", 5.0)
            h_bead_mm = self._get_dim_mm("h_bead", 3.0)
            nl = max(int(float(self._param_vars.get("n_layers", (None,))[0].get().strip() or "1")), 1)
            remelt = self._f(self._param_vars.get("remelt_ratio", (None,))[0], 0.8)
            hz_dep_mm = h_bead_mm if nl <= 1 else (h_bead_mm + (nl - 1) * h_bead_mm * remelt)

            deposit_axes = [
                ("x", lx_mm, "nx_dep", self.target_dx_var),
                ("y", ty_dep_mm, "ny_dep", self.target_dy_var),
                ("z", hz_dep_mm, "nz_dep", self.target_dz_var),
            ]
            for axis, length, key, var in deposit_axes:
                n = max(int(float(self._param_vars[key][0].get().strip() or "1")), 1)
                d = length / n
                var.set(f"{d:.2f}")

            ly_base_mm = self._get_dim_mm("ly_base", 150.0)
            hz_base_mm = self._get_dim_mm("hz_base", 5.0)
            substrate_axes = [
                ("x", lx_mm, "nx_base", self.base_dx_var),
                ("y", ly_base_mm, "ny_base", self.base_dy_var),
                ("z", hz_base_mm, "nz_base", self.base_dz_var),
            ]
            for axis, length, key, var in substrate_axes:
                n = max(int(float(self._param_vars[key][0].get().strip() or "1")), 1)
                d = length / n
                var.set(f"{d:.2f}")

            self._update_mesh_calc()
        except Exception as e:
            messagebox.showerror("Division Counts Error", str(e))

    def _verify_meshing_rules(self) -> dict:
        from gui.controllers.mesh_controller import verify_meshing_rules
        return verify_meshing_rules(self)

    def _auto_fix_mesh_rules(self):
        from gui.controllers.mesh_controller import auto_fix_mesh_rules
        return auto_fix_mesh_rules(self)

    def _generate_waam_mesh(self):
        from gui.controllers.mesh_controller import generate_waam_mesh
        return generate_waam_mesh(self)

    def _update_mesh_calc(self):
        from gui.controllers.mesh_controller import update_mesh_calc
        return update_mesh_calc(self)

    def _update_heat_calc(self):
        from gui.controllers.mesh_controller import update_heat_calc
        return update_heat_calc(self)

    def _update_mesh_ui(self):
        val = self.mesh_source_var.get()
        if hasattr(self, "file_picker_frame"):
            if val == "parametric":
                self.file_picker_frame.grid_remove()
            else:
                self.file_picker_frame.grid()
        if hasattr(self, "mesh_divisions_frame") and isinstance(self.mesh_divisions_frame, (tk.LabelFrame, ttk.LabelFrame)):
            if val == "parametric":
                self.mesh_divisions_frame.config(text="Mesh Division Counts (Nx, Ny, Nz)")
            else:
                self.mesh_divisions_frame.config(text="Mesh Division Counts (Nx, Ny, Nz) — [Parametric Box Mesh Only | Inactive for CAD Tet Mesh]")

    def _browse_mesh_file(self):
        filetypes = [
            ("3D CAD Models", "*.stl *.step *.stp *.iges *.igs *.ply *.obj"),
            ("STL Files", "*.stl"),
            ("STEP / IGES Files", "*.step *.stp *.iges *.igs"),
            ("Mesh & Toolpath Files", "*.mesh *.msh *.gcode *.nc"),
            ("All Files", "*.*")
        ]
        path = filedialog.askopenfilename(
            filetypes=filetypes,
            title="Select 3D CAD or Mesh File",
            initialdir=str(Path.home() / "Desktop")
        )
        if path:
            self._handle_cad_stl_selected(path, auto_mesh=False)

    def _handle_cad_stl_selected(self, path: str, auto_mesh: bool = False):
        from gui.controllers.mesh_controller import handle_cad_stl_selected
        return handle_cad_stl_selected(self, path, auto_mesh)

    def _start_stl_meshing_thread(self, cad_path: str):
        from gui.controllers.mesh_controller import start_stl_meshing_thread
        return start_stl_meshing_thread(self, cad_path)

    def _execute_custom_slicer(self):
        from gui.controllers.mesh_controller import execute_custom_slicer
        return execute_custom_slicer(self)

    def _run_slicer_dialog(self):
        """Legacy slicer dialog forwarding to custom slicer."""
        self._execute_custom_slicer()

    def _build_physics_tab(self):
        from gui.tabs.physics_tab import build_physics_tab
        return build_physics_tab(self)

    def _add_info_btn_to_labelframe(self, lf, command):
        """Place an Info button in the top right corner of a LabelFrame."""
        btn = tk.Button(
            lf, text="ⓘ Info", font=FONT_SMALL_BOLD,
            command=command, padx=6, pady=1,
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
        btn.place(relx=1.0, rely=0.0, anchor="ne", x=-6, y=2)
        self._reg(btn, "button")
        return btn

    def _show_info_dialog(self, title: str, heading: str, text_blocks: list):
        """Generic info dialog generator with rich typography and scrollable text."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("760x640")
        dlg.minsize(680, 500)
        dlg.transient(self.root)
        dlg.grab_set()

        canvas = tk.Canvas(dlg, highlightthickness=0, bg=self.colors["bg_card"])
        scroll = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg=self.colors["bg_card"], padx=18, pady=14)
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        cw = canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        title_lbl = tk.Label(
            frame, text=heading,
            font=FONT_TITLE, fg=self.colors["accent"], bg=self.colors["bg_card"]
        )
        title_lbl.pack(anchor=tk.W, pady=(0, 10))

        for sect_title, body_text in text_blocks:
            card = tk.LabelFrame(
                frame, text=f"  {sect_title}  " if sect_title else "",
                font=FONT_SECTION, fg="#2563eb", bg=self.colors["bg_card"],
                padx=12, pady=8
            )
            card.pack(fill=tk.X, pady=6)
            b = tk.Label(
                card, text=body_text,
                font=FONT_LABEL, fg=self.colors["fg"], bg=self.colors["bg_card"],
                justify=tk.LEFT, wraplength=690
            )
            b.pack(anchor=tk.W, fill=tk.X)

        btn_close = tk.Button(
            frame, text="Close Guide", font=FONT_BTN,
            command=dlg.destroy, padx=14, pady=5, relief=tk.FLAT,
            bg=self.colors["button"], fg=self.colors["button_fg"]
        )
        btn_close.pack(anchor=tk.E, pady=(12, 4))

    def _show_substrate_info(self):
        self._show_info_dialog(
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

    def _show_fusion_info(self):
        self._show_info_dialog(
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

    def _show_process_info(self):
        self._show_info_dialog(
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

    def _show_heat_calc_info(self):
        self._show_info_dialog(
            "Heat Input & Mass Deposition Audit Guide",
            "Real-Time Thermal Audit & Deposition Physics Guide",
            [
                ("1. Real-Time Linear Heat Input (H_in)",
                 "• Formula: H_in = (η · U · I) / v_scan [J/mm].\n"
                 "• Live Readout: Continuously recomputed whenever current, voltage, travel speed, or efficiency changes.\n"
                 "• Standard WAAM Range: 250 - 650 J/mm for steel and nickel alloys; 150 - 350 J/mm for aluminium alloys."),
                ("2. Volumetric Energy Density (E_vol)",
                 "• Formula: E_vol = P_net / (A_bead · v_scan) = P_net / V_dot [J/mm³].\n"
                 "• Quantifies energy concentration delivered per unit volume of deposited metal.\n"
                 "• Excessive E_vol (> 80 J/mm³) causes melt pool sagging, excessive penetration, and loss of bead profile."),
                ("3. Mass Deposition & Theoretical Bead Cross-Section",
                 "• Theoretical Bead Area: A_theo = (π · d_wire² · v_wire) / (4 · v_scan) [mm²].\n"
                 "• Mass Deposition Rate: ṁ = ρ · A_theo · v_scan [kg/h].\n"
                 "• Compares programmed wire feed rate against the geometric bead cross-section (w_bead · h_layer)."),
                ("4. Finite Element Energy Conservation Audit",
                 "• The FreeFEM++ solver integrates the moving volumetric source across 3D element quadrature: ∫∫∫ q(x,y,z,t) dΩ.\n"
                 "• Validates that injected thermal energy strictly equals the programmed arc power P_net within < 0.1% numerical tolerance.")
            ]
        )

    def _show_heatsource_info(self):
        self._show_info_dialog(
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

    def _show_material_info(self):
        self._show_info_dialog(
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

    def _show_properties_info(self):
        self._show_info_dialog(
            "Thermophysical Properties & Boundary Cooling Guide",
            "Temperature-Dependent Properties & Surface Heat Losses Guide",
            [
                ("1. Non-Linear Thermophysical Properties (k, Cp, ρ)",
                 "• Thermal Conductivity k(T): Decreases or increases with temperature; molten metal features higher effective conductivity due to fluid convection.\n"
                 "• Specific Heat Capacity Cp(T): Increases with temperature; incorporates phase transformation enthalpy."),
                ("2. Latent Heat of Fusion & Apparent Heat Capacity Method",
                 "• Solidus & Liquidus: Mushy zone bounded by T_sol and T_liq (e.g. 1402 K and 1457 K for SS316L).\n"
                 "• Enthalpy Integration: ∫[Tsol, Tliq] Cp_eff(T) dT = Cp_base·ΔT + L_f.\n"
                 "• Latent Heat of Fusion L_f: Absorbed during melting, released during solidification, smoothing thermal shock and extending cooling dwell."),
                ("3. Convective & Radiative Surface Losses",
                 "• Convection: q''_conv = h_conv · (T - T_amb) [W/m²]. Typical h_conv = 10 - 25 W/(m²·K).\n"
                 "• Stefan-Boltzmann Radiation: q''_rad = ε · σ_SB · (T⁴ - T_amb⁴) [W/m²], where σ_SB = 5.67e-8 W/(m²·K⁴).\n"
                 "• Emissivity (ε): Typically 0.40 - 0.70 for oxidised metallic surfaces at elevated temperatures. Radiation dominates heat loss above 800 °C.")
            ]
        )

    def _show_mesh_info(self):
        self._show_info_dialog(
            "Mesh Discretization & CAD Slicing Guide",
            "Finite Element Discretization & Conforming Interface Guide",
            [
                ("1. Spatial Resolution in Deposition Zone vs Substrate",
                 "• Melt Pool / HAZ Resolution: Minimum 4 elements across bead width (ny_dep ≥ 4) and at least 1-2 elements per deposited layer (nz_dep ≥ N_layer).\n"
                 "• Substrate Grading: Coarser element discretization in substrate regions far from the fusion line reduces total degrees of freedom (DOF) without compromising accuracy."),
                ("2. Conforming Delaunay Tetrahedral Meshes",
                 "• Shared Interface Nodes: Substrate top surface and Layer 1 bottom surface share identical nodes, guaranteeing displacement continuity u and heat flux conservation across the interface.\n"
                 "• Aspect Ratio Constraint: Element aspect ratios are kept below 5:1 to avoid numerical ill-conditioning in the stiffness matrix K."),
                ("3. Physics-Adaptive Auto-Meshing Engine",
                 "• Measures source dimensions (af, b, c) and adjusts element sizes to guarantee the heat source resolves across at least 3-4 element diameters.\n"
                 "• Prevents spatial source aliasing and unphysical peak temperature spikes.")
            ]
        )

    def _show_interface_info(self):
        self._show_info_dialog(
            "Conforming Deposit/Substrate Interface Guide",
            "Interface Continuity & Boundary Surface Labels Guide",
            [
                ("1. Conforming Interface Topology",
                 "• Deposit and substrate mesh partitions are generated with conforming Delaunay triangulation.\n"
                 "• Eliminates the need for artificial contact penalties or Lagrange multipliers, providing exact traction and heat flux continuity."),
                ("2. Boundary Surface Labeling",
                 "• Label 1: Substrate underside (Z = 0) — carries fixture spring supports and conductive bottom losses.\n"
                 "• Labels 2 & 4: Substrate X-minimum and X-maximum lateral faces.\n"
                 "• Labels 3 & 6: Substrate Y-minimum and Y-maximum lateral faces.\n"
                 "• Label 5: Exposed top surfaces of substrate and newly deposited weld bead — subject to convection and radiation losses.")
            ]
        )

    def _show_physics_info(self):
        self._show_info_dialog(
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

    def _show_thermal_info(self):
        self._show_info_dialog(
            "Thermal Boundary Conditions & Cooling Guide",
            "Inter-Pass Cooling Strategies & Thermal Management Guide",
            [
                ("1. Inter-Pass Dwell Modes",
                 "• Fixed Time Dwell (t_wait): Torch pauses for a constant duration (e.g. 30 - 90 s) after completing each pass.\n"
                 "• Temperature-Controlled Dwell (T_interpass): Torch halts until peak monitored temperature drops below a target threshold (e.g. 150 °C).\n"
                 "• Prevents continuous heat accumulation in tall walls, stabilizing bead geometry and refining grain structure."),
                ("2. Boundary Heat Transfer Coefficients",
                 "• Free Convection: h_conv ≈ 15 W/(m²·K) across vertical and horizontal exposed faces.\n"
                 "• Backing Plate Conduction: High bottom transfer coefficient h_bot (50 - 200 W/(m²·K)) simulates intimate contact with heavy steel/copper welding tables.")
            ]
        )

    def _show_mechanical_info(self):
        self._show_info_dialog(
            "Mechanical Boundary & Fixturing Guide",
            "Fixturing Scheme, Spring Supports & Unclamp Springback Guide",
            [
                ("1. Fixturing Clamping Models",
                 "• Isostatic 3-2-1 Kinematic Support: Restrains rigid-body translations and rotations without imposing artificial thermal over-constraint.\n"
                 "• Distributed Elastic Fixture Springs: Applies distributed vertical spring stiffness Kz (N/m³) and lateral restraint Kxy to the substrate underside, modeling real-world toggle clamps."),
                ("2. Unclamp & Springback Equilibrium Solve",
                 "• During deposition: Clamps remain active (clampActive = 1), restraining bowing distortion.\n"
                 "• Post-cooling: Clamps are released (clampActive = 0) and a secondary non-linear equilibrium solve is performed.\n"
                 "• Yields true unconstrained part distortion, warpage, and permanent residual stress distribution."),
                ("3. Newton-Raphson Solver Controls",
                 "• Maximum equilibrium iterations (typical: 15 - 30).\n"
                 "• Non-linear residual force tolerance (< 1e-4) guarantees strict mechanical force balance.")
            ]
        )

    def _show_solver_info(self):
        self._show_info_dialog(
            "FreeFEM++ Time Integration & Solver Settings Guide",
            "Numerical Discretization, Timestepping & Solver Architecture Guide",
            [
                ("1. Temporal Discretization Scheme (θ-method)",
                 "• θ = 1.0 (Fully Implicit Euler): Unconditionally stable, optimal for non-linear latent heat phase transitions and steep thermal gradients.\n"
                 "• θ = 0.5 (Crank-Nicolson): Second-order accurate in time, suitable when timesteps are tightly resolved."),
                ("2. Multi-Stage Timestepping Strategy",
                 "• Deposition Timestep (Δt_weld): Typically 0.2 - 0.5 s, resolving torch travel speed across finite element lengths.\n"
                 "• Inter-Pass Timestep (Δt_dwell): Typically 2.0 - 10.0 s, capturing cooling decay between layers.\n"
                 "• Final Cooling Timestep (Δt_cool): Progressively larger increments (30 - 120 s) for long cooldown to room temperature."),
                ("3. Adaptive Time Stepping (Fourier Controller)",
                 "• Automatically computes dt based on Fourier diffusion number Fo = α·dt / h_min².\n"
                 "• Enforces Courant-like resolution across the heat source diameter while accelerating dwell and cool phases."),
                ("4. State Checkpointing & Restart",
                 "• Checkpointing can be scheduled per layer or every N steps.\n"
                 "• Saves temperature, plastic strain peeq, stress, and displacement fields to disk, enabling seamless simulation resumption.")
            ]
        )

    def _show_history_output_info(self):
        self._show_info_dialog(
            "History Output (Probe Points & Paths) Guide",
            "Continuous Time-History Extraction & Spatial Profile Probing Guide",
            [
                ("1. Purpose & Abaqus *OUTPUT, HISTORY Equivalence",
                 "• Samples field variables (T, σ_von_mises, σ_xx, σ_yy, σ_zz, ε_p, uz) directly inside the FreeFEM++ finite element solver at true simulation time steps.\n"
                 "• Eliminates post-processing interpolation errors and generates publication-grade 2D time-history plots."),
                ("2. Geometry-Linked Baseplate Center Stations (Xc = Lx/2, Yc = W_sub/2)",
                 "• Station 1 (Z = 0.50 · H_sub): Substrate mid-depth — captures baseplate conductive heat soak and longitudinal bending moment.\n"
                 "• Station 2 (Z = 1.00 · H_sub): Substrate surface / fusion boundary — tracks peak interfacial thermal shock and maximum shear stress τ_xz.\n"
                 "• Station 3 (Z = H_sub + 0.20 · H_build): Lower wall build — evaluates remelting and heat accumulation in early layers.\n"
                 "• Station 4 (Z = H_sub + 0.50 · H_build): Mid wall build — measures quasi-steady-state deposition thermal cycles and cooling rate Δt_8/5.\n"
                 "• Station 5 (Z = H_sub + 1.00 · H_build): Top wall build — captures final layer cooling and free-surface thermal shrinkage."),
                ("3. Spatial Probe Paths (Linear Profile Extraction)",
                 "• Format: x1, y1, z1, x2, y2, z2 (one per line, in mm).\n"
                 "• Default Path: Longitudinal centerline along substrate mid-depth (0, Yc, H_sub/2) → (Lx, Yc, H_sub/2).\n"
                 "• Generates spatial profiles of residual stress and warpage along the weld direction."),
                ("4. Dynamic Auto-Sync with Geometry Window",
                 "• Any modification to baseplate dimensions (Lx, Ly_base, hz_base) or layer build (N_layer, h_bead, remelt_ratio) immediately recalculates probe coordinates.\n"
                 "• Manual edits are preserved and can be restored at any time by clicking 'Reset to Standard Probes'.")
            ]
        )

    def _show_openfoam_info(self):
        self._show_info_dialog(
            "OpenFOAM 2412 Melt Pool Hydrodynamics Guide",
            "beamWeldFoam VOF Fluid Flow & Marangoni Convection Guide",
            [
                ("1. Multiphase Volume of Fluid (VOF) Free Surface Tracking",
                 "• Solves Navier-Stokes equations with phase fraction α (1 = liquid metal, 0 = shielding gas).\n"
                 "• Captures dynamic melt pool geometry, surface depression, droplet impingement, and liquid surface ripple formation."),
                ("2. Marangoni Thermocapillary Convection",
                 "• Surface Shear Stress: τ = (∂γ/∂T) · ∇_s T.\n"
                 "• Outward Flow (∂γ/∂T < 0): Standard pure alloys produce outward fluid circulation, yielding wide, shallow melt pools.\n"
                 "• Inward Flow (∂γ/∂T > 0): Presence of surface-active elements (e.g. sulfur/oxygen) inverts surface tension gradient, driving inward convection and deep finger penetration."),
                ("3. Darcy-Type Porous Flow Damping in Mushy Zone",
                 "• Momentum Sink: S = -[C_mushy · (1 - f_L)² / (f_L³ + ε)] · u.\n"
                 "• Smoothly extinguishes fluid velocity as metal cools through the solidus-liquidus mushy zone.")
            ]
        )

    def _show_ultrasonic_info(self):
        self._show_info_dialog(
            "Ultrasonic-Assisted WAAM (UA-WAAM) Guide",
            "Acoustic Cavitation, Streaming & Grain Refinement Guide",
            [
                ("1. Ultrasonic High-Frequency Acoustic Energy (20 - 40 kHz)",
                 "• Transmits high-intensity acoustic vibration directly into the substrate or molten weld pool during deposition.\n"
                 "• Acoustic power input P_us and horn vibration amplitude A_us induce dynamic alternating stress waves."),
                ("2. Acoustic Cavitation & Equiaxed Grain Refinement",
                 "• Cavitation Bubble Collapse: Generates localized shockwaves (> 1 GPa) and micro-jets that shatter growing columnar dendrite arms.\n"
                 "• Columnar-to-Equiaxed Transition (CET): Promotes heterogeneous nucleation, transforming coarse anisotropic columnar grains into fine, isotropic equiaxed microstructure."),
                ("3. Acoustic Softening & Residual Stress Mitigation",
                 "• Oscillatory stress waves assist dislocation motion past pinning obstacles (Blaha effect).\n"
                 "• Drastically reduces macroscopic yield stress during deposition and relaxes peak residual tensile stresses by 30 - 50%.")
            ]
        )

    def _show_microstructure_info(self):
        self._show_info_dialog(
            "Microstructure Kinetics & Hardness Guide",
            "Solidification Morphology, Phase Transformations & HV Mapping Guide",
            [
                ("1. Solidification Parameters (G, R, Cooling Rate)",
                 "• Thermal Gradient G = |∇T| [K/mm].\n"
                 "• Solidification Growth Velocity R = v_scan · cos(θ) [mm/s].\n"
                 "• Cooling Rate: dT/dt = G · R [K/s].\n"
                 "• G/R Ratio dictates solidification mode (planar → cellular → columnar dendritic → equiaxed)."),
                ("2. Secondary Dendrite Arm Spacing (SDAS)",
                 "• Empirical Power Law: λ_2 = A · (G · R)^(-n).\n"
                 "• Higher cooling rates produce significantly finer dendrite arm spacing, directly improving yield strength and ductility."),
                ("3. Solid-State Phase Transformation Kinetics & Vickers Hardness",
                 "• Austenite decomposition into ferrite, pearlite, bainite, and martensite modeled via Johnson-Mehl-Avrami-Kolmogorov (JMAK) kinetics.\n"
                 "• Vickers Hardness (HV): Evaluated across the build via rule-of-mixtures based on local phase fractions.")
            ]
        )

    def _show_solve_cadence_info(self):
        """Display an engineering guide explaining structural solve cadence and trade-offs."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Structural Solve Cadence & Equilibrium Guide")
        dlg.geometry("760x640")
        dlg.minsize(680, 500)
        dlg.transient(self.root)
        dlg.grab_set()

        canvas = tk.Canvas(dlg, highlightthickness=0, bg=self.colors["bg_card"])
        scroll = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg=self.colors["bg_card"], padx=18, pady=14)
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        cw = canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        title = tk.Label(
            frame, text="Structural Solve Cadence & Equilibrium Guide",
            font=FONT_TITLE, fg=self.colors["accent"], bg=self.colors["bg_card"]
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
            frame, text=intro_text, font=FONT_LABEL, fg=self.colors["fg"],
            bg=self.colors["bg_card"], justify=tk.LEFT, wraplength=690
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
            box = tk.LabelFrame(frame, text=f"  {head}  ", font=FONT_SECTION, bg=self.colors["bg_card"],
                                fg=self.colors["accent2"], padx=12, pady=8)
            box.pack(fill=tk.X, pady=6)
            tk.Label(box, text=body, font=FONT_LABEL, fg=self.colors["fg"],
                     bg=self.colors["bg_card"], justify=tk.LEFT, wraplength=670).pack(anchor=tk.W)

        btn_close = tk.Button(
            frame, text="Close Guide", font=FONT_BTN, bg=self.colors["button"],
            fg=self.colors["button_fg"], command=dlg.destroy, padx=14, pady=5,
            relief=tk.FLAT, bd=0
        )
        btn_close.pack(anchor=tk.E, pady=(12, 4))

    def _get_default_probe_points_text(self):
        """
        Compute standard 5 physical history probe stations at baseplate center (X=Lx/2, Y=Ly/2):
        Station 1: Substrate Mid-Depth (Z = H_sub / 2)
        Station 2: Substrate Surface / Fusion Interface (Z = H_sub)
        Station 3: 20% Wall Build Height (Z = H_sub + 0.20 * H_build)
        Station 4: 50% Wall Build Height (Z = H_sub + 0.50 * H_build)
        Station 5: 100% Wall Build Height (Z = H_sub + 1.00 * H_build)
        """
        try:
            lx_mm = self._f(self._param_vars.get("lx", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "lx" in self._param_vars else 150.0
            ly_mm = self._f(self._param_vars.get("ly_base", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "ly_base" in self._param_vars else 150.0
            hz_sub_mm = self._f(self._param_vars.get("hz_base", (None,))[0], 10.0) if hasattr(self, "_param_vars") and "hz_base" in self._param_vars else 10.0
            
            xc = lx_mm / 2.0
            yc = ly_mm / 2.0
            
            if hasattr(self, "_effective_layer_count"):
                _, _, h_build_mm = self._effective_layer_count()
            else:
                h_build_mm = self._current_build_height_mm() if hasattr(self, "_current_build_height_mm") else 20.0
            
            z1 = hz_sub_mm / 2.0
            z2 = hz_sub_mm
            z3 = hz_sub_mm + 0.20 * h_build_mm
            z4 = hz_sub_mm + 0.50 * h_build_mm
            z5 = hz_sub_mm + 1.00 * h_build_mm
            
            lines = [
                f"{xc:.1f}, {yc:.1f}, {z1:.2f}   # Station 1: Substrate Mid-Depth (0.5 * H_sub)",
                f"{xc:.1f}, {yc:.1f}, {z2:.2f}   # Station 2: Substrate Top Surface / Interface (H_sub)",
                f"{xc:.1f}, {yc:.1f}, {z3:.2f}   # Station 3: Lower Wall Build (H_sub + 0.20 * H_build)",
                f"{xc:.1f}, {yc:.1f}, {z4:.2f}   # Station 4: Mid Wall Build (H_sub + 0.50 * H_build)",
                f"{xc:.1f}, {yc:.1f}, {z5:.2f}   # Station 5: Top Wall Build (H_sub + 1.00 * H_build)",
            ]
            return "\n".join(lines)
        except Exception:
            return (
                "75.0, 75.0, 2.50   # Station 1: Substrate Mid-Depth\n"
                "75.0, 75.0, 5.00   # Station 2: Substrate Surface\n"
                "75.0, 75.0, 7.64   # Station 3: 20% Build Height\n"
                "75.0, 75.0, 11.60  # Station 4: 50% Build Height\n"
                "75.0, 75.0, 18.20  # Station 5: 100% Build Height"
            )

    def _get_default_probe_paths_text(self):
        """
        Compute standard longitudinal centerline probe path at baseplate mid-depth:
        (x1=0, y1=W_sub/2, z1=H_sub/2) -> (x2=Lx, y2=W_sub/2, z2=H_sub/2)
        """
        try:
            lx_mm = self._f(self._param_vars.get("lx", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "lx" in self._param_vars else 150.0
            ly_mm = self._f(self._param_vars.get("ly_base", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "ly_base" in self._param_vars else 150.0
            hz_sub_mm = self._f(self._param_vars.get("hz_base", (None,))[0], 10.0) if hasattr(self, "_param_vars") and "hz_base" in self._param_vars else 10.0
            yc = ly_mm / 2.0
            zc = hz_sub_mm / 2.0
            return f"0.0, {yc:.1f}, {zc:.2f}, {lx_mm:.1f}, {yc:.1f}, {zc:.2f}   # Longitudinal centerline at substrate mid-depth"
        except Exception:
            return "0.0, 75.0, 5.0, 150.0, 75.0, 5.0"

    def _reset_default_probe_points(self):
        """Reset probe points and paths to standard baseplate center and geometry-linked elevation stations."""
        self._user_custom_probes = False
        self._user_custom_paths = False
        if hasattr(self, "probe_points_text"):
            default_txt = self._get_default_probe_points_text()
            self.probe_points_text.delete("1.0", tk.END)
            self.probe_points_text.insert("1.0", default_txt)
        if hasattr(self, "probe_paths_text"):
            path_txt = self._get_default_probe_paths_text()
            self.probe_paths_text.delete("1.0", tk.END)
            self.probe_paths_text.insert("1.0", path_txt)
        self._update_probe_geom_badge()

    def _on_probe_points_user_key(self, event=None):
        self._user_custom_probes = True
        self._update_probe_geom_badge()

    def _on_probe_paths_user_key(self, event=None):
        self._user_custom_paths = True
        self._update_probe_geom_badge()

    def _update_probe_geom_badge(self):
        if not hasattr(self, "probe_geom_badge_lbl"):
            return
        is_custom = getattr(self, "_user_custom_probes", False) or getattr(self, "_user_custom_paths", False)
        if is_custom:
            self.probe_geom_badge_lbl.config(
                text="⚠️ Custom Probe Coordinates Active (click 'Reset' below to re-link to Geometry)",
                fg="#d97706"
            )
        else:
            try:
                lx_mm = self._f(self._param_vars.get("lx", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "lx" in self._param_vars else 150.0
                ly_mm = self._f(self._param_vars.get("ly_base", (None,))[0], 150.0) if hasattr(self, "_param_vars") and "ly_base" in self._param_vars else 150.0
                hz_sub_mm = self._f(self._param_vars.get("hz_base", (None,))[0], 10.0) if hasattr(self, "_param_vars") and "hz_base" in self._param_vars else 10.0
                if hasattr(self, "_effective_layer_count"):
                    _, _, h_build_mm = self._effective_layer_count()
                else:
                    h_build_mm = 20.0
                xc = lx_mm / 2.0
                yc = ly_mm / 2.0
                self.probe_geom_badge_lbl.config(
                    text=f"✓ Auto-Linked to Geometry: Center ({xc:.1f}, {yc:.1f}) mm | H_sub={hz_sub_mm:.1f} mm | H_build={h_build_mm:.2f} mm",
                    fg="#2563eb"
                )
            except Exception:
                self.probe_geom_badge_lbl.config(
                    text="✓ Auto-Linked to Geometry Window Coordinates",
                    fg="#2563eb"
                )

    def _build_solver_tab(self):
        from gui.tabs.solver_tab import build_solver_tab
        return build_solver_tab(self)

    # ============================================================
    # ACTION HANDLERS
    # ============================================================

    def _collect_params(self) -> dict:
        from gui.params_collector import collect_params
        return collect_params(self)

    def _log(self, msg: str):
        if not hasattr(self, "console"):
            return
        self.console.config(state=tk.NORMAL)
        text = msg if msg.endswith("\n") else msg + "\n"
        s = text.strip()

        # Insert clean line spacing before major phase/layer transitions so lines don't clutter
        is_major_section = (
            s.startswith("--- Layer") or
            "Inter-pass Cooling" in s or
            "FINAL COOLING" in s or
            "MECHANICAL STAGE" in s or
            "[OK] SIMULATION COMPLETED" in s or
            "STARTING WAAM MULTI-PHYSICS SIMULATION" in s
        )
        if is_major_section:
            try:
                prev = self.console.get("end-2c", "end-1c")
                if prev and prev != "\n":
                    self.console.insert(tk.END, "\n")
            except Exception:
                pass

        # Classify syntax highlighting tag
        tag = None
        if "[ERROR]" in text or "[Error]" in text or "Execution failure" in text or "exited with code" in text:
            tag = "error"
        elif "[WARN]" in text or "[WARNING]" in text or "[Warning]" in text:
            tag = "warn"
        elif "[OK]" in text or "SIMULATION COMPLETED" in text or "Normal End" in text or "✓ Status:" in text:
            tag = "ok"
        elif s.startswith("--- Layer") or ("Layer " in s and "Deposition" in s):
            tag = "layer"
        elif "Inter-pass" in s or "FINAL COOLING" in s or "MECHANICAL STAGE" in s:
            tag = "phase"
        elif s.startswith("ws=") or s.startswith("Step:"):
            tag = "step"
        elif any(k in text for k in ("[SUMMARY]", "[PLOTS]", "[PARAVIEW]", "[REPORT]", "[LOG]", "[INFO]", "[SIM]")):
            tag = "info"
        elif s.startswith("•") or s.startswith("  •"):
            tag = "bullet"
        elif s.startswith("=") and len(s) >= 15:
            tag = "banner"
        elif any(s.startswith(p) for p in ("Timestamp:", "Script:", "Case Dir:", "Run Dir:", "FreeFem++:")):
            tag = "dim"

        if tag:
            self.console.insert(tk.END, text, tag)
        else:
            self.console.insert(tk.END, text)

        # Respect auto-scroll toggle
        if getattr(self, "console_autoscroll_var", None) is None or self.console_autoscroll_var.get():
            self.console.see(tk.END)

        self.console.config(state=tk.DISABLED)

    def _log_batch(self, lines: list):
        """Batch-insert console lines and throttle progress updates to eliminate UI freezing."""
        if not hasattr(self, "console") or not lines:
            return

        import re
        latest_val = None
        latest_stage = None
        latest_step = None

        for line in lines:
            m_lay = re.search(r"--- Layer\s+(\d+)/(\d+)", line)
            if m_lay:
                cl, tl = int(m_lay.group(1)), int(m_lay.group(2))
                latest_val = int((cl / tl) * 80.0)
                latest_stage = f"Current Phase: Layer {cl} of {tl} (Deposition)"

            m_ws = re.search(r"ws=(\d+).*?Tmax=([\d\.]+)", line)
            if m_ws:
                latest_step = f"Step: {m_ws.group(1)} | Peak Temp: {m_ws.group(2)} °C | Status: Active Arc Melting"

            if "Inter-pass" in line:
                latest_stage = "Current Phase: Inter-Pass Cooling Dwell"
            elif "FINAL COOLING" in line:
                latest_val = 85
                latest_stage = "Current Phase: Final Part Cooling to Room Temp"
            elif "MECHANICAL STAGE" in line:
                latest_val = 95
                latest_stage = "Current Phase: Solving Residual Stress & Distortion"
            elif "DONE" in line or "Normal End" in line:
                latest_val = 100
                latest_stage = "Current Phase: Simulation Complete! [OK]"
                latest_step = "Status: Finished. Ready for ParaView visualization."

        if latest_val is not None and latest_val != getattr(self, "_last_progress_val", -1):
            self._last_progress_val = latest_val
            if hasattr(self, "progress_bar"):
                self.progress_bar.configure(value=latest_val)
        if latest_stage is not None and latest_stage != getattr(self, "_last_stage_text", ""):
            self._last_stage_text = latest_stage
            if hasattr(self, "stage_label"):
                self.stage_label.configure(text=latest_stage)
        if latest_step is not None and latest_step != getattr(self, "_last_step_text", ""):
            self._last_step_text = latest_step
            if hasattr(self, "step_detail_label"):
                self.step_detail_label.configure(text=latest_step)

        self.console.config(state=tk.NORMAL)

        # Capped buffer: prevent Tkinter exponential slowdown on long multi-thousand-step runs
        try:
            line_count = int(float(self.console.index("end-1c")))
            if line_count > 6000:
                self.console.delete("1.0", f"{line_count - 4500}.0")
        except Exception:
            pass

        # Group contiguous lines having identical tags to minimize widget operations
        chunks = []
        for msg in lines:
            text = msg if msg.endswith("\n") else msg + "\n"
            s = text.strip()

            is_major_section = (
                s.startswith("--- Layer") or
                "Inter-pass Cooling" in s or
                "FINAL COOLING" in s or
                "MECHANICAL STAGE" in s or
                "[OK] SIMULATION COMPLETED" in s or
                "STARTING WAAM MULTI-PHYSICS SIMULATION" in s
            )
            if is_major_section and chunks:
                chunks.append(("\n", None))

            tag = None
            if "[ERROR]" in text or "[Error]" in text or "Execution failure" in text or "exited with code" in text or "[SOLVER ERROR" in text:
                tag = "error"
            elif "[WARN]" in text or "[WARNING]" in text or "[Warning]" in text:
                tag = "warn"
            elif "[OK]" in text or "SIMULATION COMPLETED" in text or "Normal End" in text or "✓ Status:" in text or "[AUTO-HEAL] ✓" in text:
                tag = "ok"
            elif s.startswith("--- Layer") or ("Layer " in s and "Deposition" in s):
                tag = "layer"
            elif "Inter-pass" in s or "FINAL COOLING" in s or "MECHANICAL STAGE" in s or "[AUTO-HEAL]" in text:
                tag = "phase"
            elif s.startswith("ws=") or s.startswith("Step:"):
                tag = "step"
            elif any(k in text for k in ("[SUMMARY]", "[PLOTS]", "[PARAVIEW]", "[REPORT]", "[LOG]", "[INFO]", "[SIM]", "[PARALLEL]", "[CAD-", "[G-CODE]")):
                tag = "info"
            elif s.startswith("•") or s.startswith("  •"):
                tag = "bullet"
            elif s.startswith("=") and len(s) >= 15:
                tag = "banner"
            elif any(s.startswith(p) for p in ("Timestamp:", "Script:", "Case Dir:", "Run Dir:", "FreeFem++:")):
                tag = "dim"

            if chunks and chunks[-1][1] == tag:
                chunks[-1] = (chunks[-1][0] + text, tag)
            else:
                chunks.append((text, tag))

        for chunk_text, tag in chunks:
            if tag:
                self.console.insert(tk.END, chunk_text, tag)
            else:
                self.console.insert(tk.END, chunk_text)

        if getattr(self, "console_autoscroll_var", None) is None or self.console_autoscroll_var.get():
            self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

    def _get_base_output_dir(self) -> str:
        """Get the root waam_output directory configured in the UI (always inside WAAM-Framework/waam_output)."""
        _framework_dir = Path(__file__).resolve().parent.parent
        default_out = (_framework_dir / "waam_output").resolve()
        base = self._param_vars.get("output_dir", (tk.StringVar(value=str(default_out)),))[0].get()
        if not base or not base.strip() or base in ("./waam_output", "./waam_output/", "waam_output", "waam_output/"):
            base = str(default_out)
        p = Path(base)
        if not p.is_absolute():
            p = (_framework_dir / base).resolve()
        else:
            p = p.resolve()
        # If pointing to outer workspace /Users/.../Desktop/WAAM/waam_output, redirect to WAAM-Framework/waam_output
        if str(p) == str(_framework_dir.parent / "waam_output"):
            p = default_out
        if re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", p.name):
            base = str(p.parent)
        else:
            base = str(p)
        return os.path.abspath(base)

    def _get_or_create_run_dir(self, is_new_run: bool = False) -> str:
        """
        Manage timestamped run directory inside waam_output/.
        - When EDP script is generated: creates or reuses active timestamped folder.
        - Until a new run simulation is clicked, does not create and redirect to a new folder.
        - When a new run simulation is clicked (and previous run was already executed), creates a new timestamped folder.
        """
        import datetime
        base_dir = self._get_base_output_dir()
        os.makedirs(base_dir, exist_ok=True)

        if self.active_run_dir is None or (is_new_run and self.active_run_executed):
            now_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            run_dir = os.path.join(base_dir, now_str)
            os.makedirs(run_dir, exist_ok=True)
            os.makedirs(os.path.join(run_dir, "FreeFEM", "visual_outputs"), exist_ok=True)
            os.makedirs(os.path.join(run_dir, "openfoam"), exist_ok=True)
            self.active_run_dir = os.path.abspath(run_dir)
            self.active_run_executed = False
            return self.active_run_dir

        if not os.path.exists(self.active_run_dir):
            os.makedirs(self.active_run_dir, exist_ok=True)
        fem_vis = os.path.join(self.active_run_dir, "FreeFEM", "visual_outputs")
        if not os.path.exists(fem_vis):
            os.makedirs(fem_vis, exist_ok=True)

        return self.active_run_dir

    @staticmethod
    def _fem_subdir(run_dir: str) -> str:
        """FreeFEM side of a case folder: <run_dir>/FreeFEM/."""
        return os.path.join(run_dir, "FreeFEM")

    def _fem_vis_dir(self, run_dir: str) -> str:
        """Visual outputs of the FreeFEM side (legacy top-level fallback handled by callers)."""
        return os.path.join(self._fem_subdir(run_dir), "visual_outputs")

    def _get_active_or_latest_run_dir(self) -> str:
        """Return active run directory, or scan base output directory for latest timestamped folder."""
        if self.active_run_dir and os.path.exists(self.active_run_dir):
            return self.active_run_dir
        base_dir = self._get_base_output_dir()
        if os.path.exists(base_dir):
            subdirs = [
                os.path.join(base_dir, d) for d in os.listdir(base_dir)
                if os.path.isdir(os.path.join(base_dir, d)) and re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", d)
            ]
            if subdirs:
                subdirs.sort(reverse=True)
                self.active_run_dir = os.path.abspath(subdirs[0])
                return self.active_run_dir
        return base_dir

    def _generate_script(self, is_new_run: bool = False):
        from gui.controllers.simulation_controller import generate_script
        return generate_script(self, is_new_run)

    def _run_simulation(self, is_auto_retry: bool = False):
        from gui.controllers.simulation_controller import run_simulation
        return run_simulation(self, is_auto_retry)

    def _confirm_quit(self):
        """Quit with confirm when a simulation is running."""
        if getattr(self, "running", False):
            if not messagebox.askyesno(
                "Quit",
                "A simulation is running. Quit anyway?\nThe solver process will be stopped.",
            ):
                return
            try:
                self._stop_simulation()
            except Exception:
                pass
        self.root.quit()

    def _stop_simulation(self):
        from gui.controllers.simulation_controller import stop_simulation
        return stop_simulation(self)

    def _open_output(self):
        outdir = self._get_active_or_latest_run_dir()
        open_path_in_file_manager(outdir)

    def _open_report(self):
        from gui.controllers.simulation_controller import open_report
        return open_report(self)

    def _generate_html_report(self, params: dict):
        """Generate a self-contained comprehensive HTML simulation summary report."""
        base = resolve_output_dir(params.get("output_dir"))
        # Route into the FreeFEM side unless the caller already points there.
        outdir = base if os.path.basename(os.path.normpath(base)) == "FreeFEM" else os.path.join(base, "FreeFEM")
        os.makedirs(outdir, exist_ok=True)
        try:
            from core.postprocess.output_manager import generate_enhanced_html_report, generate_run_summary
            summary = generate_run_summary(outdir, params)
            report_path = generate_enhanced_html_report(outdir, params, summary)
            import shutil as _sh
            _sh.copy2(report_path, os.path.join(os.path.dirname(outdir.rstrip('/')), "report.html"))
            return report_path
        except Exception as e:
            self._log(f"[REPORT] Generation note: {e}\n")
            report_path = os.path.join(outdir, "report.html")
            with open(report_path, "w") as f:
                f.write("<!DOCTYPE html><html><body><h1>WAAM Report</h1></body></html>")
            return report_path

    def _save_project(self):
        """Save current parameters to a .waam JSON project file."""
        path = filedialog.asksaveasfilename(
            defaultextension=".waam",
            filetypes=[("WAAM Project", "*.waam"), ("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Save WAAM Project"
        )
        if not path:
            return
        params = self._collect_params()
        import datetime
        params["_project_meta"] = {
            "saved": datetime.datetime.now().isoformat(),
            "framework_version": "2.0",
            "description": "WAAM-Framework project file"
        }
        with open(path, "w") as f:
            json.dump(params, f, indent=2)
        self._log(f"[PROJECT] Saved project to: {path}\n")
        messagebox.showinfo("Project Saved", f"Project saved:\n{path}")

    def _load_project(self):
        """Load a .waam JSON project file and restore all parameters."""
        path = filedialog.askopenfilename(
            filetypes=[("WAAM Project", "*.waam"), ("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Load WAAM Project"
        )
        if not path:
            return
        try:
            with open(path, "r") as f:
                loaded = json.load(f)
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not read project file:\n{e}")
            return

        # Restore numeric params
        for key, (var, type_) in self._param_vars.items():
            if key not in loaded:
                continue
            raw = loaded[key]
            # Convert SI meters back to mm for display keys
            if key in MM_DIMENSION_KEYS and isinstance(raw, (int, float)):
                raw = round(raw * 1000.0, 4)
            elif key in MM_SPEED_KEYS and isinstance(raw, (int, float)):
                raw = round(raw * 1000.0, 4)
            var.set(str(raw))

        # Restore combos and radio buttons
        if "heat_source" in loaded and hasattr(self, "source_var"):
            self.source_var.set(loaded["heat_source"])
            self._update_source_params()
        if "material_base" in loaded and hasattr(self, "material_base_var"):
            self.material_base_var.set(loaded["material_base"])
        if "material_dep" in loaded and hasattr(self, "material_dep_var"):
            self.material_dep_var.set(loaded["material_dep"])
            self._on_multi_material_change()

        self._update_mesh_calc()
        self._update_heat_calc()
        self._log(f"[PROJECT] Loaded project from: {path}\n")
        messagebox.showinfo("Project Loaded", f"Project loaded:\n{path}")

    def _import_stl(self):
        """Import an STL file, update geometry dimensions, and mesh it using Gmsh for FreeFEM."""
        stl_path = filedialog.askopenfilename(
            filetypes=[("STL Files", "*.stl"), ("CAD Files", "*.step *.stp *.iges *.igs"), ("All Files", "*.*")],
            title="Select STL / CAD File for Import & Meshing",
            initialdir=str(Path.home() / "Desktop")
        )
        if not stl_path:
            return
        self._handle_cad_stl_selected(stl_path, auto_mesh=True)


    def _open_paraview(self):
        from gui.controllers.simulation_controller import open_paraview
        return open_paraview(self)

    def _openfoam_dialog(self):
        """Legacy toolbar button handler -- redirects to the OpenFOAM tab generate."""
        self._openfoam_generate_case()

    # The multi-material study directory was created with a transposed
    # letter ("materaial"). The on-disk name is kept so existing checkouts keep
    # working; every reference goes through this constant, and the correctly
    # spelled name is accepted as a fallback.
    CLAUDE_DIR_NAME = "multi_materaial_claude"
    CLAUDE_DIR_NAME_FIXED = "multi_material_claude"

    def _claude_dir(self):
        from gui.dialogs.claude_dialog import get_claude_dir
        return get_claude_dir()

    def _run_claude_simulation(self, preset=1, custom_stdin=None):
        from gui.dialogs.claude_dialog import run_claude_simulation
        return run_claude_simulation(self, preset, custom_stdin)

    def _run_claude_dialog(self):
        from gui.dialogs.claude_dialog import open_claude_dialog
        return open_claude_dialog(self)

    def _open_claude_paraview(self):
        from gui.dialogs.claude_dialog import open_claude_paraview
        return open_claude_paraview(self)

    def _open_claude_output(self):
        from gui.dialogs.claude_dialog import open_claude_output
        return open_claude_output(self)

    # Backward-compatibility aliases
    _run_multi_material_dialog = _run_claude_dialog
    _run_multi_mat_simulation = _run_claude_simulation
    _open_multi_mat_paraview = _open_claude_paraview
    _open_multi_mat_output = _open_claude_output

    def run(self):
        self.root.mainloop()


def main(preset_name=None):
    app = WAAMApp(initial_preset=preset_name)
    app.run()


if __name__ == "__main__":
    main()
