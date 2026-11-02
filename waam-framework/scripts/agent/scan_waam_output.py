#!/usr/bin/env python3
"""scripts/agent/scan_waam_output.py — E1 full manifest + summaries + regex matches."""
import os, sys, json, csv, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "waam_output"
OUT = Path(__file__).resolve().parents[1] / "docs" / "audit"
OUT.mkdir(parents=True, exist_ok=True)

# Regex library from E3
ERROR_PATTERNS = [
    (re.compile(r"^Erreur", re.M), "FreeFEM_Erreur"),
    (re.compile(r"Fatal (?:error|Error):?", re.I), "FreeFEM_Fatal"),
    (re.compile(r"OutOfMem|out of memory", re.I), "OOM"),
    (re.compile(r"SIGSEGV", re.I), "SIGSEGV"),
    (re.compile(r"negative matrix dimension", re.I), "NegMatrix"),
    (re.compile(r"exit code", re.I), "ExitCode"),
    (re.compile(r"Mesh Load Error", re.I), "MeshLoad"),
    (re.compile(r"(meshio|gmsh) (error|warning)", re.I), "MeshioGmsh"),
    (re.compile(r"degenerate (edge|face)", re.I), "Degenerate"),
    (re.compile(r"non-manifold", re.I), "NonManifold"),
    (re.compile(r"aspect [Rr]atio", re.I), "AspectRatio"),
    (re.compile(r"FATAL", re.I), "OpenFOAM_FATAL"),
    (re.compile(r"divergence detected", re.I), "OpenFOAM_Div"),
    (re.compile(r"floating point exception", re.I), "OpenFOAM_FPE"),
    (re.compile(r"Courant Number.*mean:([0-9.]+) value:([0-9.]+)", re.I), "Courant"),
    (re.compile(r"Tmax=([0-9.]+)"), "Tmax"),
    (re.compile(r"--- Layer (\d+)/(\d+)"), "LayerProgress"),
    (re.compile(r"EXECUTION FINISHED - RETURN CODE: (\d+)"), "ExitCode"),
    (re.compile(r"AUTO-HEAL", re.I), "AutoHeal"),
    (re.compile(r"SOLVER ERROR DIAGNOSIS", re.I), "SolverDiag"),
    (re.compile(r"Traceback \(most recent call last\)"), "PythonTraceback"),
    (re.compile(r"UnicodeDecodeError"), "UnicodeDecode"),
    (re.compile(r"TclError"), "TclError"),
    (re.compile(r"PermissionError"), "PermissionError"),
    (re.compile(r"WinError"), "WinError"),
]

runs_manifest = []
runs_summary = []
error_matches = []
slow_layers = []

for run_dir in sorted(ROOT.iterdir()):
    if not run_dir.is_dir():
        continue
    if run_dir.name in {"plots", "visual_outputs", "cache", "waam_data.csv", "waam_domain.mesh", "waam_parametric_sweep_comparison_report.pdf"}:
        continue
    
    run_id = run_dir.name
    files = list(run_dir.rglob("*"))
    n_files = len([f for f in files if f.is_file()])
    bytes_total = sum(f.stat().st_size for f in files if f.is_file())
    mtime = max(f.stat().st_mtime for f in files if f.is_file()) if files else 0
    
    sim_log = run_dir / "FreeFEM" / "sim.log"
    has_sim = sim_log.exists()
    sim_lines = 0
    sim_log_rc = None
    if has_sim:
        txt = sim_log.read_text(errors="ignore")
        sim_lines = txt.count("\n")
        m = re.search(r"EXECUTION FINISHED - RETURN CODE: (\d+)", txt)
        if m:
            sim_log_rc = int(m.group(1))
    
    # Error matches
    if has_sim:
        for pattern, tag in ERROR_PATTERNS:
            for i, line in enumerate(txt.splitlines(), 1):
                if pattern.search(line):
                    error_matches.append({
                        "run_id": run_id,
                        "file": str(sim_log.relative_to(ROOT)),
                        "line_no": i,
                        "pattern": tag,
                        "excerpt": line[:200]
                    })
    
    # Layer pass times
    lp_file = run_dir / "layer_pass_times.txt"
    if lp_file.exists():
        try:
            lines = lp_file.read_text().strip().splitlines()
            if len(lines) > 1:
                times = [float(l.split()[1]) for l in lines[1:] if l.strip()]
                if times:
                    import statistics
                    median = statistics.median(times)
                    max_t = max(times)
                    ratio = max_t / median if median > 0 else 0
                    if ratio > 3:
                        slow_layers.append({
                            "run_id": run_id,
                            "layers": len(times),
                            "median_s": median,
                            "max_s": max_t,
                            "ratio": ratio
                        })
        except Exception:
            pass
    
    params = run_dir / "parameters.json"
    summary = run_dir / "run_summary.json"
    plots_dir = run_dir / "plots"
    visual = run_dir / "visual_outputs"
    foam_log = run_dir / "sim_openfoam.log"
    
    has_params = params.exists()
    has_summary = summary.exists()
    plots_count = len(list(plots_dir.glob("*.png"))) if plots_dir.exists() else 0
    vtu_count = len(list(visual.glob("*.vtu"))) if visual.exists() else 0
    vtu_bytes_max = max((f.stat().st_size for f in visual.glob("*.vtu")), default=0) if visual.exists() else 0
    has_foam = foam_log.exists()
    foam_exit = None
    if has_foam:
        foam_txt = foam_log.read_text(errors="ignore")
        foam_exit = foam_txt.strip().splitlines()[-1][:100] if foam_txt else None
    
    runs_manifest.append({
        "run_id": run_id,
        "n_files": n_files,
        "bytes_total": bytes_total,
        "mtime": mtime
    })
    runs_summary.append({
        "run_id": run_id,
        "has_sim_log": has_sim,
        "sim_log_lines": sim_lines,
        "sim_log_rc": sim_log_rc,
        "has_params": has_params,
        "has_summary": has_summary,
        "has_plots": plots_count > 0,
        "plots_count": plots_count,
        "has_visual": vtu_count > 0,
        "vtu_count": vtu_count,
        "vtu_bytes_max": vtu_bytes_max,
        "has_foam": has_foam,
        "foam_exit": foam_exit
    })

# Write CSVs
with open(OUT / "runs_manifest.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["run_id", "n_files", "bytes_total", "mtime"])
    w.writeheader()
    w.writerows(runs_manifest)

with open(OUT / "runs_summary.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["run_id", "has_sim_log", "sim_log_lines", "sim_log_rc", "has_params", "has_summary", "has_plots", "plots_count", "has_visual", "vtu_count", "vtu_bytes_max", "has_foam", "foam_exit"])
    w.writeheader()
    w.writerows(runs_summary)

with open(OUT / "error_matches.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["run_id", "file", "line_no", "pattern", "excerpt"])
    w.writeheader()
    w.writerows(error_matches)

with open(OUT / "slow_layers.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["run_id", "layers", "median_s", "max_s", "ratio"])
    w.writeheader()
    w.writerows(slow_layers)

print(f"scan_waam_output: {len(runs_manifest)} runs, {len(error_matches)} errors, {len(slow_layers)} slow")
print("RESULT scan_waam_output complete")
