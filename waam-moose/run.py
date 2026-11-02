#!/usr/bin/env python3
"""
WAAM-MOOSE Multi-Physics Simulation Framework — Main Entry Point
================================================================
Autonomous workflow driver for the MOOSE-based Wire Arc Additive
Manufacturing simulation backend.

Usage:
  python3 run.py                 # Launch interactive MOOSE GUI
  python3 run.py --stl <file>    # FULL PIPELINE: slice -> mesh -> convert to exo -> build .i -> solve -> report
  python3 run.py --cli           # Run standard benchmark simulation in headless CLI mode
  python3 run.py --validate      # Run the verification & unit test suite
  python3 run.py --slice <file>  # Slice an STL/STEP file to G-code toolpath & schedule
  python3 run.py --mesh <file>   # Conformal Gmsh volume mesh generation
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_GUI = _HERE / "gui"
if str(_GUI) not in sys.path:
    sys.path.insert(0, str(_GUI))

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[@-Z\\-_]")


def _strip_ansi(line: str) -> str:
    """Remove terminal escape sequences so log files stay clean."""
    return _ANSI_RE.sub("", line)


def find_moose_binary() -> str:
    """Locate the waam_moose-opt application executable."""
    env_home = os.environ.get("WAAM_MOOSE_HOME")
    candidates = [
        Path(env_home) / "waam_moose" / "waam_moose-opt" if env_home else None,
        Path(env_home) / "waam_moose-opt" if env_home else None,
        _HERE / "waam_moose" / "waam_moose-opt",
        _HERE / "waam_moose-opt",
        Path.home() / "projects" / "moose" / "modules" / "combined" / "combined-opt",
    ]
    for cand in candidates:
        if cand and cand.is_file() and os.access(cand, os.X_OK):
            return str(cand.resolve())
    return ""


def run_command_with_tee(cmd: list, cwd: str, log_path: str, env: dict = None) -> int:
    """
    Run command while streaming unbuffered stdout/stderr to terminal AND writing
    to log_path in real time.
    """
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write(f"{'='*80}\n")
        log_f.write(f"EXECUTION: {' '.join(str(c) for c in cmd)}\n")
        log_f.write(f"CWD:       {cwd}\n")
        log_f.write(f"START:     {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_f.write(f"{'='*80}\n\n")
        log_f.flush()

        use_script = shutil.which("script") is not None and sys.platform != "win32"
        if use_script:
            if sys.platform == "darwin":
                exec_cmd = ["script", "-q", "/dev/null"] + [str(c) for c in cmd]
            else:
                joined = " ".join('"%s"' % str(c) if " " in str(c) else str(c) for c in cmd)
                exec_cmd = ["script", "-q", "-c", joined, "/dev/null"]
        else:
            exec_cmd = [str(c) for c in cmd]

        proc = subprocess.Popen(
            exec_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=env or os.environ.copy(),
            bufsize=1
        )
        try:
            for raw in getattr(proc, "stdout", []) or []:
                clean_line = _strip_ansi(raw.replace("\r", ""))
                while clean_line and ord(clean_line[0]) < 32 and clean_line[0] not in "\n\t":
                    clean_line = clean_line[1:]
                sys.stdout.write(clean_line)
                sys.stdout.flush()
                log_f.write(clean_line)
                log_f.flush()
            proc.wait()
        except KeyboardInterrupt:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            log_f.write("\n[INTERRUPTED] terminated by user\n")
            log_f.flush()
            return 130

        rc = proc.returncode
        log_f.write(f"\n[FINISHED] Process exited with code {rc} at "
                    f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_f.flush()
        return rc


def _point_latest(base_waam_output: Path, case_outdir: Path) -> None:
    """Make <base>/latest resolve to case_outdir."""
    latest = base_waam_output / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(case_outdir.name)
        return
    except Exception:
        pass
    try:
        with open(latest, "w", encoding="utf-8") as f:
            f.write(str(case_outdir) + "\n")
    except Exception:
        pass


def run_full_pipeline(geometry_file: str, args, base_waam_output: Path) -> int:
    """
    End-to-end pipeline: slice -> toolpath -> mesh -> convert to exo -> build .i -> solve -> audit -> plots.
    """
    from mesh.slicer_api import slice_geometry_to_toolpath
    from mesh.stl_pipeline import stl_to_freefem_mesh
    from mesh.medit_to_exodus import medit_to_exodus
    from codegen.edp_builder import EDPBuilder
    from codegen.moose_builder import main as build_moose_input

    geo = Path(geometry_file).resolve()
    if not geo.exists():
        print(f"[ERROR] Geometry file not found: {geo}")
        return 1

    now_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    case_outdir = base_waam_output / now_ts
    moose_outdir = case_outdir / "moose"
    mesh_outdir = case_outdir / "mesh"
    case_outdir.mkdir(parents=True, exist_ok=True)
    moose_outdir.mkdir(parents=True, exist_ok=True)
    mesh_outdir.mkdir(parents=True, exist_ok=True)

    print(f"\n[WAAM-MOOSE] Case directory: {case_outdir}")

    # 1. Slicing
    layer_height = float(getattr(args, "layer_height", 3.0) or 3.0)
    bead_width = float(getattr(args, "bead_width", 8.0) or 8.0)
    gcode_path = case_outdir / "toolpath.gcode"
    slice_hz = float(getattr(args, "hz_base_mm", 0.0) or 0.0) or 5.0
    print(f"[1/6] Slicing {geo.name} (layer_height={layer_height} mm, bead_width={bead_width} mm) ...")
    try:
        slice_res = slice_geometry_to_toolpath(
            str(geo), str(gcode_path),
            layer_height=layer_height, bead_width=bead_width,
            sub_hz=slice_hz)
    except Exception as ex:
        print(f"[ERROR] Slicing failed: {ex}")
        return 1

    n_layers_sliced = int(slice_res.get("n_layers", 0))
    print(f"       {n_layers_sliced} layers, {slice_res.get('n_points', 0)} points generated.")

    toolpath_txt = gcode_path.with_suffix(".txt")
    layer_times_src = gcode_path.with_suffix(".layer_times.txt")
    layer_times_dst = case_outdir / "layer_pass_times.txt"
    if layer_times_src.exists():
        shutil.copy2(layer_times_src, layer_times_dst)

    # 2. Meshing
    mesh_path = mesh_outdir / f"{geo.stem}.mesh"
    existing_mesh = getattr(args, "mesh", None)
    if existing_mesh and Path(existing_mesh).exists():
        shutil.copy2(existing_mesh, mesh_path)
        print(f"[2/6] Using provided mesh {existing_mesh} -> {mesh_path}")
    else:
        print(f"[2/6] Meshing {geo.name} with Gmsh (substrate + deposit conforming volume) ...")
        try:
            target_nodes = int(getattr(args, "target_nodes", 0) or 2000)
            mesh_res = stl_to_freefem_mesh(str(geo), str(mesh_path), target_nodes=target_nodes,
                                           layer_height=layer_height, sub_hz_mm=slice_hz)
            print(f"       Conforming volume mesh: {mesh_res.get('n_nodes', '?')} nodes, "
                  f"{mesh_res.get('n_tets', '?')} tets.")
        except Exception as ex:
            print(f"[ERROR] Meshing failed: {ex}")
            return 1

    # 3. Parameters configuration
    p = EDPBuilder.default_params()
    p["output_dir"] = str(case_outdir.resolve()) + "/"
    p["mesh_source"] = "cad_file"
    p["mesh_file"] = str(mesh_path)
    p["h_bead"] = layer_height / 1000.0
    p["h_bead_first"] = layer_height / 1000.0
    p["h_bead_subseq"] = layer_height / 1000.0
    p["hz_base"] = slice_hz / 1000.0
    if n_layers_sliced > 0:
        p["n_layers"] = n_layers_sliced
    p["enable_mechanical"] = bool(getattr(args, "mechanical", False)) or bool(getattr(args, "springback", False))
    p["enable_freefem_clip"] = True
    p["use_lumped_mass"] = False
    if getattr(args, "springback", False):
        p["springback_solve"] = True
    if getattr(args, "adaptive_dt", False):
        p["adaptive_dt"] = True
    if getattr(args, "ultrasonic", False):
        p["enable_ultrasonic"] = True
    if getattr(args, "dt_weld", None) is not None:
        p["dt_weld"] = float(args.dt_weld)
    if getattr(args, "t_wait", None) is not None:
        p["t_wait"] = float(args.t_wait)
    if getattr(args, "dt_wait", None) is not None:
        p["dt_wait"] = float(args.dt_wait)
    if getattr(args, "dt_cool", None) is not None:
        p["dt_cool"] = float(args.dt_cool)
    if getattr(args, "n_cool_steps", None) is not None:
        p["n_cool_steps"] = int(args.n_cool_steps)
    if getattr(args, "material_base", None) is not None:
        p["material_base"] = str(args.material_base)
    if getattr(args, "material_dep", None) is not None:
        p["material_dep"] = str(args.material_dep)
    (case_outdir / "parameters.json").write_text(json.dumps(p, indent=2))

    # 4. Convert mesh to Exodus II
    print(f"[3/6] Converting mesh to Exodus II CDF-2 (.exo) ...")
    exo_path = moose_outdir / "mesh.exo"
    try:
        medit_to_exodus(str(mesh_path), str(exo_path))
        print(f"       Wrote {exo_path.name}")
    except Exception as ex:
        print(f"[ERROR] Exodus conversion failed: {ex}")
        return 1

    # 5. Build MOOSE input (.i)
    print(f"[4/6] Building waam_moose.i input deck ...")
    try:
        ret = build_moose_input(["--run-dir", str(case_outdir)])
        if ret != 0:
            print(f"[ERROR] MOOSE builder exited with status {ret}")
            return ret
    except Exception as ex:
        print(f"[ERROR] MOOSE builder failed: {ex}")
        return 1

    # 6. Execute MOOSE
    moose_bin = find_moose_binary()
    if not moose_bin:
        print(f"[ERROR] Could not find 'waam_moose-opt' executable. "
              f"Set WAAM_MOOSE_HOME or build waam_moose app.")
        return 2

    moose_input = moose_outdir / "waam_moose.i"
    log_path = moose_outdir / "waam_moose.log"
    cmd = [moose_bin, "-i", str(moose_input)]
    ranks = max(1, int(getattr(args, "ranks", 1) or 1))
    if ranks > 1:
        cmd = ["mpirun", "-np", str(ranks)] + cmd

    print(f"[5/6] Executing MOOSE solve ({' '.join(cmd)}) ...")
    rc = run_command_with_tee(cmd, cwd=str(moose_outdir), log_path=str(log_path))
    if rc != 0:
        print(f"[WARNING] MOOSE solve exited with code {rc}. Check log: {log_path}")

    # 7. Post-process & Audit
    print(f"[6/6] Running energy audit, generating plots & executive report ...")
    try:
        from codegen.moose_audit import main as audit_main
        from codegen.moose_plots import main as plots_main
        from postprocess.report_generator import generate_report
        audit_main(["--run-dir", str(case_outdir), "--gates"])
        plots_main(["--run-dir", str(case_outdir)])
        generate_report(case_outdir)
    except Exception as ex:
        print(f"[WARN] Audit/Plotting/Report encountered an issue: {ex}")

    _point_latest(base_waam_output, case_outdir)
    print(f"\n[DONE] Pipeline completed. Results in: {case_outdir}\n")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="WAAM-MOOSE Autonomous Simulation Framework"
    )
    parser.add_argument("--stl", "--geometry", type=str, help="Slice and simulate an STL/STEP geometry")
    parser.add_argument("--cli", action="store_true", help="Run default letter-Z benchmark in headless CLI mode")
    parser.add_argument("--gui", action="store_true", help="Launch interactive graphical interface")
    parser.add_argument("--validate", action="store_true", help="Run pytest verification suite")
    parser.add_argument("--mechanical", action="store_true", help="Enable coupled quasi-static J2 thermo-mechanics")
    parser.add_argument("--springback", action="store_true", help="Enable multi-stage fixture release & springback relaxation")
    parser.add_argument("--adaptive-dt", action="store_true", help="Enable IterationAdaptiveDT auto-growth & cutback time-stepping")
    parser.add_argument("--ultrasonic", action="store_true", help="Enable ultrasonic vibration-assisted (UVA) physics")
    parser.add_argument("--ranks", type=int, default=1, help="Number of MPI ranks to run")
    parser.add_argument("--layer-height", type=float, default=3.0, help="Layer height in mm (default: 3.0)")
    parser.add_argument("--bead-width", type=float, default=8.0, help="Bead width in mm (default: 8.0)")
    parser.add_argument("--hz-base-mm", type=float, default=5.0, help="Substrate thickness in mm (default: 5.0)")
    parser.add_argument("--target-nodes", type=int, default=2000, help="Target mesh nodes (default: 2000)")
    parser.add_argument("--outdir", type=str, default=None, help="Base output directory")
    parser.add_argument("--dt-weld", type=float, default=None, help="Weld time step in seconds")
    parser.add_argument("--t-wait", type=float, default=None, help="Interpass dwell duration in seconds")
    parser.add_argument("--dt-wait", type=float, default=None, help="Interpass dwell step in seconds")
    parser.add_argument("--dt-cool", type=float, default=None, help="Cooling step in seconds")
    parser.add_argument("--n-cool-steps", type=int, default=None, help="Number of cool-down steps")
    parser.add_argument("--material-base", type=str, default=None, help="Substrate alloy name (default: SS316L)")
    parser.add_argument("--material-dep", type=str, default=None, help="Deposit alloy name (default: SS308L)")
    parser.add_argument("--mesh", type=str, default=None, help="Use pre-generated .mesh file instead of remeshing")

    args = parser.parse_args(argv)

    base_waam_output = Path(args.outdir).resolve() if args.outdir else _HERE / "waam_output"
    base_waam_output.mkdir(parents=True, exist_ok=True)

    if args.validate:
        print("[VALIDATE] Running comprehensive multi-physics verification suite ...")
        cmd = [sys.executable, "-m", "pytest", str(_HERE / "tests"), str(_HERE / "core" / "test_thermal_curve.py")]
        return subprocess.run(cmd).returncode

    if args.stl:
        return run_full_pipeline(args.stl, args, base_waam_output)

    if args.cli:
        default_stl = _HERE / "test_stl" / "z.stl"
        if not default_stl.exists():
            default_stl = _HERE.parent / "waam-framework" / "stl" / "z.stl"
        if not default_stl.exists():
            default_stl = _HERE.parent / "WAAM-Framework" / "stl" / "z.stl"
        if default_stl.exists():
            return run_full_pipeline(str(default_stl), args, base_waam_output)
        else:
            print("[ERROR] Default letter-Z STL not found. Specify --stl <path>.")
            return 1

    # Default: launch GUI
    from gui.app import WAAMApp
    import tkinter as tk
    root = tk.Tk()
    app = WAAMApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
