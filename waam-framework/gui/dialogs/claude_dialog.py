"""Multi-Material Claude simulation runner and custom zone dialog."""

import os
import sys
import shutil
import subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from gui.fonts import (
    FONT_SECTION, FONT_STATUS, FONT_BTN, FONT_SMALL, FONT_SMALL_BOLD, FONT_DLG_TITLE
)
from core.platform_adapter import spawn_isolation_kwargs

CLAUDE_DIR_NAME = "multi_materaial_claude"
CLAUDE_DIR_NAME_FIXED = "multi_material_claude"


def get_claude_dir():
    _here = Path(__file__).resolve().parent.parent.parent
    legacy = _here / CLAUDE_DIR_NAME
    if legacy.exists():
        return legacy
    return _here / CLAUDE_DIR_NAME_FIXED


def run_claude_simulation(app, preset=1, custom_stdin=None):
    """Run the multi-material FreeFEM++ simulation with the specified preset or custom configuration."""
    if app.running:
        messagebox.showwarning("Simulation Running", "A simulation is already in progress. Please stop it first.")
        return

    claude_dir = get_claude_dir()
    main_edp = claude_dir / "main.edp"
    if not main_edp.exists():
        messagebox.showerror("File Not Found", f"Cannot find {main_edp}")
        return

    preset_labels = {
        1: "Default Benchmark (10 Layers, 20 mm Wall)",
        2: "Custom Multi-Material Zone Configuration",
        3: "100 mm Tall Wall Build (50 Layers, 100 mm Wall)"
    }
    lbl = preset_labels.get(preset, f"Preset {preset}")
    app._log(f"\n{'='*65}\nSTARTING MULTI-MATERIAL SIMULATION: {lbl}...\n{'='*65}\n")
    app.running = True
    app.status_var.set("▶ Status: Multi-Material Solving...")
    app.run_btn.config(state=tk.DISABLED)
    app.stop_btn.config(state=tk.NORMAL)

    def thread_fn():
        try:
            from run import find_freefem_serial
            from core.platform_adapter import configure_parallel_environment
            ff_path = find_freefem_serial() or shutil.which("FreeFem++") or "FreeFem++"
            env = configure_parallel_environment()

            run_dir = app._get_or_create_run_dir(is_new_run=True)
            _run_dir = os.path.abspath(run_dir) + "/"
            from core.platform_adapter import is_windows_solver_path, to_solver_path
            if is_windows_solver_path(ff_path):
                _run_dir = to_solver_path(_run_dir)
            cmd = [ff_path, "main.edp", _run_dir]
            app.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(claude_dir),
                env=env,
                bufsize=1,
                **spawn_isolation_kwargs(),
            )

            if preset == 2 and custom_stdin:
                app.process.stdin.write(custom_stdin)
            else:
                app.process.stdin.write(f"{preset}\n")
            app.process.stdin.flush()
            try:
                app.process.stdin.close()
            except Exception:
                pass

            time_prev = time.monotonic()
            time_pending = []

            def _flush_time_ui(force=False):
                nonlocal time_prev
                if not time_pending:
                    return
                if force or time.monotonic() - time_prev >= 0.25:
                    msgs = time_pending[-1:]
                    time_pending.clear()
                    time_prev = time.monotonic()
                    app.root.after(0, lambda: app.stage_label.config(text=msgs[0]))

            def _flush_lines():
                nonlocal pending
                if pending:
                    chunk = "\n".join(pending) + "\n"
                    pending.clear()
                    app.root.after(0, app._log, chunk)

            pending = []
            for line in iter(app.process.stdout.readline, ''):
                if not app.running:
                    break
                line_clean = line.strip()
                if line_clean:
                    pending.append(line_clean)
                    if len(pending) >= 80:
                        _flush_lines()
                if "Layer " in line and "z=[" in line:
                    time_pending.append(line.strip())
                    _flush_time_ui()
                if "Max Released Springback:" in line:
                    time_pending.append(line.strip())
                    _flush_time_ui()
            _flush_lines()
            _flush_time_ui(force=True)

            app.process.stdout.close()
            app.process.wait()

            try:
                from postprocess.plot_generator import generate_all_plots
                plots = generate_all_plots(run_dir)
                app.root.after(0, app._log, f"[PLOTS] Generated {len(plots)} publication-quality plots in: {os.path.join(run_dir, 'plots')}\n")
            except Exception:
                pass
        except Exception as ex:
            app.root.after(0, app._log, f"[ERROR] Multi-Material solver execution failed: {ex}")
        finally:
            app.running = False
            app.root.after(0, lambda: app.status_var.set("● Status: Ready"))
            app.root.after(0, lambda: app.run_btn.config(state=tk.NORMAL))
            app.root.after(0, lambda: app.stop_btn.config(state=tk.DISABLED))
            app.root.after(0, app._log, f"[OK] Multi-Material Simulation Complete.")

    t = threading.Thread(target=thread_fn, daemon=True)
    t.start()


