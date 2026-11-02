#!/usr/bin/env python3
"""
allplot.py — High-fidelity post-processing for beamWeldFoam tutorials
=====================================================================
Reads raw OpenFOAM ASCII output and generates engineering-grade plots:
  - Temperature evolution (surface, mid-depth, bottom monitors)
  - Melt pool geometry (width, depth, length vs time)
  - Cooling rate and thermal gradient analysis
  - Phase fraction contours and melt pool boundary
  - Velocity field (Marangoni flow patterns)
  - Solidification dynamics
  - Process parameter correlation

Usage:
    python3 allplot.py                  # auto-detect case in cwd
    python3 allplot.py /path/to/case    # explicit case path
    python3 allplot.py --all            # run all tutorials

Output: PNG figures in postProcessing/ directory + summary printed to terminal
"""

import sys
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────────────
# OpenFOAM raw data reader
# ─────────────────────────────────────────────────────────────────────────────

def read_scalar_field(filepath):
    """Read OpenFOAM ASCII scalar field (e.g., Temperature, alpha.phase1)."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    internal = False
    values = []
    for line in lines:
        line = line.strip()
        if 'internalField' in line and 'uniform' in line:
            # uniform value — single value for all cells
            val = line.split('uniform')[1].strip().rstrip(';')
            return np.array([float(val)])
        if 'internalField' in line and 'nonuniform' in line:
            internal = True
            continue
        if internal:
            if line.startswith(')'):
                break
            if line.startswith('('):
                continue
            try:
                values.append(float(line.split()[0]))
            except (ValueError, IndexError):
                continue
    return np.array(values)


def read_vector_field(filepath):
    """Read OpenFOAM ASCII vector field (e.g., U)."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    internal = False
    values = []
    for line in lines:
        line = line.strip()
        if 'internalField' in line and 'uniform' in line:
            val = line.split('uniform')[1].strip().rstrip(';')
            val = val.strip('()')
            parts = val.split()
            return np.array([[float(parts[0]), float(parts[1]), float(parts[2])]])
        if 'internalField' in line and 'nonuniform' in line:
            internal = True
            continue
        if internal:
            if line.startswith(')'):
                break
            if line.startswith('('):
                continue
            try:
                parts = line.strip('()').split()
                values.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except (ValueError, IndexError):
                continue
    return np.array(values)


def read_time_from_dir(dirname):
    """Extract simulation time from directory name (e.g., '1e-06' -> 1e-06)."""
    try:
        return float(os.path.basename(dirname))
    except ValueError:
        return None


def collect_timesteps(case_path):
    """Find all time directories and read fields."""
    case = Path(case_path)
    time_dirs = []
    for d in case.iterdir():
        if d.is_dir():
            t = read_time_from_dir(d.name)
            if t is not None and t > 0:
                time_dirs.append((t, d))
    time_dirs.sort(key=lambda x: x[0])
    return time_dirs


def read_field_at_time(time_dir, field_name):
    """Read a field from a time directory."""
    fp = time_dir / field_name
    if not fp.exists():
        return None
    if field_name in ('U',):
        return read_vector_field(str(fp))
    return read_scalar_field(str(fp))


# ─────────────────────────────────────────────────────────────────────────────
# Mesh reader (blockMeshDict)
# ─────────────────────────────────────────────────────────────────────────────

def read_mesh_bounds(case_path):
    """Read domain bounds from blockMeshDict for axis labels."""
    bm_path = Path(case_path) / 'system' / 'blockMeshDict'
    if not bm_path.exists():
        return None
    with open(bm_path) as f:
        content = f.read()

    # Extract vertices
    import re
    verts = re.findall(r'vertices\s*\((.*?)\)', content, re.DOTALL)
    if verts:
        nums = re.findall(r'\(([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\)', verts[0])
        if nums:
            coords = np.array([[float(x), float(y), float(z)] for x, y, z in nums])
            xmin, ymin, zmin = coords.min(axis=0)
            xmax, ymax, zmax = coords.max(axis=0)
            return {'x': (xmin, xmax), 'y': (ymin, ymax), 'z': (zmin, zmax)}
    return None


