"""Simulation runner, script generation, and postprocessing controller for WAAM Framework."""

import datetime
import glob
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from codegen.edp_builder import EDPBuilder
from core.platform_adapter import (
    build_unbuffered_command,
    kill_process_tree,
    open_url_in_browser,
    open_path_in_file_manager,
    spawn_isolation_kwargs,
)
from run import find_freefem_serial


def safe_copy_file(src, dst):
    try:
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
    except Exception:
        pass


def generate_script(app, is_new_run: bool = False):
    """Generate multi-physics FreeFEM++ EDP script from current parameters."""
    app._batch_updating = True
    try:
        run_dir = app._get_or_create_run_dir(is_new_run=is_new_run)
        fem_dir = app._fem_subdir(run_dir)
        vis_dir = os.path.join(fem_dir, "visual_outputs")
        os.makedirs(vis_dir, exist_ok=True)

        params = app._collect_params()
        params["output_dir"] = fem_dir.rstrip('/') + '/'

        has_custom_cad = bool(
            params.get("stl_file") or
            params.get("mesh_file") or
            (hasattr(app, "mesh_source_var") and app.mesh_source_var.get() in ("cad_file", "gcode_file")) or
            (hasattr(app, "loaded_stl_path") and app.loaded_stl_path)
        )

        if has_custom_cad:
            stl_cand = params.get("stl_file") or getattr(app, "loaded_stl_path", "")
            existing_mesh = params.get("mesh_file") or getattr(app, "loaded_mesh_path", "")
            if not (existing_mesh and os.path.exists(existing_mesh) and existing_mesh.lower().endswith(('.mesh', '.mesh3', '.msh'))):
                if stl_cand:
                    cand_m = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "waam_output", f"imported_{Path(stl_cand).stem}.mesh")
                    if os.path.exists(cand_m):
                        existing_mesh = cand_m

            if existing_mesh and os.path.exists(existing_mesh) and existing_mesh.lower().endswith(('.mesh', '.mesh3', '.msh')):
                params["mesh_source"] = "cad_file"
                from mesh.intelligent_mesher import detect_mesh_substrate_height
                sub_hz_det = detect_mesh_substrate_height(existing_mesh)
                req_sub_hz = float(params.get("hz_base", 0.005)) * 1000.0
                if sub_hz_det is not None and abs(sub_hz_det - req_sub_hz) > 0.5 and stl_cand and os.path.exists(stl_cand):
                    app._log(f"\n[CAD-SIM] Re-meshing {os.path.basename(stl_cand)} with requested substrate plate HzBase = {req_sub_hz:.1f} mm (cached mesh had {sub_hz_det:.1f} mm)...\n")
                    from mesh.stl_pipeline import stl_to_freefem_mesh
                    target_nodes = 2000
                    try:
                        target_nodes = int(app.mesh_budget_var.get())
                    except Exception:
                        pass
                    mesh_out = os.path.join(fem_dir, f"imported_{Path(stl_cand).stem}.mesh")
                    res = stl_to_freefem_mesh(stl_cand, mesh_out, target_nodes=target_nodes, sub_hz_mm=req_sub_hz,
                                             sub_lx_mm=float(params.get("lx", 0.150)) * 1000.0,
                                             sub_ly_mm=float(params.get("ly_base", 0.150)) * 1000.0)
                    existing_mesh = mesh_out
                    sub_hz_det = req_sub_hz
                    app._log(f"[CAD-SIM] Remeshing complete: {res['n_nodes']} nodes, {res['n_tets']} tets -> {mesh_out}\n")
                elif sub_hz_det is not None and sub_hz_det > 0.0:
                    params["hz_base"] = float(sub_hz_det / 1000.0)
                    if hasattr(app, "_param_vars") and "hz_base" in app._param_vars:
                        app._param_vars["hz_base"][0].set(str(round(sub_hz_det, 2)))
                    app._log(f"[CAD-SYNC] Synchronized substrate plate HzBase = {sub_hz_det:.1f} mm with volume mesh.\n")
                mesh_out = os.path.join(fem_dir, os.path.basename(existing_mesh))
                safe_copy_file(existing_mesh, mesh_out)
                from mesh.stl_pipeline import reorient_mesh_boundary_triangles
                n_fixed = reorient_mesh_boundary_triangles(mesh_out)
                if n_fixed > 0:
                    app._log(f"[CAD-HEAL] Reoriented {n_fixed} inverted boundary triangles for FreeFEM compatibility.\n")
                params["mesh_file"] = mesh_out
            elif stl_cand and os.path.exists(stl_cand) and Path(stl_cand).suffix.lower() in ('.stl', '.step', '.stp', '.iges', '.igs', '.ply', '.obj'):
                mesh_out = os.path.join(fem_dir, f"imported_{Path(stl_cand).stem}.mesh")
                if not os.path.exists(mesh_out) or os.path.getmtime(mesh_out) < os.path.getmtime(stl_cand):
                    app._log(f"\n[CAD-SIM] Automatically meshing {os.path.basename(stl_cand)} to FreeFEM volume mesh...\n")
                    from mesh.stl_pipeline import stl_to_freefem_mesh
                    target_nodes = 2000
                    try:
                        target_nodes = int(app.mesh_budget_var.get())
                    except Exception:
                        pass
                    res = stl_to_freefem_mesh(stl_cand, mesh_out, target_nodes=target_nodes, sub_hz_mm=params.get("hz_base", 0.005) * 1000.0,
                                             sub_lx_mm=float(params.get("lx", 0.150)) * 1000.0,
                                             sub_ly_mm=float(params.get("ly_base", 0.150)) * 1000.0)
                    app._log(f"[CAD-SIM] Volume mesh ready: {res['n_nodes']} nodes, {res['n_tets']} tets -> {mesh_out}\n")
                from mesh.stl_pipeline import reorient_mesh_boundary_triangles
                n_fixed = reorient_mesh_boundary_triangles(mesh_out)
                if n_fixed > 0:
                    app._log(f"[CAD-HEAL] Reoriented {n_fixed} inverted boundary triangles for FreeFEM compatibility.\n")
                params["mesh_file"] = mesh_out
                params["mesh_source"] = "cad_file"
                params["stl_file"] = stl_cand

            cad_to_slice = stl_cand if (stl_cand and os.path.exists(stl_cand)) else (existing_mesh if (existing_mesh and os.path.exists(existing_mesh)) else None)
            curr_gc = params.get("gcode_file") or getattr(app, "loaded_gcode_path", "")
            user_gcode = (
                (app.mesh_source_var.get() == "gcode_file"
                 if hasattr(app, "mesh_source_var") else False)
                and bool(curr_gc) and os.path.exists(curr_gc))
            needs_cad_slicing = bool(cad_to_slice) and not user_gcode

            if needs_cad_slicing and cad_to_slice:
                try:
                    from mesh.slicer_api import slice_geometry_to_toolpath
                    h_bead = app._f(app._param_vars.get("h_bead", (None,))[0], 3.0) if hasattr(app, "_param_vars") and "h_bead" in app._param_vars else 3.0
                    w_bead = app._f(app._param_vars.get("ty_dep", (None,))[0], 4.0) if hasattr(app, "_param_vars") and "ty_dep" in app._param_vars else 4.0
                    lx_sub_mm = float(params.get("lx", 0.150)) * 1000.0
                    ly_sub_mm = float(params.get("ly_base", 0.150)) * 1000.0
                    hz_sub_mm = float(params.get("hz_base", 0.005)) * 1000.0
                    s_infill = app.slicer_pattern_var.get() if hasattr(app, "slicer_pattern_var") else "contour"
                    s_perims = int(app.slicer_perim_var.get()) if hasattr(app, "slicer_perim_var") else 3
                    s_overlap = float(app.slicer_overlap_var.get()) if hasattr(app, "slicer_overlap_var") else 75.0
                    s_feedrate = float(app.slicer_feedrate_var.get()) if hasattr(app, "slicer_feedrate_var") else 600.0
                    s_rapid = float(app.slicer_rapid_var.get()) if hasattr(app, "slicer_rapid_var") else 3000.0
                    s_dwell = float(app.slicer_dwell_var.get()) if hasattr(app, "slicer_dwell_var") else 10.0
                    s_power = float(app.slicer_power_var.get()) if hasattr(app, "slicer_power_var") else 3840.0
                    s_rev = bool(app.slicer_reverse_var.get()) if hasattr(app, "slicer_reverse_var") else True

                    app._log(f"\n[CAD-SLICER] Auto-slicing CAD ({os.path.basename(cad_to_slice)}) for multi-physics run (dz={h_bead:.2f} mm, w={w_bead:.2f} mm, infill={s_infill}, walls={s_perims}, plate={lx_sub_mm:.0f}x{ly_sub_mm:.0f}x{hz_sub_mm:.1f} mm)...\n")
                    slice_target_gcode = os.path.join(fem_dir, "toolpath.gcode")
                    s_res = slice_geometry_to_toolpath(
                        geometry_file=cad_to_slice,
                        output_gcode=slice_target_gcode,
                        layer_height=h_bead,
                        bead_width=w_bead,
                        sub_hz=hz_sub_mm,
                        sub_lx_mm=lx_sub_mm,
                        sub_ly_mm=ly_sub_mm,
                        infill_pattern=s_infill,
                        overlap_pct=s_overlap,
                        perimeters=s_perims,
                        feedrate=s_feedrate,
                        rapid_feedrate=s_rapid,
                        power=s_power,
                        dwell_time=s_dwell,
                        start_reverse=s_rev
                    )
                    params["gcode_file"] = slice_target_gcode
                    params["n_layers"] = int(s_res.get("n_layers", params.get("n_layers", 1)))
                    if hasattr(app, "_param_vars") and "n_layers" in app._param_vars:
                        app._param_vars["n_layers"][0].set(str(params["n_layers"]))
                    app._log(f"[CAD-SLICER] Generated toolpath: {params['n_layers']} layers, {s_res.get('n_points', 0)} points.\n")
                    for _w in s_res.get("warnings", []) or []:
                        app._log(f"[CAD-SLICER] [WARNING] {_w}\n")
                except Exception as se:
                    app._log(f"[CAD-SLICER] Warning: automatic CAD slicing failed ({se}), falling back to wall toolpath.\n")

        if not params.get("gcode_file") or params.get("mesh_source", "box_wall") == "box_wall":
            app._auto_update_wall_gcode(run_dir=fem_dir)
            auto_gc = os.path.join(fem_dir, "toolpath.gcode")
            if os.path.exists(auto_gc):
                params["gcode_file"] = auto_gc

        builder = EDPBuilder(params)
        for w in getattr(builder, "warnings", []):
            app._log(f"[ADVISORY] [INFO] {w}\n")

        gc_file = params.get("gcode_file")
        if gc_file and os.path.exists(gc_file):
            gc_dir = os.path.dirname(os.path.abspath(gc_file))
            gc_stem = Path(gc_file).stem
            tp_src = None
            for cand in [os.path.join(gc_dir, "toolpath.txt"), os.path.join(gc_dir, f"{gc_stem}.txt"), os.path.join(run_dir, "toolpath.txt")]:
                if os.path.exists(cand):
                    tp_src = cand
                    break
            lt_src = None
            for cand in [os.path.join(gc_dir, "layer_pass_times.txt"), os.path.join(gc_dir, f"{gc_stem}.layer_times.txt"), os.path.join(run_dir, "layer_pass_times.txt")]:
                if os.path.exists(cand):
                    lt_src = cand
                    break

            for dest_dir in (run_dir, fem_dir):
                safe_copy_file(gc_file, os.path.join(dest_dir, "toolpath.gcode"))
                if os.path.basename(gc_file) != "toolpath.gcode":
                    safe_copy_file(gc_file, os.path.join(dest_dir, os.path.basename(gc_file)))
                if tp_src and os.path.exists(tp_src):
                    safe_copy_file(tp_src, os.path.join(dest_dir, "toolpath.txt"))
                if lt_src and os.path.exists(lt_src):
                    safe_copy_file(lt_src, os.path.join(dest_dir, "layer_pass_times.txt"))

            app._log(f"[FILE SYNC] Synchronized toolpath.gcode, toolpath.txt, and layer_pass_times.txt to run folder: {run_dir}\n")

            # Verify and auto-align toolpath coordinates against simulation substrate
            for dest_dir in (run_dir, fem_dir):
                tp_f = os.path.join(dest_dir, "toolpath.txt")
                if os.path.exists(tp_f):
                    try:
                        with open(tp_f, "r", encoding="utf-8") as f:
                            lines = [line.strip() for line in f if line.strip()]
                        if len(lines) > 1:
                            pts_data = []
                            xs_m, ys_m, zs_m = [], [], []
                            for l in lines[1:]:
                                parts = l.split()
                                if len(parts) >= 5:
                                    t_v, x_v, y_v, z_v, p_v = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), int(parts[4])
                                    pts_data.append((t_v, x_v, y_v, z_v, p_v))
                                    if p_v == 1:
                                        xs_m.append(x_v)
                                        ys_m.append(y_v)
                                    zs_m.append(z_v)
                            if not xs_m and pts_data:
                                xs_m = [p[1] for p in pts_data]
                                ys_m = [p[2] for p in pts_data]

                            sub_lx_m = float(params.get("lx", 0.150))
                            if sub_lx_m > 10.0: sub_lx_m /= 1000.0
                            sub_ly_m = float(params.get("ly_base", 0.150))
                            if sub_ly_m > 10.0: sub_ly_m /= 1000.0
                            sub_hz_m = float(params.get("hz_base", 0.005))
                            if sub_hz_m > 1.0: sub_hz_m /= 1000.0

                            target_cx_m = sub_lx_m / 2.0
                            target_cy_m = sub_ly_m / 2.0

                            if xs_m and ys_m and zs_m:
                                cx_m = (min(xs_m) + max(xs_m)) / 2.0
                                cy_m = (min(ys_m) + max(ys_m)) / 2.0
                                min_z_m = min(zs_m)

                                shift_x_m = 0.0
                                shift_y_m = 0.0
                                shift_z_m = 0.0
                                # If toolpath is offset from substrate center by > 5 mm
                                if abs(cx_m - target_cx_m) > 0.005 or abs(cy_m - target_cy_m) > 0.005:
                                    shift_x_m = target_cx_m - cx_m
                                    shift_y_m = target_cy_m - cy_m
                                # If toolpath was sliced starting from z=0 rather than resting on top of substrate
                                if min_z_m < sub_hz_m * 0.7:
                                    shift_z_m = sub_hz_m

                                if abs(shift_x_m) > 1e-6 or abs(shift_y_m) > 1e-6 or abs(shift_z_m) > 1e-6:
                                    aligned_lines = [f"{len(pts_data)}"]
                                    for t_v, x_v, y_v, z_v, p_v in pts_data:
                                        x_adj = (x_v + shift_x_m) if (x_v > 1e-6 or p_v == 1) else x_v
                                        y_adj = (y_v + shift_y_m) if (y_v > 1e-6 or p_v == 1) else y_v
                                        z_adj = z_v + shift_z_m
                                        aligned_lines.append(f"{t_v:.3f} {x_adj:.5f} {y_adj:.5f} {z_adj:.5f} {p_v}")
                                    with open(tp_f, "w", encoding="utf-8") as f:
                                        f.write("\n".join(aligned_lines) + "\n")
                                    if dest_dir == fem_dir:
                                        app._log(f"[AUTO-ALIGN] Synchronized toolpath.txt to substrate plate: shift=({shift_x_m*1000:+.1f}, {shift_y_m*1000:+.1f}, {shift_z_m*1000:+.1f}) mm (substrate center: {target_cx_m*1000:.1f}, {target_cy_m*1000:.1f} mm, hz_base: {sub_hz_m*1000:.1f} mm)\n")
                    except Exception as _e_align:
                        app._log(f"[WARN] Toolpath auto-align check: {_e_align}\n")

        for key in ["stl_file", "mesh_file"]:
            fpath = params.get(key)
            if fpath and os.path.exists(fpath) and os.path.isfile(fpath):
                for dest_dir in (run_dir, fem_dir):
                    dest_f = os.path.join(dest_dir, os.path.basename(fpath))
                    safe_copy_file(fpath, dest_f)
                app._log(f"[FILE SYNC] Copied {os.path.basename(fpath)} to run folder: {os.path.join(run_dir, os.path.basename(fpath))}\n")

        script_path = os.path.join(fem_dir, "waam_simulation.edp")
        builder.save(script_path)

        for _k in ("hz_base", "n_layers", "lx", "ly_base"):
            if _k in getattr(builder, "p", {}):
                params[_k] = builder.p[_k]
                if hasattr(app, "_param_vars") and _k in app._param_vars:
                    try:
                        _v = builder.p[_k]
                        app._param_vars[_k][0].set(
                            str(int(_v)) if _k == "n_layers" else str(round(float(_v) * 1000.0, 3)))
                    except Exception:
                        pass

        h_net = params.get("heat_input_net_J_per_mm", 0.0)
        p_net = params.get("power_net_W", 0.0)
        h_gr = params.get("heat_input_gross_J_per_mm", 0.0)
        app._log(f"\n[OUTPUT DIRECTORY] Directed to: {fem_dir}\n")
        app._log(f"[VISUAL OUTPUTS]   Directed to: {vis_dir}\n")
        app._log(f"[PROCESS] Calculated Heat Input: Net = {h_net:.2f} J/mm ({h_net/1000.0:.3f} kJ/mm) | P_net = {p_net/1000.0:.2f} kW | Gross = {h_gr:.2f} J/mm\n")
        app._log(f"[CODEGEN] [OK] FreeFEM++ script generated: {script_path}\n")
        app.status_var.set("● Status: Script Generated")

        params_path = os.path.join(fem_dir, "parameters.json")
        try:
            with open(params_path, 'w') as f:
                json.dump(params, f, indent=2)
            safe_copy_file(params_path, os.path.join(run_dir, "parameters.json"))
            app._log(f"[CODEGEN] Parameters metadata saved: {params_path}\n")
        except Exception as pe:
            app._log(f"[CODEGEN] [WARNING] Could not save parameters.json ({pe})\n")
        return script_path
    except Exception as e:
        app._log(f"\n[CODEGEN] [ERROR] Error generating script: {e}\n")
        messagebox.showerror("Script Generation Error", str(e))
        return None
    finally:
        app._batch_updating = False


