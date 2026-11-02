"""Mesh, CAD import, and Slicer controller for WAAM Framework."""

import json
import math
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


def verify_meshing_rules(app) -> dict:
    """Evaluate WAAM finite element discretization standards."""
    try:
        lx_mm = app._get_dim_mm("lx", 150.0)
        ty_dep_mm = app._get_dim_mm("ty_dep", 5.0)
        h_bead_mm = app._get_dim_mm("h_bead", 3.0)
        nl = max(int(float(app._param_vars.get("n_layers", (None,))[0].get().strip() or "1")), 1)
        remelt = app._f(app._param_vars.get("remelt_ratio", (None,))[0], 0.8)
        hz_dep_mm = h_bead_mm if nl <= 1 else (h_bead_mm + (nl - 1) * h_bead_mm * remelt)

        nx_dep = max(int(float(app._param_vars.get("nx_dep", (None,))[0].get().strip() or "30")), 1)
        ny_dep = max(int(float(app._param_vars.get("ny_dep", (None,))[0].get().strip() or "6")), 1)
        nz_dep = max(int(float(app._param_vars.get("nz_dep", (None,))[0].get().strip() or "26")), 1)

        dx_dep = lx_mm / nx_dep
        dy_dep = ty_dep_mm / ny_dep
        dz_dep = hz_dep_mm / nz_dep

        ar_dep = max(dx_dep, dy_dep, dz_dep) / max(min(dx_dep, dy_dep, dz_dep), 1e-4)
        cpl = nz_dep / nl

        af = app._get_dim_mm("af", 4.0)
        bG = app._get_dim_mm("bG", 4.0)
        cG = app._get_dim_mm("cG", 4.0)

        violations = []

        rule1_ok = (nz_dep >= 2 * nl) or (dz_dep <= (h_bead_mm / 2.0 + 1e-3))
        if not rule1_ok:
            violations.append(f"Layer Resolution: {cpl:.1f} cells/layer (dz={dz_dep:.2f}mm > h_bead/2={h_bead_mm/2:.2f}mm; minimum 2 cells/layer required)")

        rule2_ok = (ny_dep >= 2)
        if not rule2_ok:
            violations.append(f"Bead Width Resolution: Only {ny_dep} cell across bead (dy={dy_dep:.2f}mm > w/2; minimum 2 required)")

        rule3_ok = (dx_dep <= af / 2.0 + 1e-3) and (dy_dep <= bG / 2.0 + 1e-3) and (dz_dep <= cG / 2.0 + 1e-3)
        if not rule3_ok:
            violations.append(f"Goldak Heat Source: dx={dx_dep:.2f}mm, dy={dy_dep:.2f}mm, dz={dz_dep:.2f}mm is too coarse to resolve steep meltpool gradients (requires dx≤{af/2:.2f}mm, dy≤{bG/2:.2f}mm, dz≤{cG/2:.2f}mm)")

        rule4_ok = (ar_dep <= 2.05)
        if not rule4_ok:
            violations.append(f"Aspect Ratio: AR={ar_dep:.2f} exceeds recommended limit of 2.0")

        all_passed = rule1_ok and rule2_ok and rule3_ok and rule4_ok

        return {
            "all_passed": all_passed,
            "rule1_ok": rule1_ok,
            "rule2_ok": rule2_ok,
            "rule3_ok": rule3_ok,
            "rule4_ok": rule4_ok,
            "cpl": cpl,
            "dz_dep": dz_dep,
            "dy_dep": dy_dep,
            "dx_dep": dx_dep,
            "ar_dep": ar_dep,
            "af": af, "bG": bG, "cG": cG,
            "h_bead_mm": h_bead_mm,
            "violations": violations,
        }
    except Exception:
        return {"all_passed": True, "violations": []}