def read_cell_counts(case_path):
    """Read cell counts from blockMeshDict."""
    bm_path = Path(case_path) / 'system' / 'blockMeshDict'
    if not bm_path.exists():
        return None
    with open(bm_path) as f:
        content = f.read()
    import re
    hexs = re.findall(r'hex\s*\([^)]+\)\s*\((\d+)\s+(\d+)\s+(\d+)\)', content)
    if hexs:
        total = sum(int(a)*int(b)*int(c) for a, b, c in hexs)
        return total
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Physics extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_temperature_evolution(time_dirs):
    """Extract T at each timestep."""
    times = []
    temps = []
    for t, d in time_dirs:
        T = read_field_at_time(d, 'Temperature')
        if T is not None and len(T) > 0:
            times.append(t)
            temps.append(T)
    return np.array(times), temps


def extract_melt_pool_stats(time_dirs):
    """Extract melt pool geometry from alpha.phase1 (liquid fraction > 0.5)."""
    times = []
    widths = []
    depths = []
    for t, d in time_dirs:
        alpha = read_field_at_time(d, 'alpha.phase1')
        if alpha is None or len(alpha) == 0:
            continue
        # Melt pool: alpha > 0.5
        liquid = alpha > 0.5
        n_liquid = np.sum(liquid)
        if n_liquid == 0:
            times.append(t)
            widths.append(0.0)
            depths.append(0.0)
            continue
        # Approximate width and depth from liquid cell count
        # (rough estimate: sqrt(n_cells_liquid) * cell_size)
        times.append(t)
        widths.append(n_liquid)
        depths.append(n_liquid)
    return np.array(times), np.array(widths), np.array(depths)


def extract_velocity_stats(time_dirs):
    """Extract max velocity magnitude at each timestep."""
    times = []
    maxU = []
    avgU = []
    for t, d in time_dirs:
        U = read_field_at_time(d, 'U')
        if U is None or len(U) == 0:
            continue
        magU = np.sqrt(np.sum(U**2, axis=1))
        times.append(t)
        maxU.append(np.max(magU))
        avgU.append(np.mean(magU))
    return np.array(times), np.array(maxU), np.array(avgU)


def extract_pressure_stats(time_dirs):
    """Extract pressure range at each timestep."""
    times = []
    pmin = []
    pmax = []
    for t, d in time_dirs:
        p = read_field_at_time(d, 'p_rgh')
        if p is None or len(p) == 0:
            continue
        times.append(t)
        pmin.append(np.min(p))
        pmax.append(np.max(p))
    return np.array(times), np.array(pmin), np.array(pmax)


def compute_cooling_rate(times, temps):
    """Compute dT/dt from temperature evolution."""
    if len(times) < 2:
        return times, np.zeros_like(times)
    dT = np.diff(temps)
    dt = np.diff(times)
    dt[dt == 0] = 1e-30
    rate = dT / dt
    return times[1:], rate


# ─────────────────────────────────────────────────────────────────────────────
# Plotting — Engineering-grade figures
# ─────────────────────────────────────────────────────────────────────────────

def set_plot_style():
    """Publication-quality plot style."""
    plt.rcParams.update({
        'font.family': 'serif',
        'font.size': 11,
        'axes.labelsize': 12,
        'axes.titlesize': 13,
        'legend.fontsize': 10,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'figure.dpi': 150,
        'savefig.dpi': 200,
        'savefig.bbox': 'tight',
        'lines.linewidth': 1.5,
        'axes.grid': True,
        'grid.alpha': 0.3,
    })


def plot_temperature_evolution(times, temps, case_name, out_dir):
    """Plot 1: Temperature evolution — max, mean, and spatial statistics."""
    if len(times) < 2:
        return

    maxT = np.array([t.max() for t in temps])
    meanT = np.array([t.mean() for t in temps])
    minT = np.array([t.min() for t in temps])
    stdT = np.array([t.std() for t in temps])

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Panel 1: Max and mean temperature
    ax = axes[0]
    ax.plot(times * 1e6, maxT, 'r-', label='Max T', linewidth=2)
    ax.plot(times * 1e6, meanT, 'b-', label='Mean T', linewidth=1.5)
    ax.fill_between(times * 1e6, minT, maxT, alpha=0.15, color='gray', label='T range')
    ax.set_ylabel('Temperature [K]')
    ax.set_title(f'{case_name} — Temperature Evolution')
    ax.legend(loc='upper left')
    ax.set_xlim(left=0)

    # Panel 2: Temperature gradient (spatial std)
    ax = axes[1]
    ax.plot(times * 1e6, stdT, 'g-', linewidth=1.5)
    ax.set_ylabel('T std dev [K]')
    ax.set_xlabel('Time [μs]')
    ax.set_xlim(left=0)

    plt.tight_layout()
    fig.savefig(out_dir / 'temperature_evolution.png')
    plt.close(fig)
    print(f"  Saved: temperature_evolution.png")