def preflight_health_check(fem_dir: str, script_path: str, app) -> bool:
    """Pre-flight sanity check and self-healing for simulation assets."""
    try:
        from mesh.stl_pipeline import reorient_mesh_boundary_triangles
        import re

        # 1. Sanitize all .mesh files in fem_dir (prune orphan facets, fix outward normals)
        mesh_files = glob.glob(os.path.join(fem_dir, "*.mesh"))
        for mf in mesh_files:
            n_fixed = reorient_mesh_boundary_triangles(mf)
            if n_fixed > 0:
                app._log(f"[PRE-FLIGHT] Auto-healed boundary mesh: {os.path.basename(mf)} ({n_fixed} orphan/inverted facets fixed).\n")

        # 2. Verify script_path exists and dimensions are physically sane
        if not os.path.exists(script_path):
            app._log(f"[PRE-FLIGHT] [ERROR] Simulation script missing: {script_path}\n")
            return False

        with open(script_path, "r", encoding="utf-8", errors="replace") as sf:
            code = sf.read()

        modified = False
        # Check LxW, LyBase, HzBase scale collapses (e.g. 0.0002 m instead of 0.200 m)
        for var_name, min_sane_m in (("LxW", 0.005), ("LyBase", 0.005), ("HzBase", 0.0005)):
            m = re.search(rf"real\s+{var_name}\s*=\s*([0-9.eE+-]+);", code)
            if m:
                val = float(m.group(1))
                if 0.0 < val < min_sane_m:
                    healed_val = val * 1000.0
                    code = code[:m.start(1)] + f"{healed_val:.6g}" + code[m.end(1):]
                    modified = True
                    app._log(f"[PRE-FLIGHT] [AUTO-HEAL] Corrected collapsed dimension {var_name}: {val*1000:.3f} mm -> {healed_val*1000:.1f} mm\n")

        if modified:
            with open(script_path, "w", encoding="utf-8") as sf:
                sf.write(code)
            app._log(f"[PRE-FLIGHT] Updated simulation script with validated physical dimensions.\n")

        app._log(f"[PRE-FLIGHT] [OK] Multi-physics domain, mesh topology, and assets passed pre-flight verification.\n")
        return True
    except Exception as ex:
        app._log(f"[PRE-FLIGHT] [WARNING] Pre-flight verification notice: {ex}\n")
        return True