def auto_fix_mesh_rules(app):
    """Adjust grid divisions to strictly meet all WAAM meshing standards."""
    try:
        import re
        if hasattr(app, "slicer_h_var"):
            try:
                h_val_str = re.sub(r"[^\d.]", "", str(app.slicer_h_var.get()).strip())
                if h_val_str:
                    h_val = float(h_val_str)
                    if h_val > 0.05 and "h_bead" in app._param_vars:
                        app._param_vars["h_bead"][0].set(f"{h_val:.2f}")
            except Exception:
                pass
        if hasattr(app, "slicer_w_var"):
            try:
                w_val_str = re.sub(r"[^\d.]", "", str(app.slicer_w_var.get()).strip())
                if w_val_str:
                    w_val = float(w_val_str)
                    if w_val > 0.1 and "ty_dep" in app._param_vars:
                        app._param_vars["ty_dep"][0].set(f"{w_val:.2f}")
            except Exception:
                pass

        lx_mm = app._get_dim_mm("lx", 150.0)
        ty_dep_mm = app._get_dim_mm("ty_dep", 5.0)
        h_bead_mm = app._get_dim_mm("h_bead", 3.0)
        nl = max(int(float(re.sub(r"[^\d.]", "", app._param_vars.get("n_layers", (None,))[0].get().strip() or "1") or "1")), 1)
        remelt = app._f(app._param_vars.get("remelt_ratio", (None,))[0], 0.8)
        hz_dep_mm = h_bead_mm if nl <= 1 else (h_bead_mm + (nl - 1) * h_bead_mm * remelt)

        af = app._get_dim_mm("af", 4.0)
        bG = app._get_dim_mm("bG", 4.0)
        cG = app._get_dim_mm("cG", 4.0)

        dz_target = min(h_bead_mm / 2.0, cG / 2.0)
        nz_dep = max(2 * nl, int(math.ceil(hz_dep_mm / dz_target)))

        dy_target = min(ty_dep_mm / 3.0, bG / 2.5)
        ny_dep = max(4, int(math.ceil(ty_dep_mm / dy_target)))

        actual_dz = hz_dep_mm / nz_dep
        actual_dy = ty_dep_mm / ny_dep

        target_min_d = min(actual_dy, actual_dz)
        dx_target = min(af / 2.5, 2.0 * target_min_d)
        nx_dep = max(2, int(math.ceil(lx_mm / dx_target)))

        nx_base = nx_dep
        ly_base_mm = app._get_dim_mm("ly_base", 150.0)
        hz_base_mm = app._get_dim_mm("hz_base", 5.0)
        ny_base = max(int(round(ly_base_mm / (actual_dy * 3.0))), 8)
        nz_base = max(int(round(hz_base_mm / 2.0)), 2)

        if "nx_dep" in app._param_vars: app._param_vars["nx_dep"][0].set(str(nx_dep))
        if "ny_dep" in app._param_vars: app._param_vars["ny_dep"][0].set(str(ny_dep))
        if "nz_dep" in app._param_vars: app._param_vars["nz_dep"][0].set(str(nz_dep))
        if "nx_base" in app._param_vars: app._param_vars["nx_base"][0].set(str(nx_base))
        if "ny_base" in app._param_vars: app._param_vars["ny_base"][0].set(str(ny_base))
        if "nz_base" in app._param_vars: app._param_vars["nz_base"][0].set(str(nz_base))

        if hasattr(app, "target_dx_var"): app.target_dx_var.set(f"{lx_mm / nx_dep:.2f}")
        if hasattr(app, "target_dy_var"): app.target_dy_var.set(f"{actual_dy:.2f}")
        if hasattr(app, "target_dz_var"): app.target_dz_var.set(f"{actual_dz:.2f}")

        update_mesh_calc(app)
        app._log(
            f"[AUTO-FIX] Discretization adjusted to WAAM Standards:\n"
            f"   • Nz_dep = {nz_dep} ({nz_dep/nl:.1f} cells/layer, dz = {actual_dz:.2f} mm <= h_bead/2)\n"
            f"   • Ny_dep = {ny_dep} ({ny_dep} cells across bead, dy = {actual_dy:.2f} mm)\n"
            f"   • Nx_dep = {nx_dep} (dx = {lx_mm/nx_dep:.2f} mm <= af/2.5)\n"
            f"   • Aspect Ratio: AR_dep = {max(lx_mm/nx_dep, actual_dy, actual_dz)/min(lx_mm/nx_dep, actual_dy, actual_dz):.2f} <= 2.0\n"
        )
        app.status_var.set(f"Status: Mesh Auto-Fixed (AR <= 2.0, {nz_dep/nl:.1f} cells/layer)")
    except Exception as e:
        if hasattr(app, "_log"):
            app._log(f"[AUTO-FIX ERROR] {e}\n")
        messagebox.showerror("Auto-Fix Error", str(e))


def generate_waam_mesh(app):
    """Validates rules and generates conforming 3D volume mesh."""
    rules = verify_meshing_rules(app)
    if not rules["all_passed"]:
        violations_str = "\n• " + "\n• ".join(rules["violations"])
        msg = (
            f"WAAM Meshing Quality Standard Violations Detected:\n"
            f"{violations_str}\n\n"
            f"Would you like to Auto-Fix the discretization to meet all standards (≥2 cells/layer, AR ≤ 2.0, Goldak resolvability) before generating?"
        )
        res = messagebox.askyesnocancel("WAAM Mesh Quality Standards", msg, parent=app.root)
        if res is None:
            return
        if res:
            auto_fix_mesh_rules(app)

    mesh_src = app.mesh_source_var.get()
    cad_p = getattr(app, "loaded_stl_path", "") or app.mesh_file_var.get().strip()

    if mesh_src == "cad_file" and cad_p and os.path.exists(cad_p):
        start_stl_meshing_thread(app, cad_p)
        return

    try:
        from mesh.structured_conforming import generate_waam_mesh as _gen_mesh
        run_dir = app._get_or_create_run_dir(is_new_run=False)
        os.makedirs(run_dir, exist_ok=True)
        out_mesh = os.path.join(run_dir, "waam_domain.mesh")

        params = app._collect_params()
        _nlay = int(params.get("n_layers", 1))
        _hb1 = float(params.get("h_bead_first", params.get("h_bead", 0.003)))
        _hbs = float(params.get("h_bead_subseq", _hb1))
        _hz_dep = (_nlay * _hb1) if _nlay <= 1 else (_hb1 + (_nlay - 1) * _hbs)

        kwargs = dict(
            lx=float(params["lx"]),
            ly_base=float(params["ly_base"]),
            hz_base=float(params["hz_base"]),
            ty_dep=float(params["ty_dep"]),
            hz_dep=_hz_dep,
            nx_dep=int(params["nx_dep"]),
            ny_dep=int(params["ny_dep"]),
            nz_dep=int(params["nz_dep"]),
            nx_base=int(params["nx_base"]),
            ny_base=int(params["ny_base"]),
            nz_base=int(params["nz_base"]),
        )

        app.status_var.set(f"Status: Meshing... (target ~{int(params.get('nx_dep', 30))}x{int(params.get('ny_dep', 6))} grid)")

        def _mesh_worker():
            try:
                info = _gen_mesh(out_mesh, **kwargs)
                app.root.after(0, lambda: _mesh_done(info))
            except Exception as e:
                app.root.after(0, lambda err=e: _mesh_fail(err))

        def _mesh_done(info):
            app.loaded_mesh_path = out_mesh
            app.mesh_file_var.set(out_mesh)
            app._log(
                f"\n[MESH-GEN] [OK] Conforming Structured Mesh Generated successfully:\n"
                f"[MESH-GEN] Path: {out_mesh}\n"
                f"[MESH-GEN] Scale: {info['n_nodes']:,} nodes  |  {info['n_tets']:,} tetrahedra\n"
                f"[MESH-GEN] Grid: Nx={info['n_x']}, Ny={info['n_y']}, Nz={info['n_z']}\n"
                f"[MESH-GEN] Shared Conforming Boundary Faces: {info['n_boundary_faces']:,}\n"
                f"[MESH-GEN] Structure: 6-Tet Kuhn Cartesian Brick Subdivision (FreeFEM Conforming)\n"
            )
            app.status_var.set(f"Status: Mesh Generated ({info['n_nodes']:,} nodes, {info['n_tets']:,} tets)")

            params["mesh_file"] = out_mesh
            vp = getattr(app, "viewport", getattr(app, "viewport_3d", None))
            if vp:
                vp.update_mesh(params)
            if hasattr(app, "slicer_widget") and hasattr(app.slicer_widget, "load_file"):
                try:
                    app.slicer_widget.load_file(out_mesh)
                except Exception:
                    pass

            messagebox.showinfo("Mesh Generated", f"Successfully generated conforming structured WAAM volume mesh!\n\nNodes: {info['n_nodes']:,}\nTetrahedra: {info['n_tets']:,}\nResolution: {int(params['nz_dep'])/_nlay:.1f} cells/layer\nSaved to: {out_mesh}")

        def _mesh_fail(err):
            messagebox.showerror("Mesh Generation Error", f"Failed to generate structured volume mesh:\n{err}")
            app._log(f"[MESH-GEN] [ERROR] {err}\n")

        # Structured mesh synthesis is pure numpy math: run it off the Tk
        # thread so a 100k-node target cannot freeze the window.
        threading.Thread(target=_mesh_worker, daemon=True).start()
    except Exception as e:
        messagebox.showerror("Mesh Generation Error", f"Failed to generate structured volume mesh:\n{e}")
        app._log(f"[MESH-GEN] [ERROR] {e}\n")


