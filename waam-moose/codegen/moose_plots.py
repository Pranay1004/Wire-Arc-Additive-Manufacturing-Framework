"""
codegen/moose_plots.py — MOOSE thermal post-processing plots.

Reads waam_moose_out.csv (+ optional exodus final frame) and renders the core
thermal plots into <run_dir>/moose/plots/. Mirrors the FreeFEM plot_generator
contract but consumes the MOOSE ledger schema.

Plots:
  01_thermal_envelope.png   - tmax / tmin vs time
  02_energy_ledger.png      - e_intended / e_injected / e_injected_raw vs time
  03_cap_power.png          - cap_power (boiling clamp) vs time
  04_melt_pool.png          - max_liquid / molten_fraction vs time
  05_fidelity.png           - fidelity (injected/intended) vs time
  06_final_temperature.png  - exodus final-frame T field (if available)

Usage:
    python3 -m codegen.moose_plots --run-dir <run_dir>
    python3 -m codegen.moose_plots --run-dir <run_dir> --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

os.environ.setdefault("MPLCONFIGDIR", os.path.join(
    tempfile.gettempdir(), "mpl_waam_moose"))
try:
    os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)
except Exception:
    pass
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _moose_dir(run_dir: Path) -> Path:
    cand = run_dir / "moose"
    return cand if cand.is_dir() else run_dir


def _read_csv(path: Path) -> List[Dict[str, float]]:
    if not path.exists():
        return []
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            row = {}
            for k, v in r.items():
                try:
                    row[k] = float(v)
                except (ValueError, TypeError):
                    row[k] = v
            out.append(row)
    return out


def _style():
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "#fafafa",
        "axes.edgecolor": "#334155",
        "axes.linewidth": 1.2,
        "grid.color": "#cbd5e1",
        "grid.linestyle": "--",
        "grid.alpha": 0.6,
        "font.size": 10,
        "axes.labelsize": 11,
        "axes.titlesize": 12,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.fontsize": 9,
        "legend.framealpha": 0.9,
    })


def _save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    fig.tight_layout()
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


def plot_thermal_envelope(rows, out_dir):
    if not rows:
        return None
    t = np.array([r["time"] for r in rows])
    tmax = np.array([r["tmax"] for r in rows])
    tmin = np.array([r["tmin"] for r in rows])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(t, tmax, color="#dc2626", lw=1.6, label="Tmax (°C)")
    ax.plot(t, tmin, color="#2563eb", lw=1.6, label="Tmin (°C)")
    ax.axhline(2862, color="#7c3aed", ls=":", lw=1.2, label="T_boil 2862 °C")
    ax.axhline(25, color="#059669", ls=":", lw=1.2, label="T_amb 25 °C")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("temperature (°C)")
    ax.set_title("MOOSE thermal envelope (Tmax / Tmin)")
    ax.grid(True)
    ax.legend()
    return _save(fig, out_dir, "01_thermal_envelope.png")


def plot_energy_ledger(rows, out_dir):
    if not rows:
        return None
    t = np.array([r["time"] for r in rows])
    ei = np.array([r["e_intended"] for r in rows])
    ej = np.array([r["e_injected"] for r in rows])
    er = np.array([r["e_injected_raw"] for r in rows])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(t, ei, color="#1f2937", lw=1.6, label="e_intended (J)")
    ax.plot(t, ej, color="#2563eb", lw=1.6, label="e_injected (J)")
    ax.plot(t, er, color="#9ca3af", lw=1.2, ls="--", label="e_injected_raw (J)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("energy (J)")
    ax.set_title("MOOSE energy ledger (intended vs injected)")
    ax.grid(True)
    ax.legend()
    return _save(fig, out_dir, "02_energy_ledger.png")


def plot_cap_power(rows, out_dir):
    if not rows:
        return None
    t = np.array([r["time"] for r in rows])
    cp = np.array([r["cap_power"] for r in rows])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(t, cp, color="#d97706", lw=1.4, label="cap_power (W)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("power (W)")
    ax.set_title("MOOSE boiling-cap power (upper clamp)")
    ax.grid(True)
    ax.legend()
    return _save(fig, out_dir, "03_cap_power.png")


def plot_melt_pool(rows, out_dir):
    if not rows:
        return None
    t = np.array([r["time"] for r in rows])
    ml = np.array([r["max_liquid"] for r in rows])
    mf = np.array([r["molten_fraction"] for r in rows])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(t, ml, color="#dc2626", lw=1.4, label="max_liquid (0/1)")
    ax2 = ax.twinx()
    ax2.plot(t, mf, color="#2563eb", lw=1.4, ls="--", label="molten_fraction")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("max_liquid")
    ax2.set_ylabel("molten_fraction")
    ax.set_title("MOOSE melt-pool indicators")
    ax.grid(True)
    # combined legend
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left")
    return _save(fig, out_dir, "04_melt_pool.png")


def plot_fidelity(rows, out_dir):
    if not rows:
        return None
    t = np.array([r["time"] for r in rows])
    f = np.array([r["fidelity"] for r in rows])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(t, f, color="#059669", lw=1.6, label="fidelity (injected/intended)")
    ax.axhline(1.0, color="#1f2937", ls=":", lw=1.2, label="1.0")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("fidelity")
    ax.set_ylim(0, 1.1)
    ax.set_title("MOOSE source fidelity (injected/intended)")
    ax.grid(True)
    ax.legend()
    return _save(fig, out_dir, "05_fidelity.png")


def plot_final_temperature(moose_dir: Path, out_dir: Path) -> Optional[Path]:
    exo = moose_dir / "waam_moose_exo.e"
    if not exo.exists():
        exo = moose_dir / "waam_moose.e"
    if not exo.exists():
        return None
    try:
        import netCDF4
    except Exception:
        return None
    try:
        ds = netCDF4.Dataset(str(exo))
        nts = ds.dimensions["time_step"].size
        Tnod = ds.variables["vals_nod_var1"][nts - 1]
        coords = (ds.variables["coordx"][:], ds.variables["coordy"][:],
                   ds.variables["coordz"][:])
        t_last = float(ds.variables["time_whole"][nts - 1])
        ds.close()
    except Exception:
        return None
    import numpy as np
    pts = np.column_stack(coords)
    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection="3d")
    sc = ax.scatter(pts[:, 0] * 1000, pts[:, 1] * 1000, pts[:, 2] * 1000,
                    c=Tnod, cmap="hot", s=4)
    cb = fig.colorbar(sc, ax=ax, shrink=0.6)
    cb.set_label("T (°C)")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_zlabel("z (mm)")
    ax.set_title(f"MOOSE final temperature field (t = {t_last:.2f} s)")
    return _save(fig, out_dir, "06_final_temperature.png")


def plot_thermomechanics(rows, out_dir):
    if not rows or "vonmises_max" not in rows[0]:
        return None
    t = np.array([r["time"] for r in rows])
    vm = np.array([r["vonmises_max"] / 1.0e6 for r in rows]) # Pa -> MPa
    dz = np.array([r.get("disp_z_max", 0.0) * 1000.0 for r in rows]) # m -> mm
    fig, ax1 = plt.subplots(figsize=(9, 5))
    color1 = "#b91c1c"
    ax1.set_xlabel("time (s)")
    ax1.set_ylabel("Peak von Mises Stress (MPa)", color=color1)
    l1 = ax1.plot(t, vm, color=color1, lw=1.8, label="von Mises (MPa)")
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.grid(True)

    ax2 = ax1.twinx()
    color2 = "#1d4ed8"
    ax2.set_ylabel("Peak z-Distortion (mm)", color=color2)
    l2 = ax2.plot(t, dz, color=color2, lw=1.8, ls="--", label="Disp Z (mm)")
    ax2.tick_params(axis="y", labelcolor=color2)

    lines = l1 + l2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left")
    ax1.set_title("QuasiStatic J2 Thermo-Mechanics: Stress & Distortion Evolution")
    return _save(fig, out_dir, "07_thermomechanics.png")


def plot_ultrasonics(rows, out_dir):
    if not rows or "uva_softening_max" not in rows[0]:
        return None
    t = np.array([r["time"] for r in rows])
    soft = np.array([r["uva_softening_max"] * 100.0 for r in rows]) # fraction -> %
    p_acou = np.array([r.get("uva_pressure_max", 0.0) / 1.0e6 for r in rows]) # Pa -> MPa
    fig, ax1 = plt.subplots(figsize=(9, 5))
    color1 = "#7c3aed"
    ax1.set_xlabel("time (s)")
    ax1.set_ylabel("Acoustic Softening Factor (%)", color=color1)
    l1 = ax1.plot(t, soft, color=color1, lw=1.8, label="Dynamic Softening (%)")
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.grid(True)

    ax2 = ax1.twinx()
    color2 = "#059669"
    ax2.set_ylabel("Acoustic Pressure Amplitude (MPa)", color=color2)
    l2 = ax2.plot(t, p_acou, color=color2, lw=1.8, ls="--", label="Acoustic Pressure (MPa)")
    ax2.tick_params(axis="y", labelcolor=color2)

    lines = l1 + l2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left")
    ax1.set_title("Ultrasonic Vibration-Assisted (UVA) Acoustic Multi-Physics")
    return _save(fig, out_dir, "08_ultrasonic_fields.png")


def plot_springback(rows, out_dir, p_meta=None):
    if not rows or "disp_z_max" not in rows[0]:
        return None
    t = np.array([r["time"] for r in rows])
    dz_max = np.array([r.get("disp_z_max", 0.0) * 1000.0 for r in rows])
    dz_min = np.array([r.get("disp_z_min", 0.0) * 1000.0 for r in rows])
    vm = np.array([r.get("vonmises_max", 0.0) / 1.0e6 for r in rows])

    t_unclamp = None
    if p_meta and p_meta.get("t_unclamp"):
        t_unclamp = float(p_meta["t_unclamp"])
    elif p_meta and (p_meta.get("springback_solve") or p_meta.get("dynamic_clamping")):
        t_unclamp = 0.5 * t[-1]

    if t_unclamp is None and not (p_meta and p_meta.get("springback_solve")):
        return None

    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.plot(t, dz_max, color="#1e40af", lw=1.8, label="Max z-Disp (mm)")
    ax1.plot(t, dz_min, color="#0284c7", lw=1.6, ls="--", label="Min z-Disp (mm)")
    ax1.set_xlabel("time (s)")
    ax1.set_ylabel("Vertical Distortion uz (mm)", color="#1e40af")
    ax1.tick_params(axis="y", labelcolor="#1e40af")
    ax1.grid(True)

    ax2 = ax1.twinx()
    ax2.plot(t, vm, color="#dc2626", lw=1.4, ls=":", label="Peak von Mises (MPa)")
    ax2.set_ylabel("Peak Stress (MPa)", color="#dc2626")
    ax2.tick_params(axis="y", labelcolor="#dc2626")

    if t_unclamp is not None and t[0] <= t_unclamp <= t[-1]:
        ax1.axvline(t_unclamp, color="#15803d", lw=1.8, ls="-.", label=f"Unclamp (t={t_unclamp:.2f} s)")
        ax1.text(t_unclamp, float(np.max(dz_max)) * 0.85, "  FIXTURE RELEASE\n  (Springback Relaxation)",
                 color="#15803d", fontsize=9, fontweight="bold")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    ax1.set_title("Multi-Stage Fixture Release: In-Clamp Clamping & Free Springback Relaxation")
    return _save(fig, out_dir, "10_springback_fixture_release.png")


def plot_bimetallic_graded_transition(run_dir: Path, out_dir: Path, p_meta: dict = None):
    """
    Renders 09_bimetallic_graded_transition.png demonstrating Option 5:
    Functionally Graded Material (FGM) transition between substrate (SS316L)
    and deposit (IN625), including continuous composition blending, dilution
    tracking across layers, Scheil freezing range, and WRC-1992/Sigma/Laves risk.
    """
    base_name = "SS316L"
    dep_name = "IN625"
    if p_meta:
        base_name = p_meta.get("material_base", base_name)
        dep_name = p_meta.get("material_dep", dep_name)
    
    try:
        from core.multimaterial.graded_transition import (
            blend_weight, interpolate_composition,
            compute_dilution_layer_composition,
            estimate_solidus_liquidus, evaluate_intermetallic_risk
        )
    except Exception:
        import sys
        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root))
        from core.multimaterial.graded_transition import (
            blend_weight, interpolate_composition,
            compute_dilution_layer_composition,
            estimate_solidus_liquidus, evaluate_intermetallic_risk
        )

    comp_base = {'Fe': 65.88, 'Cr': 17.5, 'Ni': 12.0, 'Mo': 2.5, 'Mn': 1.6, 'Si': 0.5, 'C': 0.02, 'Nb': 0.0}
    comp_dep = {'Ni': 60.92, 'Cr': 21.5, 'Mo': 8.5, 'Nb': 3.65, 'Fe': 4.5, 'Ti': 0.2, 'Al': 0.2, 'C': 0.03, 'Mn': 0.25, 'Si': 0.25}

    z_vals = np.linspace(0.0, 35.0, 100) # mm
    z_interface = 15.0 # mm substrate boundary
    
    fe_vals, ni_vals, cr_vals, mo_vals, nb_vals = [], [], [], [], []
    t_sol_vals, t_liq_vals = [], []
    cr_ni_ratios, fn_vals = [], []
    
    for z in z_vals:
        w_base = blend_weight(z, z_start=12.0, z_end=18.0, mode="smoothstep")
        comp = interpolate_composition(comp_base, comp_dep, weight_a=w_base)
        fe_vals.append(comp.get("Fe", 0.0))
        ni_vals.append(comp.get("Ni", 0.0))
        cr_vals.append(comp.get("Cr", 0.0))
        mo_vals.append(comp.get("Mo", 0.0))
        nb_vals.append(comp.get("Nb", 0.0))
        
        ts, tl = estimate_solidus_liquidus(comp)
        t_sol_vals.append(ts)
        t_liq_vals.append(tl)
        
        risk = evaluate_intermetallic_risk(comp)
        cr_ni_ratios.append(risk["cr_ni_ratio"])
        fn_vals.append(risk["ferrite_number_FN"])

    n_passes = 4
    dil_comps = [comp_base]
    for _ in range(n_passes):
        dil_comps.append(compute_dilution_layer_composition(comp_dep, dil_comps[-1], dilution_ratio=0.25))

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    
    # Subplot 1: Continuous composition profile
    ax = axes[0, 0]
    ax.plot(z_vals, fe_vals, label="Fe (wt%)", color="#2563eb", lw=2)
    ax.plot(z_vals, ni_vals, label="Ni (wt%)", color="#059669", lw=2)
    ax.plot(z_vals, cr_vals, label="Cr (wt%)", color="#dc2626", lw=2)
    ax.plot(z_vals, mo_vals, label="Mo (wt%)", color="#7c3aed", lw=2)
    ax.plot(z_vals, nb_vals, label="Nb (wt%)", color="#d97706", lw=2)
    ax.axvline(z_interface, color="#475569", ls="--", lw=1.2, label=f"Interface (z={z_interface} mm)")
    ax.set_xlabel("Build Height z (mm)")
    ax.set_ylabel("Element Concentration (wt%)")
    ax.set_title("Functionally Graded Composition: SS316L -> IN625")
    ax.legend(fontsize=8, loc="center right")
    ax.grid(True)

    # Subplot 2: Layer Dilution Evolution
    ax = axes[0, 1]
    layers = list(range(n_passes + 1))
    ni_pass = [c.get("Ni", 0.0) for c in dil_comps]
    fe_pass = [c.get("Fe", 0.0) for c in dil_comps]
    ax.bar([l - 0.2 for l in layers], fe_pass, width=0.4, label="Fe wt% (Substrate carry-over)", color="#3b82f6")
    ax.bar([l + 0.2 for l in layers], ni_pass, width=0.4, label="Ni wt% (Deposit uptake)", color="#10b981")
    ax.set_xticks(layers)
    ax.set_xticklabels(["Substrate"] + [f"Layer {i}" for i in range(1, n_passes + 1)])
    ax.set_ylabel("Concentration (wt%)")
    ax.set_title("Layer Dilution Kinetics (η = 25% melt pool blend)")
    ax.legend(fontsize=8.5)
    ax.grid(True)

    # Subplot 3: Scheil Freezing Range
    ax = axes[1, 0]
    ax.plot(z_vals, t_liq_vals, label="Liquidus Tliq (°C)", color="#ef4444", lw=2)
    ax.plot(z_vals, t_sol_vals, label="Solidus Tsol (°C)", color="#3b82f6", lw=2)
    ax.fill_between(z_vals, t_sol_vals, t_liq_vals, color="#fca5a5", alpha=0.35, label="Mushy Freezing Zone")
    ax.axvline(z_interface, color="#475569", ls="--", lw=1.2)
    ax.set_xlabel("Build Height z (mm)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("CALPHAD Solidification Range Across Transition")
    ax.legend(fontsize=8.5)
    ax.grid(True)

    # Subplot 4: Embrittlement & WRC-1992 Metallurgical Risk
    ax = axes[1, 1]
    ax.plot(z_vals, cr_ni_ratios, label="Cr_eq / Ni_eq Ratio", color="#b91c1c", lw=2)
    ax.axhline(1.48, color="#15803d", ls=":", label="FA mode lower limit (1.48)")
    ax.axhline(1.95, color="#15803d", ls="-.", label="FA mode upper limit (1.95)")
    ax.set_xlabel("Build Height z (mm)")
    ax.set_ylabel("Cr_eq / Ni_eq", color="#b91c1c")
    ax.tick_params(axis="y", labelcolor="#b91c1c")
    ax.grid(True)

    ax2 = ax.twinx()
    ax2.plot(z_vals, fn_vals, label="Ferrite Number (FN)", color="#6366f1", lw=1.8, ls="--")
    ax2.set_ylabel("WRC-1992 FN", color="#6366f1")
    ax2.tick_params(axis="y", labelcolor="#6366f1")

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8)
    ax.set_title("WRC-1992 Constitution & Solidification Mode Transition")

    return _save(fig, out_dir, "09_bimetallic_graded_transition.png")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WAAM MOOSE thermal plots")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="output directory (default: <moose>/plots)")
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    moose_dir = _moose_dir(run_dir)
    out_dir = args.out if args.out else (moose_dir / "plots")
    out_dir = Path(out_dir)

    rows = _read_csv(moose_dir / "waam_moose_out.csv")
    p_meta = {}
    params_path = run_dir / "parameters.json"
    if params_path.exists():
        try:
            import json
            p_meta.update(json.loads(params_path.read_text()))
        except Exception:
            pass
    meta_path = moose_dir / "waam_moose.i.meta"
    if meta_path.exists():
        try:
            import json
            p_meta.update(json.loads(meta_path.read_text()))
        except Exception:
            pass

    _style()
    produced = []
    for fn in (plot_thermal_envelope, plot_energy_ledger, plot_cap_power,
               plot_melt_pool, plot_fidelity, plot_thermomechanics, plot_ultrasonics):
        p = fn(rows, out_dir)
        if p:
            produced.append(p)
    p = plot_springback(rows, out_dir, p_meta)
    if p:
        produced.append(p)
    p = plot_bimetallic_graded_transition(run_dir, out_dir, p_meta)
    if p:
        produced.append(p)
    p = plot_final_temperature(moose_dir, out_dir)
    if p:
        produced.append(p)

    print(f"[moose_plots] wrote {len(produced)} plots to {out_dir}")
    for p in produced:
        print(f"  {p.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
