"""Parametric sweep and DOE matrix controller for WAAM Framework."""

import itertools
import os
import re
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from codegen.edp_builder import EDPBuilder


def parse_csv_num_list(text, default_val=10.0):
    try:
        parts = [float(x.strip()) for x in text.split(",") if x.strip()]
        return parts if parts else [default_val]
    except Exception:
        return [default_val]


def generate_doe_matrix(app):
    """Build DOE Cartesian product of all selected sweep dimensions."""
    for row in app.doe_tree.get_children():
        app.doe_tree.delete(row)
    app._doe_queue.clear()

    cur_str = app._param_vars.get("I_weld", (tk.StringVar(value="150.0"), "float"))[0].get() or "150.0"
    spd_str = app._param_vars.get("v_scan", (tk.StringVar(value="10.0"), "float"))[0].get() or "10.0"
    lay_str = app._param_vars.get("n_layers", (tk.StringVar(value="10"), "int"))[0].get() or "10"
    dw_str = app._param_vars.get("d_wire", (tk.StringVar(value="1.2"), "float"))[0].get() or "1.2"

    currents = parse_csv_num_list(app.sweep_i_entry.get(), 150.0) if app.sweep_i_var.get() else [float(cur_str)]
    speeds = parse_csv_num_list(app.sweep_v_entry.get(), 10.0) if app.sweep_v_var.get() else [float(spd_str)]
    us_freqs = parse_csv_num_list(app.sweep_us_entry.get(), 0.0) if app.sweep_us_var.get() else [0.0]
    layers = [int(x) for x in parse_csv_num_list(app.sweep_lay_entry.get(), 10.0)] if app.sweep_lay_var.get() else [int(lay_str)]
    dwires = parse_csv_num_list(app.sweep_dwire_entry.get(), 1.2) if app.sweep_dwire_var.get() else [float(dw_str)]

    run_idx = 1
    for cur, spd, us, lay, dw in itertools.product(currents, speeds, us_freqs, layers, dwires):
        rid = f"DOE_{run_idx:02d}"
        item = {
            "run_id": rid,
            "current": cur,
            "speed": spd,
            "us_freq": us,
            "layers": lay,
            "wire_dia": dw,
            "status": "Ready",
            "tpeak": "-"
        }
        app._doe_queue.append(item)
        app.doe_tree.insert("", tk.END, iid=rid, values=(rid, f"{cur:.1f}", f"{spd:.1f}", f"{us:.1f}", lay, f"{dw:.2f}", "Ready", "-"))
        run_idx += 1

    app.sweep_status_lbl.config(text=f"Queue: {len(app._doe_queue)} runs generated")


def run_parametric_sweep(app):
    """Execute all parameter configurations in the DOE queue sequentially through EDPBuilder."""
    if not app._doe_queue:
        generate_doe_matrix(app)
    if not app._doe_queue:
        return

    def worker():
        from run import find_freefem_serial
        for item in app._doe_queue:
            rid = item["run_id"]
            app.doe_tree.set(rid, "status", "Running...")
            app.sweep_status_lbl.config(text=f"Executing {rid} ({item['current']}A, ∅{item['wire_dia']}mm, {item['layers']}L)...")

            p = app._collect_params()
            p["I_weld"] = float(item["current"])
            p["v_scan"] = float(item["speed"]) / 1000.0 if float(item["speed"]) > 0.05 else float(item["speed"])
            p["ultrasonic_frequency"] = float(item["us_freq"]) * 1000.0 if float(item["us_freq"]) > 0 else 0.0
            p["n_layers"] = int(item["layers"])
            p["num_layers"] = int(item["layers"])
            p["d_wire"] = float(item["wire_dia"]) / 1000.0 if float(item["wire_dia"]) > 0.05 else float(item["wire_dia"])
            p["wire_diameter"] = p["d_wire"]
            p["wire_diameter_mm"] = p["d_wire"] * 1000.0

            builder = EDPBuilder(p)
            run_dir = app._get_or_create_run_dir(is_new_run=True)
            fem_dir = app._fem_subdir(run_dir)
            edp_path = os.path.join(fem_dir, "waam_simulation.edp")
            builder.save(edp_path)

            ff_path = find_freefem_serial() or shutil.which("FreeFem++") or "FreeFem++"
            sim_log = os.path.join(fem_dir, "sim.log")
            from core.platform_adapter import is_windows_solver_path, to_solver_path
            if is_windows_solver_path(ff_path):
                _edp = to_solver_path(edp_path)
                _fem = to_solver_path(fem_dir + "/")
            else:
                _edp, _fem = edp_path, fem_dir + "/"
            with open(sim_log, "w") as lf:
                proc = subprocess.Popen([ff_path, _edp, _fem], stdout=lf, stderr=subprocess.STDOUT)
                proc.wait()

            t_peak = "-"
            try:
                with open(sim_log, "r") as lf:
                    content = lf.read()
                    matches = re.findall(r"Tmax=([\d\.]+)C", content)
                    if matches:
                        t_peak = f"{float(matches[-1]):.1f}"
            except Exception:
                pass

            app.doe_tree.set(rid, "status", "Done")
            app.doe_tree.set(rid, "tpeak", t_peak)

        app.sweep_status_lbl.config(text="Parametric sweep completed!")
        messagebox.showinfo("Sweep Complete", f"Completed all {len(app._doe_queue)} parametric runs successfully.")

    threading.Thread(target=worker, daemon=True).start()