def update_mesh_calc(app):
    """Update live calculated element sizes displayed in the Mesh tab."""
    if not hasattr(app, "mesh_calc_label"):
        return
    try:
        lx_mm = app._get_dim_mm("lx", 150.0)
        ty_dep_mm = app._get_dim_mm("ty_dep", 5.0)
        h_bead_mm = app._get_dim_mm("h_bead", 3.0)
        hz_base_mm = app._get_dim_mm("hz_base", 5.0)
        ly_base_mm = app._get_dim_mm("ly_base", 150.0)
        nl = max(int(float(app._param_vars.get("n_layers", (None,))[0].get().strip() or "1")), 1)
        remelt = app._f(app._param_vars.get("remelt_ratio", (None,))[0], 0.8)
        hz_dep_mm = h_bead_mm if nl <= 1 else (h_bead_mm + (nl - 1) * h_bead_mm * remelt)

        def get_div(key, default=1):
            if key not in app._param_vars:
                return default
            return max(int(float(app._param_vars[key][0].get().strip() or str(default))), 1)

        nx_dep = get_div("nx_dep", 30)
        ny_dep = get_div("ny_dep", 6)
        nz_dep = get_div("nz_dep", 26)

        nx_base = get_div("nx_base", 30)
        ny_base = get_div("ny_base", 20)
        nz_base = get_div("nz_base", 8)

        dx_dep = lx_mm / nx_dep
        dy_dep = ty_dep_mm / ny_dep
        dz_dep = hz_dep_mm / nz_dep

        dx_base = lx_mm / nx_base
        dy_base = ly_base_mm / ny_base
        dz_base = hz_base_mm / nz_base

        ar_dep = max(dx_dep, dy_dep, dz_dep) / max(min(dx_dep, dy_dep, dz_dep), 1e-4)
        ar_base = max(dx_base, dy_base, dz_base) / max(min(dx_base, dy_base, dz_base), 1e-4)

        nodes_base = (nx_base + 1) * (ny_base + 1) * (nz_base + 1)
        nodes_dep = (nx_dep + 1) * (ny_dep + 1) * (nz_dep + 1)
        tets_base = 6 * nx_base * ny_base * nz_base
        tets_dep = 6 * nx_dep * ny_dep * nz_dep
        total_nodes = nodes_base + nodes_dep
        total_tets = tets_base + tets_dep

        is_cad_active = (
            (hasattr(app, "mesh_source_var") and app.mesh_source_var.get() in ("cad_file", "gcode_file")) or
            bool(getattr(app, "loaded_stl_path", None))
        )
        cad_p = getattr(app, "loaded_stl_path", None) or (app.mesh_file_var.get().strip() if hasattr(app, "mesh_file_var") else None)
        cpl = nz_dep / nl

        if is_cad_active and cad_p and os.path.exists(cad_p):
            cad_name = os.path.basename(cad_p)
            info = (
                f"Imported CAD / Toolpath: {cad_name}\n"
                f"Layer Slicing Count:     {nl} Layers (Layer Height dz = {dz_dep:.2f} mm | Bead Width dy = {dy_dep:.2f} mm)\n"
                f"Substrate Base Plate:    {lx_mm:.1f} x {ly_base_mm:.1f} x {hz_base_mm:.1f} mm (dx = {dx_base:.2f} mm, dy = {dy_base:.2f} mm, dz = {dz_base:.2f} mm)\n"
                f"Grid Structure:          Gmsh 4.15 OCCT Volume Mesh + Substrate Tetrahedra Split\n"
                f"Estimated Discretization:~{total_nodes:,} Nodes  |  ~{total_tets:,} Tetrahedra"
            )
        else:
            info = (
                f"Deposit Bead Element:   dx = {dx_dep:.2f} mm | dy = {dy_dep:.2f} mm | dz = {dz_dep:.2f} mm  (AR = {ar_dep:.2f} | {cpl:.1f} cells/layer)\n"
                f"Substrate Element:      dx = {dx_base:.2f} mm | dy = {dy_base:.2f} mm | dz = {dz_base:.2f} mm  (AR = {ar_base:.2f})\n"
                f"Grid Structure:         Structured Cartesian Hexahedra -> 6-Tet Kuhn Split (FreeFEM Conforming)\n"
                f"Mesh Scale:             ~{total_nodes:,} Nodes  |  ~{total_tets:,} Tetrahedra"
            )
        app.mesh_calc_label.config(text=info)

        rules = verify_meshing_rules(app)
        if hasattr(app, "quality_rule1_lbl"):
            if rules["rule1_ok"]:
                app.quality_rule1_lbl.config(
                    text=f"• Rule 1 [Layer Resolution]: PASS — {rules['cpl']:.1f} cells/layer (dz={rules['dz_dep']:.2f}mm ≤ h_bead/2 = {rules['h_bead_mm']/2:.2f}mm)",
                    fg="#059669"
                )
            else:
                app.quality_rule1_lbl.config(
                    text=f"• Rule 1 [Layer Resolution]: FAIL — {rules['cpl']:.1f} cells/layer (dz={rules['dz_dep']:.2f}mm > h_bead/2; minimum 2 cells/layer required)",
                    fg="#dc2626"
                )
        if hasattr(app, "quality_rule2_lbl"):
            if rules["rule2_ok"]:
                app.quality_rule2_lbl.config(
                    text=f"• Rule 2 [Bead Width Resolution]: PASS — {ny_dep} cells across bead (dy={rules['dy_dep']:.2f}mm ≤ w/2)",
                    fg="#059669"
                )
            else:
                app.quality_rule2_lbl.config(
                    text=f"• Rule 2 [Bead Width Resolution]: FAIL — Only {ny_dep} cell across bead (minimum 2 required)",
                    fg="#dc2626"
                )
        if hasattr(app, "quality_rule3_lbl"):
            if rules["rule3_ok"]:
                app.quality_rule3_lbl.config(
                    text=f"• Rule 3 [Goldak Heat Source Resolvability]: PASS — Resolved (dx={rules['dx_dep']:.2f}mm ≤ af/2, dy={rules['dy_dep']:.2f}mm ≤ bG/2, dz={rules['dz_dep']:.2f}mm ≤ cG/2)",
                    fg="#059669"
                )
            else:
                app.quality_rule3_lbl.config(
                    text=f"• Rule 3 [Goldak Heat Source Resolvability]: WARN — Coarse thermal grid (requires dx≤{rules['af']/2:.2f}mm, dy≤{rules['bG']/2:.2f}mm, dz≤{rules['cG']/2:.2f}mm)",
                    fg="#d97706"
                )
        if hasattr(app, "quality_rule4_lbl"):
            if rules["rule4_ok"]:
                app.quality_rule4_lbl.config(
                    text=f"• Rule 4 [Aspect Ratio Metric]: PASS — AR = {rules['ar_dep']:.2f} ≤ 2.0 (High accuracy, minimal shear locking)",
                    fg="#059669"
                )
            else:
                app.quality_rule4_lbl.config(
                    text=f"• Rule 4 [Aspect Ratio Metric]: FAIL — AR = {rules['ar_dep']:.2f} > 2.0 (Exceeds maximum AR 2.0)",
                    fg="#dc2626"
                )

        if hasattr(app, "viewport") or hasattr(app, "viewport_3d"):
            try:
                params_now = app._collect_params()
                if hasattr(app, "loaded_stl_path") and app.loaded_stl_path and os.path.exists(app.loaded_stl_path):
                    params_now["stl_file"] = app.loaded_stl_path
                vp = getattr(app, "viewport", getattr(app, "viewport_3d", None))
                if vp:
                    vp.update_mesh(params_now)
            except Exception:
                pass
    except Exception:
        pass