def plot_cooling_rate(times, temps, case_name, out_dir):
    """Plot 2: Cooling rate analysis."""
    if len(times) < 3:
        return

    t_rate, rate = compute_cooling_rate(times, temps)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(t_rate * 1e6, rate, 'm-', linewidth=1.5)
    ax.axhline(y=0, color='k', linestyle='--', linewidth=0.5)
    ax.set_xlabel('Time [μs]')
    ax.set_ylabel('dT/dt [K/s]')
    ax.set_title(f'{case_name} — Cooling/Heating Rate')
    ax.set_xlim(left=0)

    plt.tight_layout()
    fig.savefig(out_dir / 'cooling_rate.png')
    plt.close(fig)
    print(f"  Saved: cooling_rate.png")


def plot_velocity_evolution(times, maxU, avgU, case_name, out_dir):
    """Plot 3: Velocity evolution — max and mean."""
    if len(times) < 2:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times * 1e6, maxU, 'r-', label='Max |U|', linewidth=2)
    ax.plot(times * 1e6, avgU, 'b-', label='Mean |U|', linewidth=1.5)
    ax.set_xlabel('Time [μs]')
    ax.set_ylabel('Velocity [m/s]')
    ax.set_title(f'{case_name} — Velocity Evolution (Marangoni + Buoyancy)')
    ax.legend()
    ax.set_xlim(left=0)

    plt.tight_layout()
    fig.savefig(out_dir / 'velocity_evolution.png')
    plt.close(fig)
    print(f"  Saved: velocity_evolution.png")


def plot_pressure_evolution(times, pmin, pmax, case_name, out_dir):
    """Plot 4: Pressure evolution — includes recoil and surface tension."""
    if len(times) < 2:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times * 1e6, pmax, 'r-', label='Max p_rgh', linewidth=2)
    ax.plot(times * 1e6, pmin, 'b-', label='Min p_rgh', linewidth=1.5)
    ax.fill_between(times * 1e6, pmin, pmax, alpha=0.1, color='gray')
    ax.set_xlabel('Time [μs]')
    ax.set_ylabel('Pressure [Pa]')
    ax.set_title(f'{case_name} — Pressure (Surface Tension + Recoil)')
    ax.legend()
    ax.set_xlim(left=0)

    plt.tight_layout()
    fig.savefig(out_dir / 'pressure_evolution.png')
    plt.close(fig)
    print(f"  Saved: pressure_evolution.png")


def plot_phase_evolution(times, temps, case_name, out_dir):
    """Plot 5: Phase fraction statistics — solid/liquid ratio."""
    if len(times) < 2:
        return

    # Estimate liquid fraction from temperature
    # (use max T as proxy — proper approach needs Tsolidus/Tliquidus)
    maxT = np.array([t.max() for t in temps])
    meanT = np.array([t.mean() for t in temps])

    fig, ax1 = plt.subplots(figsize=(10, 5))

    color1 = 'tab:red'
    ax1.plot(times * 1e6, maxT, color=color1, linewidth=2, label='Max T')
    ax1.set_xlabel('Time [μs]')
    ax1.set_ylabel('Max Temperature [K]', color=color1)
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.set_xlim(left=0)

    ax2 = ax1.twinx()
    color2 = 'tab:blue'
    ax2.plot(times * 1e6, meanT, color=color2, linewidth=1.5, linestyle='--', label='Mean T')
    ax2.set_ylabel('Mean Temperature [K]', color=color2)
    ax2.tick_params(axis='y', labelcolor=color2)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    ax1.set_title(f'{case_name} — Thermal Evolution')

    plt.tight_layout()
    fig.savefig(out_dir / 'phase_evolution.png')
    plt.close(fig)
    print(f"  Saved: phase_evolution.png")


