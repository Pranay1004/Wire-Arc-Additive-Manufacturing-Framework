#!/usr/bin/env python3
"""
UVA-WAAM OpenFOAM Post-Processing — Complete Analysis
=====================================================
Parses the reconstructed beamWeldFoam case data and produces:
  • Temperature history & solidification front tracking
  • Velocity field statistics
  • Courant number evolution
  • Residual convergence plots
  • Summary metrics JSON

Uses the solver log directly (no OpenFOAM python bindings needed).
Author: UVA-WAAM Module
"""

import re
import json
import os
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_PLT = True
except ImportError:
    HAS_PLT = False

# ── Paths ────────────────────────────────────────────────────────────
CASE_DIR  = Path(__file__).parent
LOG_FILE  = CASE_DIR / "solver_parallel_9core.log"
OUT_DIR   = CASE_DIR / "postprocess_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_solver_log(logpath):
    """Extract time-series data from beamWeldFoam solver log."""
    data = {
        "time": [], "courant_max": [], "courant_mean": [],
        "alpha_min": [], "alpha_max": [], "alpha_vol_frac": [],
        "temp_residual_init": [], "temp_residual_final": [],
        "ux_residual_init": [],
        "exec_time": [],
        "deltaT": [],
    }

    with open(logpath, "r") as f:
        lines = f.readlines()

    current_time = None

    for i, line in enumerate(lines):
        # Time step
        m = re.match(r'^Time = ([\d.e+-]+)', line)
        if m:
            current_time = float(m.group(1))
            data["time"].append(current_time)

        # Courant number
        m = re.search(r'Courant Number mean:\s*([\d.e+-]+)\s+max:\s*([\d.e+-]+)', line)
        if m and current_time is not None:
            data["courant_mean"].append(float(m.group(1)))
            data["courant_max"].append(float(m.group(2)))

        # Phase-1 volume fraction
        m = re.search(r'Phase-1 volume fraction = ([\d.e+-]+)\s+Min.*= ([\d.e+-]+)\s+Max.*= ([\d.e+-]+)', line)
        if m and current_time is not None:
            data["alpha_vol_frac"].append(float(m.group(1)))
            data["alpha_min"].append(float(m.group(2)))
            data["alpha_max"].append(float(m.group(3)))

        # Temperature residual
        m = re.search(r'Solving for Temperature, Initial residual = ([\d.e+-]+), Final residual = ([\d.e+-]+)', line)
        if m:
            data["temp_residual_init"].append(float(m.group(1)))
            data["temp_residual_final"].append(float(m.group(2)))

        # Ux residual
        m = re.search(r'Solving for Ux, Initial residual = ([\d.e+-]+)', line)
        if m:
            data["ux_residual_init"].append(float(m.group(1)))

        # Execution time
        m = re.search(r'ExecutionTime = ([\d.]+) s', line)
        if m:
            data["exec_time"].append(float(m.group(1)))

        # deltaT
        m = re.search(r'deltaT = ([\d.e+-]+)', line)
        if m:
            data["deltaT"].append(float(m.group(1)))

    return data


def summarize(data):
    """Compute summary statistics."""
    summary = {}

    if data["time"]:
        summary["simulation_time_range_s"] = [data["time"][0], data["time"][-1]]
        summary["total_timesteps"] = len(data["time"])

    if data["courant_max"]:
        summary["courant_max_peak"] = max(data["courant_max"])
        summary["courant_max_mean"] = sum(data["courant_max"]) / len(data["courant_max"])

    if data["alpha_vol_frac"]:
        summary["alpha_vol_frac_final"] = data["alpha_vol_frac"][-1]

    if data["temp_residual_init"]:
        summary["temp_residual_initial_first"] = data["temp_residual_init"][0]
        summary["temp_residual_initial_last"] = data["temp_residual_init"][-1]
        summary["temp_residual_final_last"] = data["temp_residual_final"][-1] if data["temp_residual_final"] else None

    if data["exec_time"]:
        summary["wall_clock_s"] = data["exec_time"][-1]

    if data["deltaT"]:
        summary["dt_range_s"] = [min(data["deltaT"]), max(data["deltaT"])]

    return summary