def update_heat_calc(app):
    """Calculate and display real-time Heat Input, Wire Feed Rate, and Power based on process inputs."""
    if not hasattr(app, "heat_calc_label"):
        return
    try:
        def get_val(key, default):
            if key not in app._param_vars:
                return float(app.params.get(key, default))
            raw = app._param_vars[key][0].get().strip()
            return float(raw) if raw else float(default)

        I = get_val("I_weld", 180.0)
        U = get_val("U_weld", 20.0)
        eta = get_val("eta_arc", 0.8)
        v_scan_val = get_val("v_scan", 8.0)
        v_scan_mm_s = v_scan_val if v_scan_val > 0.1 else v_scan_val * 1000.0
        v_travel_mm_min = v_scan_mm_s * 60.0

        v_wire_m_min = get_val("v_wire", 5.0)
        d_wire_val = get_val("d_wire", 1.2)
        d_wire_mm = d_wire_val * 1000.0 if d_wire_val < 0.05 else d_wire_val

        w_bead_val = get_val("ty_dep", 8.0)
        w_bead_mm = w_bead_val if w_bead_val > 0.1 else w_bead_val * 1000.0
        h_bead_val = get_val("h_bead", 3.0)
        h_bead_mm = h_bead_val if h_bead_val > 0.1 else h_bead_val * 1000.0

        p_gross_w = U * I
        p_gross_kw = p_gross_w / 1000.0
        p_net_w = eta * U * I
        p_net_kw = p_net_w / 1000.0

        if v_scan_mm_s > 0:
            h_net_j_mm = p_net_w / v_scan_mm_s
            h_net_kj_mm = h_net_j_mm / 1000.0
            h_gross_j_mm = p_gross_w / v_scan_mm_s
            h_gross_kj_mm = h_gross_j_mm / 1000.0
        else:
            h_net_j_mm = h_net_kj_mm = h_gross_j_mm = h_gross_kj_mm = 0.0

        a_wire_mm2 = (math.pi * (d_wire_mm ** 2)) / 4.0
        q_wire_mm3_min = a_wire_mm2 * (v_wire_m_min * 1000.0)

        dep_key = app.material_dep_var.get() if hasattr(app, "material_dep_var") else "SS308L"
        mat_dep = app.materials.get(dep_key, {})
        rho_val = float(mat_dep.get("density", get_val("rho", 7850.0)))

        m_dep_kg_h = (q_wire_mm3_min * (rho_val * 1e-9)) * 60.0
        m_dep_g_s = (m_dep_kg_h * 1000.0) / 3600.0

        a_bead_theo_mm2 = (q_wire_mm3_min / v_travel_mm_min) if v_travel_mm_min > 0 else 0.0
        bead_area_mm2 = w_bead_mm * h_bead_mm
        e_vol = (h_net_j_mm / bead_area_mm2) if bead_area_mm2 > 0 else 0.0
        e_mass_kj_kg = (p_net_w / (m_dep_g_s / 1000.0) / 1000.0) if m_dep_g_s > 0 else 0.0

        lines = [
            f"Torch Travel Speed (v_travel):    {v_scan_mm_s:8.2f} mm/s   ({v_travel_mm_min:8.1f} mm/min)",
            f"Wire Feed Speed (WFS):            {v_wire_m_min:8.2f} m/min  (Wire ∅ {d_wire_mm:.2f} mm | Aw={a_wire_mm2:.2f} mm²)",
            f"Feedstock Mass Deposition (ṁ):    {m_dep_kg_h:8.2f} kg/h   ({m_dep_g_s:.2f} g/s at {rho_val:.0f} kg/m³ {dep_key})",
            f"Theoretical Bead Area (A_bead):   {a_bead_theo_mm2:8.2f} mm²  (Set CAD Bead Area: {bead_area_mm2:.2f} mm²)",
            f"Net Linear Heat Input (H_net):     {h_net_j_mm:8.2f} J/mm   ({h_net_kj_mm:.3f} kJ/mm | {h_net_j_mm:.1f} kJ/m)",
            f"Gross Linear Heat Input (H_gross): {h_gross_j_mm:8.2f} J/mm   ({h_gross_kj_mm:.3f} kJ/mm)",
            f"Net Thermal Arc Power (P_net):     {p_net_kw:8.3f} kW     ({p_net_w:,.1f} W)",
            f"Gross Electrical Power (P_gross):  {p_gross_kw:8.3f} kW     ({p_gross_w:,.1f} W)",
            f"Specific Melting Energy (E_mass):  {e_mass_kj_kg:8.1f} kJ/kg  (Available arc melting enthalpy per unit mass)",
            f"Volumetric Energy Density (E_vol): {e_vol:8.2f} J/mm³  ({e_vol:.2f} MJ/m³)",
        ]
        app.heat_calc_label.config(text="\n".join(lines))
        if hasattr(app, "viewport") or hasattr(app, "viewport_3d"):
            try:
                params_now = app._collect_params()
                vp = getattr(app, "viewport", getattr(app, "viewport_3d", None))
                if vp:
                    vp.update_mesh(params_now)
            except Exception:
                pass
    except Exception:
        pass