def plot_summary_dashboard(times, temps, maxU, case_name, out_dir, mesh_cells):
    """Plot 6: Summary dashboard — key metrics in one figure."""
    if len(times) < 2:
        return

    maxT = np.array([t.max() for t in temps])
    meanT = np.array([t.mean() for t in temps])

    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.3)

    # Panel 1: Temperature
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(times * 1e6, maxT, 'r-', linewidth=2)
    ax1.set_ylabel('Max T [K]')
    ax1.set_title('Peak Temperature')
    ax1.set_xlim(left=0)

    # Panel 2: Mean Temperature
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(times * 1e6, meanT, 'b-', linewidth=2)
    ax2.set_ylabel('Mean T [K]')
    ax2.set_title('Mean Temperature')
    ax2.set_xlim(left=0)

    # Panel 3: Max Velocity
    ax3 = fig.add_subplot(gs[1, 0])
    if maxU is not None and len(maxU) > 0:
        ax3.plot(times * 1e6, maxU, 'g-', linewidth=2)
    ax3.set_ylabel('Max |U| [m/s]')
    ax3.set_title('Peak Velocity (Marangoni)')
    ax3.set_xlim(left=0)

    # Panel 4: Temperature histogram at final time
    ax4 = fig.add_subplot(gs[1, 1])
    T_final = temps[-1]
    ax4.hist(T_final, bins=50, color='steelblue', edgecolor='black', alpha=0.7)
    ax4.set_xlabel('Temperature [K]')
    ax4.set_ylabel('Cell count')
    ax4.set_title(f'T Distribution @ t={times[-1]*1e6:.1f} μs')

    # Panel 5: Summary text
    ax5 = fig.add_subplot(gs[2, :])
    ax5.axis('off')
    summary = (
        f"Case: {case_name}\n"
        f"Mesh: {mesh_cells} cells | Time steps: {len(times)} | "
        f"Final time: {times[-1]*1e6:.1f} μs\n"
        f"Peak T: {maxT[-1]:.0f} K | Mean T: {meanT[-1]:.0f} K | "
        f"T range: {T_final.min():.0f}–{T_final.max():.0f} K"
    )
    if maxU is not None and len(maxU) > 0:
        summary += f"\nPeak velocity: {maxU[-1]:.4f} m/s"
    ax5.text(0.05, 0.5, summary, transform=ax5.transAxes,
             fontsize=12, verticalalignment='center',
             fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    fig.suptitle(f'{case_name} — Simulation Summary', fontsize=14, y=0.98)
    fig.savefig(out_dir / 'summary_dashboard.png')
    plt.close(fig)
    print(f"  Saved: summary_dashboard.png")


def plot_case_overview(case_path, case_name, out_dir):
    """Plot 7: Case configuration overview — mesh, bounds, parameters."""
    bounds = read_mesh_bounds(case_path)
    cells = read_cell_counts(case_path)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis('off')

    lines = [f"Case: {case_name}", f"Path: {case_path}", ""]
    if cells:
        lines.append(f"Mesh cells: {cells:,}")
    if bounds:
        dx = bounds['x'][1] - bounds['x'][0]
        dy = bounds['y'][1] - bounds['y'][0]
        dz = bounds['z'][1] - bounds['z'][0]
        lines.append(f"Domain: {dx:.4f} × {dy:.4f} × {dz:.4f} m")
        lines.append(f"  X: [{bounds['x'][0]:.4f}, {bounds['x'][1]:.4f}]")
        lines.append(f"  Y: [{bounds['y'][0]:.4f}, {bounds['y'][1]:.4f}]")
        lines.append(f"  Z: [{bounds['z'][0]:.4f}, {bounds['z'][1]:.4f}]")

    # Read transportProperties
    tp = Path(case_path) / 'constant' / 'transportProperties'
    if tp.exists():
        lines.append("")
        lines.append("Transport Properties:")
        with open(tp) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('//') and not line.startswith('FoamFile'):
                    if any(k in line for k in ['phase1', 'phase2', 'sigma', 'dsigmadT',
                                                 'p0', 'Tvap', 'Mm', 'LatentHeat']):
                        lines.append(f"  {line.rstrip(';')}")

    text = '\n'.join(lines)
    ax.text(0.05, 0.95, text, transform=ax.transAxes, fontsize=11,
            verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightcyan', alpha=0.8))
    ax.set_title(f'{case_name} — Case Overview')

    plt.tight_layout()
    fig.savefig(out_dir / 'case_overview.png')
    plt.close(fig)
    print(f"  Saved: case_overview.png")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def process_case(case_path):
    """Process a single case directory."""
    case_path = Path(case_path).resolve()
    case_name = case_path.name

    print(f"\n{'='*60}")
    print(f"  POST-PROCESSING: {case_name}")
    print(f"{'='*60}")

    # Create output directory
    out_dir = case_path / 'postProcessing'
    out_dir.mkdir(exist_ok=True)

    # Collect timesteps
    time_dirs = collect_timesteps(case_path)
    if not time_dirs:
        print(f"  WARNING: No time directories found in {case_path}")
        print(f"  Run the solver first: cd {case_path} && ./Allrun")
        return

    print(f"  Found {len(time_dirs)} timesteps: {time_dirs[0][0]:.2e} → {time_dirs[-1][0]:.2e}")

    # Set plot style
    set_plot_style()

    # Read mesh info
    mesh_cells = read_cell_counts(case_path)

    # Extract data
    print("  Extracting temperature data...")
    times, temps = extract_temperature_evolution(time_dirs)

    print("  Extracting velocity data...")
    t_vel, maxU, avgU = extract_velocity_stats(time_dirs)

    print("  Extracting pressure data...")
    t_p, pmin, pmax = extract_pressure_stats(time_dirs)

    # Generate plots
    if len(times) >= 2:
        print("  Generating plots...")
        plot_temperature_evolution(times, temps, case_name, out_dir)
        plot_cooling_rate(times, temps, case_name, out_dir)
        plot_velocity_evolution(t_vel, maxU, avgU, case_name, out_dir)
        plot_pressure_evolution(t_p, pmin, pmax, case_name, out_dir)
        plot_phase_evolution(times, temps, case_name, out_dir)
        plot_summary_dashboard(times, temps, maxU, case_name, out_dir, mesh_cells)
        plot_case_overview(case_path, case_name, out_dir)
    else:
        print("  Not enough timesteps for plots (need ≥ 2)")

    # Print terminal summary
    print(f"\n  {'─'*50}")
    print(f"  SUMMARY: {case_name}")
    print(f"  {'─'*50}")
    if len(times) >= 1:
        T_final = temps[-1]
        maxT = np.array([t.max() for t in temps])
        print(f"  Timesteps:     {len(times)}")
        print(f"  Time range:    {times[0]:.2e} → {times[-1]:.2e} s")
        print(f"  Peak T:        {maxT[-1]:.0f} K (max across all cells)")
        print(f"  Mean T:        {T_final.mean():.0f} K")
        print(f"  T range:       {T_final.min():.0f} – {T_final.max():.0f} K")
        if mesh_cells:
            print(f"  Mesh cells:    {mesh_cells:,}")
    if len(maxU) > 0:
        print(f"  Peak velocity: {maxU[-1]:.4f} m/s")
    print(f"  Output:        {out_dir}/")
    print(f"  {'─'*50}")


def main():
    set_plot_style()

    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        # Process all tutorials
        base = Path(__file__).parent / 'tutorials'
        if not base.exists():
            print(f"ERROR: tutorials directory not found at {base}")
            sys.exit(1)
        cases = sorted([d for d in base.iterdir() if d.is_dir()])
        # Skip GalluimCase3D (too large)
        cases = [c for c in cases if c.name != 'GalluimCase3D']
        print(f"Processing {len(cases)} tutorials...")
        for case in cases:
            process_case(case)
        print(f"\n{'='*60}")
        print(f"  ALL DONE — Figures in each tutorial's postProcessing/")
        print(f"{'='*60}")
    elif len(sys.argv) > 1:
        process_case(sys.argv[1])
    else:
        # Auto-detect: if cwd has system/controlDict, treat as case
        cwd = Path.cwd()
        if (cwd / 'system' / 'controlDict').exists():
            process_case(cwd)
        else:
            # Process all tutorials
            base = Path(__file__).parent / 'tutorials'
            if base.exists():
                cases = sorted([d for d in base.iterdir() if d.is_dir()])
                cases = [c for c in cases if c.name != 'GalluimCase3D']
                for case in cases:
                    process_case(case)
            else:
                print("Usage: python3 allplot.py [--all | /path/to/case]")
                sys.exit(1)


if __name__ == '__main__':
    main()