def open_claude_dialog(app):
    """Open detailed custom multi-material configuration dialog with arbitrary zone and layer allocations."""
    dlg = tk.Toplevel(app.root)
    dlg.title("Multi-Material Custom Configuration")
    dlg.geometry("580x680")
    dlg.transient(app.root)
    dlg.grab_set()

    mat_names = ["SS308L", "SS316L", "AL1XXX", "ER70S"]

    # Header
    top_frame = tk.Frame(dlg, padx=16, pady=10)
    top_frame.pack(fill=tk.X)
    tk.Label(top_frame, text="Custom Multi-Material Configuration", font=FONT_DLG_TITLE, fg="#111827").pack(anchor=tk.W)
    tk.Label(top_frame, text="Configure number of materials, total layers, and zone-by-zone layer allocations.", font=FONT_SMALL, fg="#4b5563").pack(anchor=tk.W, pady=(2, 0))

    # Main scrollable canvas container
    canvas = tk.Canvas(dlg, highlightthickness=0)
    scrollbar = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, padx=14, pady=6)

    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Mode Selection
    mode_frame = tk.LabelFrame(scrollable_frame, text="Simulation Mode", font=FONT_SECTION, padx=10, pady=8)
    mode_frame.pack(fill=tk.X, pady=(0, 8))
    if hasattr(app, "_add_info_btn_to_labelframe") and hasattr(app, "_show_default_case_info"):
        app._add_info_btn_to_labelframe(mode_frame, app._show_default_case_info)

    sim_mode_var = tk.IntVar(value=2)

    rb_custom = tk.Radiobutton(mode_frame, text="Custom Multi-Zone Material Architecture", variable=sim_mode_var, value=2, font=FONT_SECTION)
    rb_custom.pack(anchor=tk.W)
    rb_p1 = tk.Radiobutton(mode_frame, text="Preset 1: Default Benchmark (10 Layers: 5x SS308L + 5x SS316L, 20 mm Wall)", variable=sim_mode_var, value=1)
    rb_p1.pack(anchor=tk.W)
    rb_p3 = tk.Radiobutton(mode_frame, text="Preset 3: 100 mm Tall Wall Build (50 Layers: 25x SS308L + 25x SS316L, 100 mm Wall)", variable=sim_mode_var, value=3)
    rb_p3.pack(anchor=tk.W)

    # 1. Substrate (Base Plate) Setup
    sub_frame = tk.LabelFrame(scrollable_frame, text="Substrate (Base Plate) Setup", font=FONT_SECTION, padx=10, pady=8)
    sub_frame.pack(fill=tk.X, pady=(0, 8))
    if hasattr(app, "_add_info_btn_to_labelframe") and hasattr(app, "_show_default_case_info"):
        app._add_info_btn_to_labelframe(sub_frame, app._show_default_case_info)

    sf_grid = tk.Frame(sub_frame)
    sf_grid.pack(fill=tk.X)

    tk.Label(sf_grid, text="Substrate Material:", font=FONT_SMALL_BOLD).grid(row=0, column=0, sticky=tk.W, pady=3)
    sub_mat_combo = ttk.Combobox(sf_grid, values=mat_names, state="readonly", width=14)
    sub_mat_combo.set("SS316L")
    sub_mat_combo.grid(row=0, column=1, sticky=tk.W, padx=6, pady=3)

    tk.Label(sf_grid, text="Length X (mm):", font=FONT_SMALL).grid(row=1, column=0, sticky=tk.W, pady=2)
    lx_entry = ttk.Entry(sf_grid, width=10)
    lx_entry.insert(0, "150.0")
    lx_entry.grid(row=1, column=1, sticky=tk.W, padx=6, pady=2)

    tk.Label(sf_grid, text="Width Y (mm):", font=FONT_SMALL).grid(row=1, column=2, sticky=tk.W, padx=(12, 0), pady=2)
    ly_entry = ttk.Entry(sf_grid, width=10)
    ly_entry.insert(0, "150.0")
    ly_entry.grid(row=1, column=3, sticky=tk.W, padx=6, pady=2)

    tk.Label(sf_grid, text="Thickness Z (mm):", font=FONT_SMALL).grid(row=2, column=0, sticky=tk.W, pady=2)
    hz_entry = ttk.Entry(sf_grid, width=10)
    hz_entry.insert(0, "10.0")
    hz_entry.grid(row=2, column=1, sticky=tk.W, padx=6, pady=2)

    # 2. Deposit Wall Dimensions
    geom_frame = tk.LabelFrame(scrollable_frame, text="Deposit Wall Dimensions", font=FONT_SECTION, padx=10, pady=8)
    geom_frame.pack(fill=tk.X, pady=(0, 8))
    if hasattr(app, "_add_info_btn_to_labelframe") and hasattr(app, "_show_default_case_info"):
        app._add_info_btn_to_labelframe(geom_frame, app._show_default_case_info)

    gf_grid = tk.Frame(geom_frame)
    gf_grid.pack(fill=tk.X)

    tk.Label(gf_grid, text="Single Bead Width Y (mm):", font=FONT_SMALL).grid(row=0, column=0, sticky=tk.W, pady=2)
    ty_entry = ttk.Entry(gf_grid, width=10)
    ty_entry.insert(0, "8.0")
    ty_entry.grid(row=0, column=1, sticky=tk.W, padx=6, pady=2)

    tk.Label(gf_grid, text="Single Layer Height Z (mm):", font=FONT_SMALL).grid(row=0, column=2, sticky=tk.W, padx=(12, 0), pady=2)
    hbead_entry = ttk.Entry(gf_grid, width=10)
    hbead_entry.insert(0, "2.0")
    hbead_entry.grid(row=0, column=3, sticky=tk.W, padx=6, pady=2)

    # 3. Multi-Zone / Multi-Material Allocation
    zones_frame = tk.LabelFrame(scrollable_frame, text="Multi-Zone Material Allocation", font=FONT_SECTION, padx=10, pady=8)
    zones_frame.pack(fill=tk.X, pady=(0, 8))
    if hasattr(app, "_add_info_btn_to_labelframe") and hasattr(app, "_show_default_case_info"):
        app._add_info_btn_to_labelframe(zones_frame, app._show_default_case_info)

    num_zones_row = tk.Frame(zones_frame)
    num_zones_row.pack(fill=tk.X, pady=(0, 6))

    tk.Label(num_zones_row, text="Number of Material Zones (N):", font=FONT_SMALL_BOLD).pack(side=tk.LEFT)
    num_zones_var = tk.IntVar(value=2)
    num_zones_spin = ttk.Spinbox(num_zones_row, from_=1, to=8, width=5, textvariable=num_zones_var)
    num_zones_spin.pack(side=tk.LEFT, padx=8)

    zone_rows_container = tk.Frame(zones_frame)
    zone_rows_container.pack(fill=tk.X, pady=4)

    zone_widgets = []
    summary_label = tk.Label(zones_frame, text="Total Deposited Layers: 50 layers  |  Total Build Height: 100.0 mm", font=FONT_SMALL_BOLD, fg="#1d4ed8")
    summary_label.pack(anchor=tk.W, pady=(6, 2))

    def update_summary(*args):
        tot_layers = 0
        for w in zone_widgets:
            try:
                tot_layers += int(w["cnt_var"].get())
            except ValueError:
                pass
        try:
            hb = float(hbead_entry.get())
        except ValueError:
            hb = 2.0
        tot_h = tot_layers * hb
        summary_label.config(text=f"Total Deposited Layers: {tot_layers} layers  |  Total Build Height: {tot_h:.1f} mm")

    def rebuild_zone_rows():
        for widget in zone_rows_container.winfo_children():
            widget.destroy()
        zone_widgets.clear()

        n = max(1, min(8, num_zones_var.get()))
        default_layers = [25, 25, 20, 20, 15, 15, 10, 10]
        default_mats = ["SS308L", "SS316L", "ER70S", "AL1XXX", "SS308L", "SS316L", "ER70S", "AL1XXX"]

        for i in range(n):
            zr = tk.Frame(zone_rows_container, pady=3)
            zr.pack(fill=tk.X)

            tk.Label(zr, text=f"Zone {i+1}:", font=FONT_SMALL_BOLD, width=8, anchor=tk.W).pack(side=tk.LEFT)

            tk.Label(zr, text="Layers:").pack(side=tk.LEFT, padx=(4, 2))
            cnt_var = tk.StringVar(value=str(default_layers[i] if i < len(default_layers) else 10))
            cnt_var.trace_add("write", update_summary)
            cnt_entry = ttk.Entry(zr, textvariable=cnt_var, width=8)
            cnt_entry.pack(side=tk.LEFT, padx=4)

            tk.Label(zr, text="Material:").pack(side=tk.LEFT, padx=(8, 2))
            mat_var = tk.StringVar(value=default_mats[i] if i < len(default_mats) else "SS308L")
            mat_combo = ttk.Combobox(zr, textvariable=mat_var, values=mat_names, state="readonly", width=12)
            mat_combo.pack(side=tk.LEFT, padx=4)

            zone_widgets.append({
                "cnt_var": cnt_var,
                "cnt_entry": cnt_entry,
                "mat_var": mat_var,
                "mat_combo": mat_combo
            })

        update_summary()

    num_zones_var.trace_add("write", lambda *a: rebuild_zone_rows())
    hbead_entry.bind("<KeyRelease>", update_summary)
    rebuild_zone_rows()

    # 4. Thermal & Process Parameters
    proc_frame = tk.LabelFrame(scrollable_frame, text="Welding & Process Parameters", font=FONT_SECTION, padx=10, pady=8)
    proc_frame.pack(fill=tk.X, pady=(0, 10))
    if hasattr(app, "_add_info_btn_to_labelframe") and hasattr(app, "_show_default_case_info"):
        app._add_info_btn_to_labelframe(proc_frame, app._show_default_case_info)

    pf_grid = tk.Frame(proc_frame)
    pf_grid.pack(fill=tk.X)

    tk.Label(pf_grid, text="Arc Power P (W):", font=FONT_SMALL).grid(row=0, column=0, sticky=tk.W, pady=2)
    power_entry = ttk.Entry(pf_grid, width=10)
    power_entry.insert(0, "2000.0")
    power_entry.grid(row=0, column=1, sticky=tk.W, padx=6, pady=2)

    tk.Label(pf_grid, text="Travel Speed v (mm/s):", font=FONT_SMALL).grid(row=0, column=2, sticky=tk.W, padx=(12, 0), pady=2)
    speed_entry = ttk.Entry(pf_grid, width=10)
    speed_entry.insert(0, "8.0")
    speed_entry.grid(row=0, column=3, sticky=tk.W, padx=6, pady=2)

    tk.Label(pf_grid, text="Inter-Pass Wait (s):", font=FONT_SMALL).grid(row=1, column=0, sticky=tk.W, pady=2)
    wait_entry = ttk.Entry(pf_grid, width=10)
    wait_entry.insert(0, "15.0")
    wait_entry.grid(row=1, column=1, sticky=tk.W, padx=6, pady=2)

    tk.Label(pf_grid, text="Ambient Temp (°C):", font=FONT_SMALL).grid(row=1, column=2, sticky=tk.W, padx=(12, 0), pady=2)
    tamb_entry = ttk.Entry(pf_grid, width=10)
    tamb_entry.insert(0, "25.0")
    tamb_entry.grid(row=1, column=3, sticky=tk.W, padx=6, pady=2)

    # Dialog Buttons
    btn_frame = tk.Frame(dlg, padx=14, pady=10)
    btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

    def on_run():
        chosen_mode = sim_mode_var.get()
        dlg.destroy()
        if chosen_mode == 1:
            app.material_base_var.set("SS316L")
            app.material_dep_var.set("SS308L")
            if hasattr(app, "us_layers_var"):
                app.us_layers_var.set("10")
            app._run_simulation()
            return
        elif chosen_mode == 3:
            if hasattr(app, "us_layers_var"):
                app.us_layers_var.set("50")
            if "lx" in app._param_vars:
                app._param_vars["lx"][0].set("100.0")
            app._run_simulation()
            return

        try:
            sub_mat = sub_mat_combo.get()
            app.material_base_var.set(sub_mat)

            if "lx" in app._param_vars:
                app._param_vars["lx"][0].set(str(float(lx_entry.get())))
            if "ly_base" in app._param_vars:
                app._param_vars["ly_base"][0].set(str(float(ly_entry.get())))
            if "hz_base" in app._param_vars:
                app._param_vars["hz_base"][0].set(str(float(hz_entry.get())))
            if "ty_dep" in app._param_vars:
                app._param_vars["ty_dep"][0].set(str(float(ty_entry.get())))
            if "h_bead" in app._param_vars:
                app._param_vars["h_bead"][0].set(str(float(hbead_entry.get())))
            if "t_wait" in app._param_vars:
                app._param_vars["t_wait"][0].set(str(float(wait_entry.get())))
            if "v_scan" in app._param_vars:
                app._param_vars["v_scan"][0].set(str(float(speed_entry.get())))

            tot_layers = sum(int(zw["cnt_var"].get()) for zw in zone_widgets)
            if hasattr(app, "us_layers_var"):
                app.us_layers_var.set(str(tot_layers))

            app._run_simulation()

        except Exception as ex:
            messagebox.showerror("Input Error", f"Please check numeric fields: {ex}")

    run_btn = tk.Button(
        btn_frame, text="Run Multi-Material Simulation",
        font=FONT_STATUS,
        bg=app.colors["button_primary"], fg=app.colors["button_primary_fg"],
        activebackground=app.colors["button_primary_active"],
        activeforeground=app.colors["button_primary_fg"],
        command=on_run, padx=12, pady=6
    )
    run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

    cancel_btn = tk.Button(
        btn_frame, text="Cancel",
        font=FONT_BTN,
        bg=app.colors["button"], fg=app.colors["button_fg"],
        command=dlg.destroy, padx=12, pady=6
    )
    cancel_btn.pack(side=tk.LEFT)


def open_claude_paraview(app):
    """Open Multi-Material output waam.pvd in ParaView."""
    pvd = get_claude_dir() / "waam_out" / "waam.pvd"
    if not pvd.exists():
        messagebox.showinfo("No Results", f"No waam.pvd found at:\n{pvd}\n\nPlease run the Multi-Material solver first.")
        return

    pv_path = shutil.which("paraview")
    if not pv_path:
        _app = "/Applications/ParaView.app/Contents/MacOS/paraview"
        if os.path.exists(_app):
            pv_path = _app
    if pv_path:
        subprocess.Popen([pv_path, str(pvd)])
        app._log(f"[PARAVIEW] Launched ParaView with: {pvd}")
    else:
        messagebox.showerror("ParaView Not Found", "ParaView binary could not be found.")


def open_claude_output(app):
    """Open the Multi-Material output folder."""
    outdir = get_claude_dir() / "waam_out"
    outdir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(outdir)])
    else:
        subprocess.Popen(["xdg-open", str(outdir)])