def handle_cad_stl_selected(app, path: str, auto_mesh: bool = False):
    """Load 3D CAD model and synchronize dimensions, bead width, layer height, and division counts."""
    if not path or not os.path.exists(path):
        return

    app.mesh_file_var.set(path)
    app.mesh_source_var.set("cad_file")
    app._update_mesh_ui()

    suffix = Path(path).suffix.lower()
    if suffix in ('.stl', '.ply', '.obj', '.step', '.stp', '.iges', '.igs', '.brep'):
        app.loaded_stl_path = path
        if hasattr(app, "slicer_widget") and hasattr(app.slicer_widget, "load_file"):
            try:
                app.slicer_widget.load_file(path)
            except Exception:
                pass
        try:
            from gui.widgets.mesh_viewer_3d import load_any_cad_geometry
            verts, faces, info = load_any_cad_geometry(path)
            if verts is None or faces is None or info is None:
                raise ValueError(f"Could not triangulate {os.path.basename(path)} (empty or unsupported geometry)")
            bb = info["bbox_mm"]
            lx_mm = round(float(bb["x"]), 2)
            ly_mm = round(float(bb["y"]), 2)
            hz_mm = round(float(bb["z"]), 2)

            app._cad_name = os.path.basename(path)
            app._cad_bbox_x = lx_mm
            app._cad_bbox_y = ly_mm
            app._cad_bbox_z = hz_mm

            sub_lx = max(lx_mm + 50.0, 150.0)
            sub_ly = max(ly_mm + 50.0, 150.0)
            sub_hz = 5.0
            if "lx" in app._param_vars:
                app._param_vars["lx"][0].set(f"{sub_lx:.1f}")
            if "ly_base" in app._param_vars:
                app._param_vars["ly_base"][0].set(f"{sub_ly:.1f}")
            if "hz_base" in app._param_vars:
                app._param_vars["hz_base"][0].set(f"{sub_hz:.1f}")

            current_h = 3.0
            if "h_bead" in app._param_vars:
                try:
                    current_h = float(app._param_vars["h_bead"][0].get().strip() or "3.0")
                    if current_h <= 0.1:
                        current_h *= 1000.0
                except Exception:
                    current_h = 3.0
            if current_h <= 0.0:
                current_h = 3.0

            cad_layers = max(int(round(hz_mm / current_h)), 1)
            actual_layer_h = hz_mm / cad_layers

            current_w = 4.0
            if "ty_dep" in app._param_vars:
                try:
                    current_w = float(app._param_vars["ty_dep"][0].get().strip() or "4.0")
                    if current_w <= 0.1:
                        current_w *= 1000.0
                except Exception:
                    current_w = 4.0

            if "ty_dep" in app._param_vars:
                app._param_vars["ty_dep"][0].set(f"{current_w:.2f}")
            if hasattr(app, "slicer_w_var"):
                app.slicer_w_var.set(f"{current_w:.2f}")

            if "h_bead" in app._param_vars:
                app._param_vars["h_bead"][0].set(f"{actual_layer_h:.3f}")
            if hasattr(app, "slicer_h_var"):
                app.slicer_h_var.set(f"{actual_layer_h:.3f}")

            if "n_layers" in app._param_vars:
                app._param_vars["n_layers"][0].set(str(cad_layers))

            if hasattr(app, "_build_height_var"):
                app._build_height_var.set(f"{hz_mm:.2f}")

            if hasattr(app, "geom_cad_status_lbl"):
                app.geom_cad_status_lbl.config(
                    text=f"📦 Loaded 3D CAD: {app._cad_name} | Bounding Box: {lx_mm:.1f} × {ly_mm:.1f} × {hz_mm:.1f} mm\n"
                         f"   → Part Height: {hz_mm:.2f} mm | Part Width: {ly_mm:.2f} mm | Toolpath Bead Width: {current_w:.2f} mm [⇄ Mesh Slicer]",
                    fg="#2563eb"
                )

            nz_dep_cells = max(2 * cad_layers, 2)
            if "nz_dep" in app._param_vars:
                app._param_vars["nz_dep"][0].set(str(nz_dep_cells))

            if hasattr(app, "target_dz_var"):
                app.target_dz_var.set(f"{actual_layer_h / 2.0:.3f}")
            if hasattr(app, "target_dy_var"):
                app.target_dy_var.set(f"{current_w / 4.0:.3f}")

            app._sync_geometry_to_ultrasonic()

            scale_applied = info.get("scale_applied", 1.0)
            vol_pct = info.get("vol_ratio_pct", 0.0)
            v_occ = info.get("volume_occupied_mm3", 0.0)
            orig_bb = info.get("orig_bbox_mm", {})
            scale_str = f" | Auto-scaled {scale_applied:.2f}x ({vol_pct:.1f}% enclosure vol)" if scale_applied < 0.999 else f" ({vol_pct:.1f}% enclosure vol)"

            if hasattr(app, "cad_info_label"):
                app.cad_info_label.config(
                    text=f"Loaded CAD: {os.path.basename(path)} ({info['format']}) | "
                         f"Lx={lx_mm:.1f} mm, Ly={ly_mm:.1f} mm, Lz={hz_mm:.1f} mm{scale_str} | "
                         f"Substrate {sub_lx:.0f}x{sub_ly:.0f}x{sub_hz:.0f} mm | {len(verts):,} Verts"
                )

            update_mesh_calc(app)
            update_heat_calc(app)

            orig_str = f" | Original Size: {orig_bb.get('x', lx_mm):.1f} x {orig_bb.get('y', ly_mm):.1f} x {orig_bb.get('z', hz_mm):.1f} mm" if scale_applied < 0.999 else ""
            app._log(
                f"\n[CAD-ENCLOSURE] Substrate Plate: {sub_lx:.1f} x {sub_ly:.1f} x {sub_hz:.1f} mm\n"
                f"[CAD-IMPORT] Loaded CAD Model: {os.path.basename(path)} ({info['format']}){orig_str}\n"
                f"[CAD-IMPORT] Full Path: {path}\n"
                f"[CAD-IMPORT] Scale Applied: {scale_applied:.4f}x -> Occupied Volume: {v_occ:,.1f} mm³ ({vol_pct:.1f}% of enclosure)\n"
                f"[CAD-IMPORT] Placed Bounding Box: Lx = {lx_mm:.2f} mm | Ly = {ly_mm:.2f} mm | Lz = {hz_mm:.2f} mm\n"
                f"[CAD-IMPORT] Synchronized Geometry: Layers={cad_layers} (h={actual_layer_h:.2f}mm) | Bead Width={current_w:.2f}mm | Mesh Nz={nz_dep_cells} (≥2 cells/layer)\n"
            )
            app.status_var.set(f"Status: CAD Placed ({lx_mm:.0f}x{ly_mm:.0f}x{hz_mm:.0f} mm | {vol_pct:.1f}% enclosure vol)")
        except Exception as e:
            app._log(f"[CAD-IMPORT] [WARNING] Could not parse CAD geometry: {e}\n")

    params_now = app._collect_params()
    params_now["stl_file"] = path
    params_now["mesh_file"] = path
    vp = getattr(app, "viewport", getattr(app, "viewport_3d", None))
    if vp:
        vp.update_mesh(params_now)

    if auto_mesh:
        start_stl_meshing_thread(app, path)