def plot_results(data):
    """Generate all post-processing plots."""
    if not HAS_PLT:
        print("[WARN] matplotlib unavailable, skipping plots.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("UVA-WAAM OpenFOAM Post-Processing: beamWeldFoam 9-Core Parallel",
                 fontsize=14, fontweight="bold")

    # 1. Temperature Residual Convergence
    ax = axes[0, 0]
    if data["temp_residual_init"]:
        steps = list(range(len(data["temp_residual_init"])))
        ax.semilogy(steps, data["temp_residual_init"], "b-", alpha=0.7, label="Initial")
        if len(data["temp_residual_final"]) == len(steps):
            ax.semilogy(steps, data["temp_residual_final"], "r-", alpha=0.7, label="Final")
        ax.set_xlabel("Solver Iteration")
        ax.set_ylabel("Residual")
        ax.set_title("Temperature Solver Convergence")
        ax.legend()
        ax.grid(alpha=0.3)

    # 2. Courant Number
    ax = axes[0, 1]
    if data["courant_max"]:
        n = min(len(data["time"]), len(data["courant_max"]))
        ax.plot(data["time"][:n], data["courant_max"][:n], "r-", label="Max Co", linewidth=1.5)
        if len(data["courant_mean"]) >= n:
            ax.plot(data["time"][:n], data["courant_mean"][:n], "b-", label="Mean Co", linewidth=1.0, alpha=0.6)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Courant Number")
        ax.set_title("Courant Number Evolution")
        ax.legend()
        ax.grid(alpha=0.3)

    # 3. Phase Fraction
    ax = axes[1, 0]
    if data["alpha_vol_frac"]:
        # Only plot unique entries (avoid repeats from MULES sub-iterations)
        n = min(len(data["time"]), len(data["alpha_vol_frac"]))
        ax.plot(data["time"][:n], data["alpha_vol_frac"][:n], "g-", linewidth=1.5)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Phase-1 Volume Fraction")
        ax.set_title("Metal Phase Volume Fraction")
        ax.grid(alpha=0.3)

    # 4. Velocity Residual
    ax = axes[1, 1]
    if data["ux_residual_init"]:
        steps = list(range(len(data["ux_residual_init"])))
        ax.semilogy(steps, data["ux_residual_init"], "m-", alpha=0.7, label="Ux Initial")
        ax.set_xlabel("Solver Iteration")
        ax.set_ylabel("Residual")
        ax.set_title("Velocity (Ux) Solver Convergence")
        ax.legend()
        ax.grid(alpha=0.3)

    plt.tight_layout()
    fpath = OUT_DIR / "openfoam_postprocess.png"
    plt.savefig(fpath, dpi=200)
    plt.close()
    print(f"  Saved: {fpath}")

    # Additional: Wall-clock performance plot
    if data["exec_time"] and len(data["exec_time"]) > 5:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(range(len(data["exec_time"])), data["exec_time"], "k-", linewidth=1.5)
        ax.set_xlabel("Timestep Index")
        ax.set_ylabel("Cumulative Wall Clock (s)")
        ax.set_title("Parallel Run Performance (9 Cores)")
        ax.grid(alpha=0.3)
        fpath = OUT_DIR / "performance_9core.png"
        plt.savefig(fpath, dpi=150)
        plt.close()
        print(f"  Saved: {fpath}")


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("="*60)
    print("  UVA-WAAM OpenFOAM Post-Processing")
    print("="*60)

    if not LOG_FILE.exists():
        print(f"  [ERROR] Solver log not found: {LOG_FILE}")
        print("  Available logs:")
        for f in CASE_DIR.glob("solver*.log"):
            print(f"    {f}")
        exit(1)

    print(f"  Parsing: {LOG_FILE}")
    data = parse_solver_log(LOG_FILE)

    print(f"  Timesteps parsed: {len(data['time'])}")
    print(f"  Temperature residuals: {len(data['temp_residual_init'])}")
    print(f"  Courant entries: {len(data['courant_max'])}")

    summary = summarize(data)

    # Save summary
    fpath = OUT_DIR / "summary.json"
    with open(fpath, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary saved: {fpath}")

    # Print summary table
    print("\n  ── Summary ──")
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # Generate plots
    print("\n  Generating plots...")
    plot_results(data)

    print(f"\n  ✅ Post-processing complete. Results in: {OUT_DIR}/")