def run_simulation(app, is_auto_retry: bool = False):
    """Execute FreeFEM++ simulation script with live process monitoring."""
    if not is_auto_retry:
        app._heal_attempted = False
    is_new = bool(app.active_run_executed) and not is_auto_retry
    script_path = generate_script(app, is_new_run=is_new)
    if not script_path:
        return

    fem_dir = os.path.dirname(script_path)
    if not preflight_health_check(fem_dir, script_path, app):
        app.status_var.set("✕ Status: Pre-flight Error")
        return

    app.active_run_executed = True
    app._log(f"\n{'='*55}\nSTARTING WAAM MULTI-PHYSICS SIMULATION...\n{'='*55}\n")
    app.running = True
    app.status_var.set("▶ Status: Solving...")
    app.run_btn.config(state=tk.DISABLED)
    app.stop_btn.config(state=tk.NORMAL)
    if hasattr(app, "console_status_dot"):
        app.console_status_dot.config(text="● STREAMING LIVE", fg="#22c55e")

    app._log_queue = queue.Queue()
    app._last_progress_val = -1
    app._last_stage_text = ""
    app._last_step_text = ""

    def poll_stream():
        if not hasattr(app, "_log_queue"):
            return
        batch = []
        try:
            while len(batch) < 350:
                batch.append(app._log_queue.get_nowait())
        except queue.Empty:
            pass

        if batch:
            app._log_batch(batch)

        if getattr(app, "running", False) or not app._log_queue.empty():
            app.root.after(25, poll_stream)

    app.root.after(25, poll_stream)

    def run_thread():
        rc = -1
        try:
            exec_mode = getattr(app, "parallel_mode_var", None)
            mode_str = exec_mode.get() if exec_mode else "multi_core_threaded"

            mpi_var = getattr(app, "mpi_ranks_var", None)
            try:
                raw_ranks = mpi_var.get().split()[0] if mpi_var else "1"
                n_ranks = max(1, int(raw_ranks))
            except Exception:
                n_ranks = 1

            cpu_var = getattr(app, "cpu_threads_var", None)
            try:
                import re
                txt = cpu_var.get() if cpu_var else ""
                m_c = re.search(r"(\d+)", txt)
                n_cores = int(m_c.group(1)) if m_c else min(os.cpu_count() or 4, 16)
            except Exception:
                n_cores = min(os.cpu_count() or 4, 12)

            env = os.environ.copy()
            env["OMP_NUM_THREADS"] = str(n_cores)
            env["OPENBLAS_NUM_THREADS"] = str(n_cores)
            env["MKL_NUM_THREADS"] = str(n_cores)
            env["VECLIB_MAXIMUM_THREADS"] = str(n_cores)
            env["NUMEXPR_NUM_THREADS"] = str(n_cores)

            abs_script = os.path.abspath(script_path)
            abs_cwd = os.path.abspath(os.path.dirname(script_path) or ".")

            if os.path.basename(os.path.normpath(abs_cwd)) == "FreeFEM":
                fem_dir = abs_cwd
                case_dir = os.path.dirname(abs_cwd)
            else:
                case_dir = app.active_run_dir or abs_cwd
                fem_dir = os.path.join(case_dir, "FreeFEM")
            os.makedirs(fem_dir, exist_ok=True)
            target_run_dir = fem_dir
            norm_run_dir = os.path.abspath(target_run_dir).replace('\\', '/').rstrip('/') + '/'

            cmd = None
            ff_bin_info = ""
            if mode_str == "mpi_parallel" or n_ranks > 1:
                try:
                    from run import find_freefem_mpi
                    ff_mpi, ff_bin_mpi = find_freefem_mpi()
                except Exception:
                    ff_mpi, ff_bin_mpi = "", ""
                if ff_mpi and ff_bin_mpi:
                    from core.platform_adapter import is_windows_solver_path, to_solver_path
                    if is_windows_solver_path(ff_mpi):
                        _script = to_solver_path(abs_script)
                        _rundir = to_solver_path(norm_run_dir)
                    else:
                        _script, _rundir = abs_script, norm_run_dir
                    cmd = [ff_mpi, "-np", str(n_ranks), ff_bin_mpi, _script, _rundir]
                    ff_bin_info = f"{ff_mpi} -np {n_ranks} ({ff_bin_mpi})"
                    app._log_queue.put(f"[PARALLEL] MPI distributed execution: {n_ranks} ranks active via {ff_mpi}\\n")
                else:
                    app._log_queue.put(f"[PARALLEL] [INFO] ff-mpirun/FreeFem++-mpi not found. Using multi-core OpenMP ({n_cores} CPU threads).\\n")

            if cmd is None:
                ff_path = find_freefem_serial() or shutil.which("FreeFem++") or "FreeFem++"
                ff_bin_info = str(ff_path)
                from core.platform_adapter import is_windows_solver_path, to_solver_path
                if is_windows_solver_path(ff_path):
                    _script = to_solver_path(abs_script)
                    _rundir = to_solver_path(norm_run_dir)
                else:
                    _script, _rundir = abs_script, norm_run_dir
                raw_cmd = [ff_path, _script, _rundir]
                cmd, _ = build_unbuffered_command(raw_cmd)
                app._log_queue.put(f"[PARALLEL] Multi-core threaded execution: {n_cores} CPU cores active (OMP/MKL/Accelerate).\n")

            app.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=abs_cwd,
                env=env,
                bufsize=1,
                **spawn_isolation_kwargs(),
            )
            log_file_path = os.path.join(fem_dir, "sim.log")
            with open(log_file_path, "w", encoding="utf-8") as log_f:
                log_f.write("================================================================================\n")
                log_f.write("WAAM MULTI-PHYSICS SIMULATION TERMINAL LOG\n")
                log_f.write(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_f.write(f"Script:    {abs_script}\n")
                log_f.write(f"Case Dir:  {case_dir}\n")
                log_f.write(f"Run Dir:   {target_run_dir}\n")
                log_f.write(f"Backend:   {ff_bin_info}\n")
                log_f.write(f"Threads:   {n_cores} (OMP/MKL/Accelerate)\n")
                log_f.write("================================================================================\n\n")
                log_f.flush()

                for line in app.process.stdout:
                    if not app.running:
                        break
                    line = line.replace("\r", "")
                    while line and ord(line[0]) < 32 and line[0] not in "\n\t":
                        line = line[1:]
                    log_f.write(line)
                    log_f.flush()
                    app._log_queue.put(line)

                app.process.wait()
                rc = app.process.returncode

                log_f.write("\n================================================================================\n")
                log_f.write(f"EXECUTION FINISHED - RETURN CODE: {rc}\n")
                log_f.write(f"Finished at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_f.write("================================================================================\n")
                log_f.flush()

            if rc == 0:
                app.root.after(0, app.status_var.set, "✓ Status: Completed")
                if hasattr(app, "console_status_dot"):
                    app.root.after(0, lambda: app.console_status_dot.config(text="● COMPLETED", fg="#38bdf8"))
                try:
                    from core.postprocess.output_manager import (
                        generate_run_summary,
                        generate_paraview_loader_script,
                        generate_enhanced_html_report
                    )
                    from postprocess.plot_generator import generate_all_plots
                    p_final = app._collect_params()
                    p_final["output_dir"] = target_run_dir.rstrip('/') + '/'
                    plots = generate_all_plots(target_run_dir)
                    pv_scr = generate_paraview_loader_script(target_run_dir)
                    summary = generate_run_summary(target_run_dir, p_final, return_code=rc)

                    summary_file = os.path.join(target_run_dir, 'run_summary.json')
                    plots_dir = os.path.join(target_run_dir, 'plots')

                    sep_line = "=" * 76
                    banner_msg = (
                        f"\n\n{sep_line}\n"
                        f"  [OK] SIMULATION COMPLETED SUCCESSFULLY\n"
                        f"{sep_line}\n\n"
                        f"  • [SUMMARY]   Executive run summary saved:\n"
                        f"                {summary_file}\n\n"
                        f"  • [PLOTS]     Generated {len(plots)} publication-quality 2D analysis plot(s):\n"
                        f"                {plots_dir}\n\n"
                        f"  • [PARAVIEW]  3D visualization loader script created:\n"
                        f"                {pv_scr}\n\n"
                    )
                    app.root.after(0, app._log, banner_msg)

                    try:
                        report_html = generate_enhanced_html_report(target_run_dir, p_final, summary, plots)
                        if report_html and os.path.exists(report_html):
                            top_rep = os.path.join(case_dir, "report.html")
                            if top_rep != report_html:
                                shutil.copy2(report_html, top_rep)
                            app.root.after(0, app._log, f"  • [REPORT]    Comprehensive engineering HTML report:\n                {report_html}\n\n")
                        top_log = os.path.join(case_dir, "sim.log")
                        if os.path.exists(log_file_path) and top_log != log_file_path:
                            shutil.copy2(log_file_path, top_log)
                            app.root.after(0, app._log, f"  • [LOG]       Complete execution log published:\n                {top_log}\n\n")
                    except Exception as rep_err:
                        app.root.after(0, app._log, f"  • [REPORT]    Publishing note: {rep_err}\n\n")

                    app.root.after(0, app._log, f"{sep_line}\n\n")
                    app.root.after(500, app._log_reload)
                except Exception as pe:
                    app.root.after(0, app._log, f"[POSTPROCESS] [WARNING] Post-processing note: {pe}\n")
            else:
                from core.solver_diagnostics import FreeFEMDiagnosticsEngine
                diag = FreeFEMDiagnosticsEngine.parse_log(log_file_path, abs_script)
                diag_banner = (
                    f"\n\n{'=' * 76}\n"
                    f"  [SOLVER ERROR DIAGNOSIS] {diag.summary}\n"
                    f"{'=' * 76}\n"
                    f"  • Category:       {diag.category} (Exit Code: {diag.error_code})\n"
                    f"  • Root Cause:     {diag.root_cause}\n"
                )
                if diag.offending_line_in_edp:
                    diag_banner += f"  • Script Line:    Line {diag.offending_line_in_edp} in {os.path.basename(abs_script)}\n"
                if diag.offending_file:
                    diag_banner += f"  • Offending Asset:{diag.offending_file}\n"
                diag_banner += (
                    f"  • Remediation:    {diag.remediation_suggestion}\n"
                    f"  • Auto-Healable:  {'YES — Automated repair available' if diag.is_auto_healable else 'NO'}\n"
                    f"{'=' * 76}\n\n"
                )
                app.root.after(0, app._log, diag_banner)

                if diag.is_auto_healable and not getattr(app, "_heal_attempted", False):
                    app._heal_attempted = True
                    app.root.after(0, app._log, "  [AUTO-HEAL] Initiating automated self-healing pipeline...\n")
                    healed, action_msg = FreeFEMDiagnosticsEngine.auto_heal(diag, target_run_dir, p_final if 'p_final' in locals() else None)
                    if healed:
                        app.root.after(0, app._log, f"  [AUTO-HEAL] ✓ {action_msg}\n")
                        app.root.after(0, app._log, "  [AUTO-HEAL] Automatically re-running simulation with healed assets...\n\n")
                        app.root.after(200, lambda: run_simulation(app, is_auto_retry=True))
                        return

                app.root.after(0, app._log, f"\n[ERROR] FreeFEM exited with code {rc}\n")
                app.root.after(0, app.status_var.set, f"✕ Status: Error (Exit {rc})")
                if hasattr(app, "console_status_dot"):
                    app.root.after(0, lambda: app.console_status_dot.config(text="● ERROR", fg="#ef4444"))
        except Exception as e:
            app._log(f"\n[ERROR] Execution failure: {e}\n")
            app.root.after(0, app.status_var.set, "✕ Status: Execution Error")
            if hasattr(app, "console_status_dot"):
                app.root.after(0, lambda: app.console_status_dot.config(text="● ERROR", fg="#ef4444"))
        finally:
            app.running = False
            app.root.after(0, lambda: app.run_btn.config(state=tk.NORMAL))
            app.root.after(0, lambda: app.stop_btn.config(state=tk.DISABLED))
            if hasattr(app, "console_status_dot"):
                app.root.after(0, lambda: app.console_status_dot.config(
                    text="● COMPLETED" if rc == 0 else "● STOPPED",
                    fg="#38bdf8" if rc == 0 else "#f59e0b"
                ))

    threading.Thread(target=run_thread, daemon=True).start()


def stop_simulation(app):
    """Stop active simulation process."""
    if app.running:
        if not messagebox.askyesno(
            "Stop Simulation",
            "A simulation is running. Stop it now?\nPartial results will be kept.",
        ):
            return
    app.running = False
    if hasattr(app, "console_status_dot"):
        app.console_status_dot.config(text="● STOPPED", fg="#f59e0b")
    if app.process:
        proc = app.process
        # Kill the WHOLE solver tree (script -> sh -> FreeFem++, or on Windows
        # FreeFem++-win64.exe + children). The old retry loop always landed on
        # proc.terminate(), which only reaps the wrapper and leaves the solver
        # writing into waam_output -> PermissionError on the next run.
        kill_process_tree(proc)
        app.process = None
        app._log("\nProcess terminated by user.\n")
    app.status_var.set("■ Status: Stopped")
    app.run_btn.config(state=tk.NORMAL)
    app.stop_btn.config(state=tk.DISABLED)


def open_report(app):
    """Open simulation HTML summary report in browser."""
    outdir = app._get_active_or_latest_run_dir()
    search_order = [
        os.path.abspath(os.path.join(outdir, "waam_report.html")),
        os.path.abspath(os.path.join(outdir, "FreeFEM", "waam_report.html")),
        os.path.abspath(os.path.join(outdir, "report.html")),
        os.path.abspath(os.path.join(outdir, "FreeFEM", "report.html")),
    ]
    report_path = next((c for c in search_order if os.path.exists(c)), search_order[0])

    if os.path.exists(report_path):
        open_url_in_browser(f"file://{report_path}")
        app._log(f"[REPORT] Opened simulation report: {report_path}\n")
        return

    plots_dir = os.path.join(outdir, "plots")
    if not os.path.exists(plots_dir):
        plots_dir = os.path.join(outdir, "FreeFEM", "plots")
    if not os.path.exists(plots_dir):
        all_plots = glob.glob(os.path.join(app._get_base_output_dir(), "*", "plots"))
        all_plots += glob.glob(os.path.join(app._get_base_output_dir(), "*", "FreeFEM", "plots"))
        if all_plots:
            plots_dir = max(all_plots, key=os.path.getmtime)
    if os.path.exists(plots_dir):
        open_path_in_file_manager(plots_dir)
        app._log(f"[PLOTS] Opened plots directory: {plots_dir}\n")
        return

    messagebox.showinfo("Plots Not Found", "No plots found yet. Run a simulation first to produce results.")


def open_paraview(app):
    """Open simulation results in ParaView."""
    run_dir = app._get_active_or_latest_run_dir()
    vis_candidates = [
        os.path.join(run_dir, "FreeFEM", "visual_outputs"),
        os.path.join(run_dir, "visual_outputs"),
    ]
    vis_dir = next((v for v in vis_candidates if os.path.isdir(v)), vis_candidates[0])

    micro_vtu = os.path.abspath(os.path.join(vis_dir, "waam_micro.vtu"))
    mech_vtu = os.path.abspath(os.path.join(vis_dir, "waam_mech.vtu"))
    pvd_file = os.path.abspath(os.path.join(vis_dir, "waam.pvd"))

    if not os.path.exists(micro_vtu) and os.path.exists(os.path.join(run_dir, "waam_micro.vtu")):
        micro_vtu = os.path.abspath(os.path.join(run_dir, "waam_micro.vtu"))
    if not os.path.exists(mech_vtu) and os.path.exists(os.path.join(run_dir, "waam_mech.vtu")):
        mech_vtu = os.path.abspath(os.path.join(run_dir, "waam_mech.vtu"))
    if not os.path.exists(pvd_file) and os.path.exists(os.path.join(run_dir, "waam.pvd")):
        pvd_file = os.path.abspath(os.path.join(run_dir, "waam.pvd"))

    targets = []
    if os.path.exists(micro_vtu):
        targets.append(micro_vtu)
    if os.path.exists(mech_vtu):
        targets.append(mech_vtu)
    if os.path.exists(pvd_file):
        targets.append(pvd_file)

    if not targets:
        sub_targets = glob.glob(os.path.join(vis_dir, "*.pvd")) + glob.glob(os.path.join(vis_dir, "*.vtu"))
        for legacy in (run_dir, os.path.join(run_dir, "FreeFEM")):
            if not sub_targets:
                sub_targets = glob.glob(os.path.join(legacy, "*.pvd")) + glob.glob(os.path.join(legacy, "*.vtu"))
        targets = [os.path.abspath(f) for f in sorted(list(set(sub_targets)))]

    if not targets:
        app._log(f"[PARAVIEW] [WARNING] No VTU/PVD visual datasets found in:\n  {vis_dir}\n"
                  f"Execute 'RUN SIMULATION' first to generate visual outputs.\n")
        messagebox.showinfo(
            "No Visual Outputs Found",
            f"No 3D visual outputs (.vtu or .pvd) found in:\n{vis_dir}\n\n"
            f"Click 'RUN SIMULATION' to solve the case and generate ParaView datasets."
        )
        return

    candidates = [
        shutil.which("paraview"),
        os.environ.get("PARAVIEW_BIN"),
        os.path.expanduser("~/bin/paraview"),
        "/Applications/ParaView-5.13.3.app/Contents/MacOS/paraview",
        "/opt/homebrew/bin/paraview",
        "/usr/local/bin/paraview",
    ] + glob.glob("/Applications/ParaView*.app/Contents/MacOS/paraview")

    pv_bin = None
    for c in candidates:
        if c and os.path.exists(c):
            pv_bin = c
            break

    opened = False
    if pv_bin:
        try:
            subprocess.Popen([pv_bin] + targets)
            app._log(f"[PARAVIEW] [OK] Launching {pv_bin}\n")
            for t in targets:
                app._log(f"  -> {os.path.basename(t)} ({os.path.dirname(t)})\n")
            opened = True
        except Exception as e:
            app._log(f"[PARAVIEW] [WARNING] Binary launch error: {e}\n")

    if not opened and sys.platform == "darwin":
        pv_apps = ["/Applications/ParaView-5.13.3.app", "/Applications/ParaView.app"] + glob.glob("/Applications/ParaView*.app")
        found = [p for p in pv_apps if os.path.exists(p)]
        if found:
            try:
                subprocess.Popen(["open", "-a", found[0], "--args"] + targets)
                app._log(f"[PARAVIEW] [OK] Opening via open -a {found[0]} ({len(targets)} files)\n")
                opened = True
            except Exception as e:
                app._log(f"[PARAVIEW] [ERROR] open -a failed: {e}\n")

    if not opened:
        app._open_output()
        app._log(f"[PARAVIEW] [INFO] ParaView binary not found. Datasets are in: {vis_dir}\n")
        messagebox.showinfo(
            "ParaView Not Found",
            f"ParaView application was not found on your system.\n\n"
            f"Your visual output datasets are saved in:\n{vis_dir}\n\n"
            f"Files ready for inspection:\n" + "\n".join(f" - {os.path.basename(t)}" for t in targets) + "\n\n"
            f"To view in 3D, download ParaView from: https://www.paraview.org"
        )