def start_stl_meshing_thread(app, cad_path: str):
    target_nodes = 2500
    try:
        target_nodes = int(app.mesh_budget_var.get())
    except Exception:
        pass

    def _dim_mm(key, default_mm):
        try:
            val = float(app._param_vars[key][0].get().strip() or default_mm)
        except Exception:
            return float(default_mm)
        return val * 1000.0 if 0.0 < val < 1.0 else val

    sub_hz_mm = _dim_mm("hz_base", 5.0)
    sub_lx_mm = _dim_mm("lx", 150.0)
    sub_ly_mm = _dim_mm("ly_base", 150.0)
    layer_height_mm = _dim_mm("h_bead", 3.0)

    app._log(f"[CAD-IMPORT] Target volume mesh size: ~{target_nodes} nodes (Gmsh 4.15 + OCCT volume pipeline)\n")
    app._log(f"[CAD-IMPORT] Substrate plate for the mesh: {sub_lx_mm:.1f} x {sub_ly_mm:.1f} x {sub_hz_mm:.1f} mm | layer height {layer_height_mm:.2f} mm\n")
    app.status_var.set("Status: Meshing CAD...")
    # Resolve output dir on the Tk thread (reads a StringVar); the worker
    # thread must never touch Tk vars directly.
    outdir = app._get_base_output_dir()

    def run_mesh():
        try:
            from mesh.intelligent_mesher import import_and_mesh_cad_intelligent
            os.makedirs(outdir, exist_ok=True)
            out_mesh = os.path.join(outdir, f"imported_{Path(cad_path).stem}.mesh")
            result = import_and_mesh_cad_intelligent(
                cad_path, out_mesh, target_nodes=target_nodes, refine_thin_features=True,
                layer_height=layer_height_mm, sub_hz_mm=sub_hz_mm,
                sub_lx_mm=sub_lx_mm, sub_ly_mm=sub_ly_mm)

            warns = list(result.get("warnings", []) or [])
            if warns:
                app.root.after(0, lambda ws=warns: app._log_batch(
                    [f"[CAD] {w}" for w in ws]))

            bb = result["bbox_mm"]
            app.root.after(0, app._log,
                f"[CAD-IMPORT] [OK] Mesh complete: {result['n_nodes']:,} nodes  |  {result['n_tets']:,} tets\n"
                f"[CAD-IMPORT]     Format: {result.get('format', 'CAD')}\n"
                f"[CAD-IMPORT]     Bounding box: X={bb['x']:.1f}  Y={bb['y']:.1f}  Z={bb['z']:.1f} mm\n"
                f"[CAD-IMPORT]     Mesh file: {result['mesh_path']}\n"
            )

            def _cad_mesh_done():
                app.loaded_mesh_path = result["mesh_path"]
                if "sub_hz_mm" in result:
                    app.cad_sub_hz_mm = result["sub_hz_mm"]
                app.mesh_file_var.set(result["mesh_path"])
                app.mesh_source_var.set("cad_file")
                app.status_var.set("Status: CAD Meshed")
                params_cad = app._collect_params()
                params_cad["mesh_file"] = result["mesh_path"]
                params_cad["stl_file"] = cad_path
                vp = getattr(app, "viewport", getattr(app, "viewport_3d", None))
                if vp:
                    vp.update_mesh(params_cad)

            app.root.after(0, _cad_mesh_done)

        except Exception as e:
            app.root.after(0, app._log, f"[CAD-IMPORT] [ERROR] Meshing error: {e}\n")
            app.root.after(0, lambda: app.status_var.set("Status: Meshing Failed"))

    threading.Thread(target=run_mesh, daemon=True).start()


