#!/usr/bin/env python3
"""
Complete Simulation Runner for sphere_R40mm with Contour Infill, Al 1xxxx, 150A/15V, 15mm Substrate
===================================================================================================
Executes the full digital-twin pipeline:
  1. Conformal 3D volume meshing of sphere_R40mm on 15 mm substrate (watertight boolean union)
  2. Automatic mesh boundary orientation healing (GenericMesh.hpp:949 outward normal guarantee)
  3. 3D curved geometry slicing with contour infill (2 perimeters + concentric offset loops)
  4. Variational FreeFEM++ script synthesis with MUMPS direct solver and Pure Al (Al1xxx) metallurgy
  5. Multi-physics thermal-mechanical solving (heat transfer, fluid-like remelting, residual stresses)
  6. Automated postprocessing (temperature fields, cooling rates, warpage, plots, HTML report)
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

# Framework root
_dir = Path(__file__).resolve().parent
ROOT_DIR = _dir if (_dir / "core").exists() else _dir.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.platform_adapter import find_freefem_serial, configure_parallel_environment
from core.solver_diagnostics import FreeFEMDiagnosticsEngine
from mesh.stl_pipeline import stl_to_freefem_mesh, reorient_mesh_boundary_triangles
from mesh.slicer_api import slice_geometry_to_toolpath
from codegen.edp_builder import EDPBuilder
from postprocess.plot_generator import generate_all_plots
from core.postprocess.output_manager import (
    generate_run_summary,
    generate_paraview_loader_script,
    generate_enhanced_html_report,
)


def main():
    print("=" * 80)
    print(" WAAM DIGITAL TWIN COMPLETE RUN: SPHERE R40mm WITH CONTOUR INFILL & 15mm SUBSTRATE")
    print("=" * 80)

    # 1. Output directories
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    case_dir = ROOT_DIR / "waam_output" / f"{timestamp}_sphere_r40mm_contour_al1xxx"
    fem_dir = case_dir / "FreeFEM"
    vis_dir = fem_dir / "visual_outputs"
    os.makedirs(vis_dir, exist_ok=True)

    cad_file = ROOT_DIR / "stl" / "sphere_R40mm.stl"
    if not cad_file.exists():
        raise FileNotFoundError(f"CAD geometry not found at: {cad_file}")

    print(f"\n[1/6] Geometry & Material Specifications:")
    print(f"      • Geometry:         {cad_file.name} (R = 40 mm, Height = 80 mm)")
    print(f"      • Substrate:        150 x 150 x 15.0 mm plate (15 mm thickness)")
    print(f"      • Wire Feedstock:   Pure Al (Al1xxx)")
    print(f"      • Substrate Alloy:  Pure Al (Al1xxx)")
    print(f"      • Arc Parameters:   150.0 A, 15.0 V (eta = 0.85, Net Power = 1912.5 W)")
    print(f"      • Toolpath Slicing: contour_infill (2 perimeters + concentric infill)")
    print(f"      • Output Directory: {case_dir}")

    # 2. Conformal Volume Meshing
    print(f"\n[2/6] Generating 3D Conformal Volume Mesh with 15 mm Substrate...")
    mesh_out = fem_dir / "sphere_r40mm_conformal.mesh"
    t0_mesh = time.time()
    mesh_res = stl_to_freefem_mesh(
        stl_path=str(cad_file),
        output_mesh_path=str(mesh_out),
        target_nodes=2200,
        layer_height=4.0,
        sub_hz_mm=15.0,
        sub_lx_mm=150.0,
        sub_ly_mm=150.0
    )
    # Ensure outward orientation
    n_reoriented = reorient_mesh_boundary_triangles(str(mesh_out))
    dt_mesh = time.time() - t0_mesh
    print(f"      ✓ Conformal mesh generated in {dt_mesh:.2f}s:")
    print(f"        Nodes: {mesh_res['n_nodes']:,} | Tetrahedra: {mesh_res['n_tets']:,}")
    print(f"        Boundary Labels: {mesh_res.get('labels')} (Orientation Verified: {n_reoriented} inverted facets healed)")

    # 3. Slicing with Contour Infill + 2 Perimeters
    print(f"\n[3/6] Slicing CAD Geometry (contour_infill, 2 walls, dz=4mm)...")
    gcode_path = fem_dir / "toolpath.gcode"
    t0_slice = time.time()
    slice_res = slice_geometry_to_toolpath(
        geometry_file=str(cad_file),
        output_gcode=str(gcode_path),
        layer_height=4.0,
        bead_width=8.0,
        sub_hz=15.0,
        sub_lx_mm=150.0,
        sub_ly_mm=150.0,
        infill_pattern="contour_infill",
        perimeters=2,
        feedrate=600.0,
        rapid_feedrate=3000.0,
        dwell_time=0.0
    )
    dt_slice = time.time() - t0_slice
    print(f"      ✓ Slicing completed in {dt_slice:.2f}s:")
    print(f"        Layers: {slice_res['n_layers']} | Toolpath Points: {slice_res['n_points']:,}")
    print(f"        Toolpath txt: {slice_res['toolpath_path']}")

    # Copy toolpath and layer pass times to fem_dir
    tp_txt_src = Path(slice_res['toolpath_path'])
    lpt_txt_src = Path(slice_res['layer_times_path'])
    tp_txt_dst = fem_dir / "toolpath.txt"
    lpt_txt_dst = fem_dir / "layer_pass_times.txt"
    if tp_txt_src.resolve() != tp_txt_dst.resolve():
        shutil.copy2(tp_txt_src, tp_txt_dst)
    if lpt_txt_src.resolve() != lpt_txt_dst.resolve():
        shutil.copy2(lpt_txt_src, lpt_txt_dst)

    # 4. Multi-Physics Parameters & EDP Synthesis
    print(f"\n[4/6] Synthesizing Multi-Physics Variational EDP Script...")
    params = {
        "mesh_source": "cad_file",
        "mesh_file": str(mesh_out),
        "stl_file": str(cad_file),
        "gcode_file": str(gcode_path),
        "material_base": "Pure Al (Al1xxx)",
        "material_dep": "Pure Al (Al1xxx)",
        "I_weld": 150.0,
        "U_weld": 15.0,
        "eta_arc": 0.85,
        "v_scan": 0.010,  # 10 mm/s = 600 mm/min (SI m/s)
        "v_wire": 5.0,
        "d_wire": 1.2,
        "lx": 0.150,
        "ly_base": 0.150,
        "hz_base": 0.015,  # 15 mm substrate
        "ty_dep": 0.008,
        "h_bead": 0.004,
        "h_bead_first": 0.004,
        "h_bead_subseq": 0.004,
        "remelt_ratio": 1.0,  # 100% fusion across layers
        "n_layers": slice_res['n_layers'],
        "t_wait": 0.0,
        "solver": "MUMPS",
        "dt_weld": 0.5,
        "enable_radiation": True,
        "enable_j2_plasticity": True,
        "output_dir": str(fem_dir) + "/"
    }

    builder = EDPBuilder(params)
    edp_code = builder.build()
    edp_file = fem_dir / "waam_simulation.edp"
    with open(edp_file, "w", encoding="utf-8") as f:
        f.write(edp_code)

    params_json = fem_dir / "parameters.json"
    with open(params_json, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2)

    print(f"      ✓ Script compiled: {edp_file.name} ({len(edp_code.splitlines())} lines)")
    print(f"      ✓ Parameters saved to: {params_json.name}")

    # 5. Execute Solver with Diagnostics & Auto-Healing
    ff_bin = find_freefem_serial()
    if not ff_bin:
        raise RuntimeError("No FreeFem++ executable found in environment or default paths.")

    env = configure_parallel_environment(n_threads=8)
    sim_log_file = fem_dir / "sim.log"
    print(f"\n[5/6] Launching FreeFEM++ Multi-Physics Solver:")
    print(f"      • Binary:  {ff_bin}")
    print(f"      • Log:     {sim_log_file}")
    print(f"      • Threads: 8")
    print(f"      • Solving transient thermal conduction + Goldak source + J2 elasto-plasticity...")

    cmd = [ff_bin, str(edp_file.resolve()), str(fem_dir.resolve()) + "/"]
    t0_solve = time.time()

    with open(sim_log_file, "w", encoding="utf-8") as log_f:
        log_f.write("=" * 80 + "\n")
        log_f.write("WAAM SIMULATION LOG — SPHERE R40mm CONTOUR INFILL\n")
        log_f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_f.write("=" * 80 + "\n\n")
        log_f.flush()

        proc = subprocess.Popen(
            cmd,
            cwd=str(fem_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        layer_count = 0
        for line in proc.stdout:
            log_f.write(line)
            log_f.flush()
            if "--- Layer" in line:
                print(f"        {line.strip()}")
            elif "FINAL COOLING" in line:
                print(f"        -> {line.strip()}")
            elif "MECHANICAL STAGE" in line:
                print(f"        -> {line.strip()}")
            elif "Tmax=" in line and "ws=" in line:
                # Print periodic progress
                pass

        proc.wait()
        rc = proc.returncode

    dt_solve = time.time() - t0_solve

    # Diagnostics check
    if rc != 0:
        diag = FreeFEMDiagnosticsEngine.parse_log(sim_log_file, edp_file)
        print("\n" + "=" * 80)
        print(f" [SOLVER ERROR] {diag.summary}")
        print("=" * 80)
        print(f" Category:   {diag.category} (Exit Code: {diag.error_code})")
        print(f" Root Cause: {diag.root_cause}")
        print(f" Remediation:{diag.remediation_suggestion}")
        print("=" * 80)

        if diag.is_auto_healable:
            print("\n [AUTO-HEAL] Executing automated healing...")
            healed, msg = FreeFEMDiagnosticsEngine.auto_heal(diag, fem_dir, params)
            if healed:
                print(f" [AUTO-HEAL] ✓ {msg}")
                print(" [AUTO-HEAL] Re-running solver with healed mesh/parameters...")
                p2 = subprocess.run(cmd, cwd=str(fem_dir), env=env, capture_output=True, text=True)
                with open(sim_log_file, "a", encoding="utf-8") as f_a:
                    f_a.write("\n--- RETRY RUN AFTER AUTO-HEAL ---\n" + p2.stdout)
                rc = p2.returncode

    if rc != 0:
        raise RuntimeError(f"FreeFem++ simulation failed with return code {rc}. See {sim_log_file}")

    print(f"\n      ✓ Solver completed successfully in {dt_solve:.2f}s (Return Code: 0).")

    # 6. Postprocessing: 2D Plots, 3D Loader, and Production Report
    print(f"\n[6/6] Generating Engineering Results, Analysis Plots, and Technical Report...")
    plots = generate_all_plots(str(fem_dir))
    pv_script = generate_paraview_loader_script(str(fem_dir))
    summary = generate_run_summary(str(fem_dir), params, return_code=0)
    report_html = generate_enhanced_html_report(str(fem_dir), params, summary, plots)

    # Top-level copies for easy access
    shutil.copy2(sim_log_file, case_dir / "sim.log")
    if report_html and os.path.exists(report_html):
        shutil.copy2(report_html, case_dir / "report.html")

    print("\n" + "=" * 80)
    print(" WAAM DIGITAL TWIN SIMULATION COMPLETED WITH FULL SUCCESS")
    print("=" * 80)
    print(f" • Run Directory:        {case_dir}")
    print(f" • Executive Summary:    {fem_dir / 'run_summary.json'}")
    print(f" • Publication Plots:    {len(plots)} figures generated in {fem_dir / 'plots'}")
    print(f" • 3D Visual Fields:     {pv_script}")
    print(f" • Engineering Report:   {case_dir / 'report.html'}")
    print(f" • Native Log:           {case_dir / 'sim.log'}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