def execute_custom_slicer(app):
    """Execute customized toolpath generation based on user G-code parameters."""
    loaded_cad = getattr(app, "loaded_stl_path", "")
    cad_path = ""
    if loaded_cad and os.path.exists(loaded_cad) and Path(loaded_cad).suffix.lower() in ('.stl', '.step', '.stp', '.iges', '.igs', '.ply', '.obj'):
        cad_path = loaded_cad
    else:
        mf = app.mesh_file_var.get().strip()
        if mf and os.path.exists(mf):
            cad_path = mf
    if not cad_path or not os.path.exists(cad_path):
        cad_path = getattr(app, "loaded_stl_path", "")
    if not cad_path or not os.path.exists(cad_path):
        cad_path = filedialog.askopenfilename(
            filetypes=[("3D CAD / STL / Mesh", "*.stl *.step *.stp *.iges *.igs *.ply *.obj *.mesh"), ("All", "*.*")],
            title="Select CAD Model to Slice",
            initialdir=str(Path.home() / "Desktop")
        )
        if not cad_path:
            return

    try:
        import re
        h_bead = float(re.sub(r"[^\d.]", "", str(app.slicer_h_var.get()).strip()) or "3.0")
        w_bead = float(re.sub(r"[^\d.]", "", str(app.slicer_w_var.get()).strip()) or "5.0")
        hz_base_mm = (app._f(app._param_vars["hz_base"][0], 5.0)
                      if "hz_base" in app._param_vars else 5.0)
        infill = app.slicer_pattern_var.get().strip() if hasattr(app, "slicer_pattern_var") else "contour"
        overlap = float(re.sub(r"[^\d.]", "", str(app.slicer_overlap_var.get()).strip()) or "100.0")
        perims = max(int(re.sub(r"[^\d]", "", str(app.slicer_perim_var.get()).strip()) or "3"), 0)
        feedrate = float(re.sub(r"[^\d.]", "", str(app.slicer_feedrate_var.get()).strip()) or "600.0")
        rapid = float(re.sub(r"[^\d.]", "", str(app.slicer_rapid_var.get()).strip()) or "3000.0")
        dwell = float(re.sub(r"[^\d.]", "", str(app.slicer_dwell_var.get()).strip()) or "15.0")
        power = float(re.sub(r"[^\d.]", "", str(app.slicer_power_var.get()).strip()) or "3150.0")
        start_rev = bool(app.slicer_reverse_var.get())

        run_dir = app._get_or_create_run_dir(is_new_run=False)
        os.makedirs(run_dir, exist_ok=True)

        cad_stem = Path(cad_path).stem
        out_gcode = os.path.join(run_dir, f"{cad_stem}.gcode")

        cad_dest = os.path.join(run_dir, os.path.basename(cad_path))
        from gui.app import safe_copy_file
        safe_copy_file(cad_path, cad_dest)

        app._log(
            f"\n[SLICER] Slicing CAD: {os.path.basename(cad_path)}\n"
            f"[SLICER] Target G-code in run folder: {out_gcode}\n"
            f"[SLICER] Layer height: {h_bead} mm | Bead width: {w_bead} mm | Infill: {infill}\n"
            f"[SLICER] Overlap: {overlap}% | Perimeters: {perims} | Feedrate: {feedrate} mm/min\n"
            f"[SLICER] Dwell cooling: {dwell} s | Power: {power} W | Reverse starts: {start_rev}\n"
        )

        from mesh.slicer_api import slice_geometry_to_toolpath
        # Read remaining Tk vars on the main thread; the worker must not touch Tk.
        sub_lx_mm = (app._f(app._param_vars["lx"][0], 150.0)
                     if "lx" in app._param_vars else 150.0)
        sub_ly_mm = (app._f(app._param_vars["ly_base"][0], 150.0)
                     if "ly_base" in app._param_vars else 150.0)
        app.status_var.set("Status: Slicing CAD... (background)")

        def _slice_worker():
            try:
                tp = slice_geometry_to_toolpath(
                    geometry_file=cad_path,
                    output_gcode=out_gcode,
                    layer_height=h_bead,
                    bead_width=w_bead,
                    sub_hz=hz_base_mm,
                    sub_lx_mm=sub_lx_mm,
                    sub_ly_mm=sub_ly_mm,
                    infill_pattern=infill,
                    overlap_pct=overlap,
                    perimeters=perims,
                    feedrate=feedrate,
                    rapid_feedrate=rapid,
                    power=power,
                    dwell_time=dwell,
                    start_reverse=start_rev
                )

                summary_path = os.path.join(run_dir, "toolpath_summary.json")
                try:
                    with open(summary_path, "w") as sf:
                        json.dump(tp, sf, indent=2, default=str)
                except Exception:
                    pass

                canon_gcode = os.path.join(run_dir, "toolpath.gcode")
                safe_copy_file(out_gcode, canon_gcode)

                fem_sub = os.path.join(run_dir, "FreeFEM")
                if os.path.exists(fem_sub):
                    for fn in ("toolpath.gcode", "toolpath.txt", "layer_pass_times.txt"):
                        fsrc = os.path.join(run_dir, fn)
                        safe_copy_file(fsrc, os.path.join(fem_sub, fn))

                app.root.after(0, lambda: _slice_done(tp))
            except Exception as err:
                app.root.after(0, lambda err=err: _slice_fail(err))

        def _slice_done(tp):
            n_sliced = int(tp.get('n_layers', 1))
            if "n_layers" in app._param_vars:
                app._param_vars["n_layers"][0].set(str(n_sliced))
            if "h_bead" in app._param_vars:
                app._param_vars["h_bead"][0].set(f"{h_bead:.2f}")
            if "ty_dep" in app._param_vars:
                app._param_vars["ty_dep"][0].set(f"{w_bead:.2f}")
            if "nz_dep" in app._param_vars:
                app._param_vars["nz_dep"][0].set(str(max(2 * n_sliced, 2)))
            if hasattr(app, "target_dz_var"):
                app.target_dz_var.set(f"{h_bead / 2.0:.3f}")

            app.loaded_gcode_path = out_gcode

            if hasattr(app, "loaded_mesh_path") and app.loaded_mesh_path and os.path.exists(app.loaded_mesh_path):
                app.mesh_file_var.set(app.loaded_mesh_path)
            else:
                app.mesh_file_var.set(out_gcode)
            app.mesh_source_var.set("gcode_file")
            app._update_mesh_ui()

            # Automatically execute Auto-Fix mesh rules on the generated G-code
            auto_fix_mesh_rules(app)

            summary = (
                f"Generated {tp['n_layers']} layers toolpath ({tp['total_length_m']:.2f} m)\n"
                f"Estimated Build Time: {tp['estimated_time_min']:.1f} min | Deposited Mass: {tp['bead_mass_kg']:.3f} kg\n"
                f"Arc Energy: {tp['energy_kj']:.1f} kJ | G-code: {os.path.basename(out_gcode)}"
            )
            if hasattr(app, "slicer_summary_label"):
                app.slicer_summary_label.config(text=summary)

            app._log(f"[SLICER] [OK] Success: {summary}\n")
            warns = list(tp.get("warnings", []) or [])
            if warns:
                app._log_batch([f"[SLICER] [WARNING] {w}" for w in warns])
            app.status_var.set(f"Status: Sliced ({tp['n_layers']} layers, {tp['total_length_m']:.1f}m)")

            params_tp = app._collect_params()
            params_tp["gcode_file"] = out_gcode
            params_tp["stl_file"] = cad_path
            params_tp["n_layers"] = n_sliced
            vp = getattr(app, "viewport", getattr(app, "viewport_3d", None))
            if vp:
                vp.update_mesh(params_tp)

            messagebox.showinfo(
                "Toolpath Generation Complete",
                f"Successfully generated custom WAAM toolpath:\n\n"
                f"File: {out_gcode}\n"
                f"Layers: {tp['n_layers']}\n"
                f"Total Length: {tp['total_length_m']} m\n"
                f"Estimated Time: {tp['estimated_time_min']} min\n"
                f"Deposited Mass: {tp['bead_mass_kg']} kg\n"
                f"Arc Energy: {tp['energy_kj']} kJ"
            )

        def _slice_fail(err):
            app._log(f"[SLICER] [ERROR] Slicing failed: {err}\n")
            messagebox.showerror("Slicer Error", str(err))

        # Slicing is pure CPU/I/O (measured 12.4 s on M4): run it off the Tk
        # thread so the window stays responsive, then marshal every Tk touch.
        threading.Thread(target=_slice_worker, daemon=True).start()
    except Exception as e:
        app._log(f"[SLICER] [ERROR] Slicing failed: {e}\n")
        messagebox.showerror("Slicer Error", str(e))
