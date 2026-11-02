#!/usr/bin/env python3
"""
Comprehensive Melt Pool Analysis & Comparative Post-Processing:
Baseline WAAM vs Ultrasonic Vibration-Assisted (UVA) WAAM
=========================================================
Extracts physical CFD fields (Temperature, Velocity U, Phase alpha)
from OpenFOAM cases and quantifies:
  1. Melt pool geometry: Length, Width, Penetration Depth, Volume
  2. Hydrodynamic circulation: Marangoni vs Acoustic Streaming vortex
  3. Thermal field: Peak temperature, cooling rates, thermal gradients
  4. Time-series evolution across available timesteps

Author: UVA-WAAM Module
"""

import os
import re
import glob
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from scipy.interpolate import griddata

# ─────────────────────────────────────────────────────────────────────────────
# 1. OpenFOAM ASCII Field Parser
# ─────────────────────────────────────────────────────────────────────────────
def parse_foam_scalar(file_path):
    """Parses an OpenFOAM scalar volScalarField file into a 1D numpy array."""
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", errors="ignore") as f:
        content = f.read()

    # Check for uniform
    uniform_match = re.search(r"internalField\s+uniform\s+([-\d.eE+]+);", content)
    if uniform_match:
        val = float(uniform_match.group(1))
        # Find cell count if possible, else return single float
        n_match = re.search(r"(\d+)\s*\(\s*", content)
        n_cells = int(n_match.group(1)) if n_match else 34944
        return np.full(n_cells, val, dtype=np.float64)

    # Nonuniform list
    match = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\((.*?)\)\s*;", content, re.DOTALL)
    if not match:
        return None
    n_cells = int(match.group(1))
    data_str = match.group(2)
    # Fast float extraction
    data = np.fromstring(data_str, sep="\n", dtype=np.float64)
    if len(data) != n_cells:
        # fallback whitespace split
        data = np.array([float(x) for x in data_str.split()], dtype=np.float64)
    return data

def parse_foam_vector(file_path):
    """Parses an OpenFOAM vector volVectorField file into an (N, 3) numpy array."""
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", errors="ignore") as f:
        content = f.read()

    uniform_match = re.search(r"internalField\s+uniform\s+\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\);", content)
    if uniform_match:
        vx = float(uniform_match.group(1))
        vy = float(uniform_match.group(2))
        vz = float(uniform_match.group(3))
        n_cells = 34944
        arr = np.empty((n_cells, 3), dtype=np.float64)
        arr[:, 0] = vx
        arr[:, 1] = vy
        arr[:, 2] = vz
        return arr

    match = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)\s*\((.*?)\)\s*;", content, re.DOTALL)
    if not match:
        return None
    n_cells = int(match.group(1))
    raw_tuples = re.findall(r"\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)", match.group(2))
    if len(raw_tuples) == n_cells:
        return np.array(raw_tuples, dtype=np.float64)
    
    # Fallback line-by-line
    data = []
    for line in match.group(2).strip().splitlines():
        line = line.strip().strip("()")
        parts = line.split()
        if len(parts) == 3:
            data.append([float(parts[0]), float(parts[1]), float(parts[2])])
    return np.array(data, dtype=np.float64)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Main Analysis Pipeline
# ─────────────────────────────────────────────────────────────────────────────
def analyze_case(case_dir, label="Case"):
    print(f"\n[{label}] Scanning {case_dir}...")
    
    # Load cell centres
    cx = parse_foam_scalar(os.path.join(case_dir, "0", "Cx"))
    cy = parse_foam_scalar(os.path.join(case_dir, "0", "Cy"))
    cz = parse_foam_scalar(os.path.join(case_dir, "0", "Cz"))
    
    if cx is None or cy is None or cz is None:
        raise RuntimeError(f"Cell centres missing in {case_dir}/0. Run writeCellCentres first.")
    
    n_cells = len(cx)
    print(f"[{label}] Loaded {n_cells} cell centres.")
    
    # Find numeric time directories
    time_dirs = []
    for entry in os.listdir(case_dir):
        path = os.path.join(case_dir, entry)
        if os.path.isdir(path):
            try:
                t_val = float(entry)
                time_dirs.append((t_val, entry))
            except ValueError:
                pass
    time_dirs.sort(key=lambda x: x[0])
    
    print(f"[{label}] Found {len(time_dirs)} time directories: {[t[1] for t in time_dirs[:5]]} ... {[t[1] for t in time_dirs[-3:]]}")
    
    # Estimate cell volume based on domain
    # Domain: 30mm x 13mm x 50mm, 24 x 26 x 56 cells -> dx = 1.25mm, dy = 0.5mm, dz = 0.893mm
    # V_cell ~ 1.25e-3 * 0.5e-3 * 0.893e-3 ~ 5.58e-10 m^3
    dx = (cx.max() - cx.min()) / 24.0
    dy = (cy.max() - cy.min()) / 26.0
    dz = (cz.max() - cz.min()) / 56.0
    v_cell = dx * dy * dz
    
    T_LIQ = 1928.0   # K
    T_SOL = 1878.0   # K
    Y_SURF = 0.003   # m (top substrate surface)
    
    history = []
    latest_field_data = None
    
    for t_val, t_str in time_dirs:
        t_dir = os.path.join(case_dir, t_str)
        T_field = parse_foam_scalar(os.path.join(t_dir, "Temperature"))
        U_field = parse_foam_vector(os.path.join(t_dir, "U"))
        alpha_field = parse_foam_scalar(os.path.join(t_dir, "alpha.phase1"))
        
        if T_field is None or U_field is None:
            continue
        if alpha_field is None:
            alpha_field = np.ones(n_cells)
            
        U_mag = np.linalg.norm(U_field, axis=1)
        
        # Melt pool definition: liquid metal
        molten_mask = (T_field >= T_LIQ) & (alpha_field >= 0.5)
        mushy_mask = (T_field >= T_SOL) & (T_field < T_LIQ) & (alpha_field >= 0.5)
        
        n_molten = np.sum(molten_mask)
        pool_vol_mm3 = n_molten * v_cell * 1e9  # mm^3
        
        if n_molten > 0:
            x_pool = cx[molten_mask]
            y_pool = cy[molten_mask]
            z_pool = cz[molten_mask]
            
            width_mm = (x_pool.max() - x_pool.min()) * 1e3
            depth_mm = max(0.0, (y_pool.max() - Y_SURF) * 1e3)
            length_mm = (z_pool.max() - z_pool.min()) * 1e3
            
            u_max_pool = U_mag[molten_mask].max()
            u_mean_pool = U_mag[molten_mask].mean()
            t_max_pool = T_field[molten_mask].max()
        else:
            width_mm = 0.0
            depth_mm = 0.0
            length_mm = 0.0
            u_max_pool = 0.0
            u_mean_pool = 0.0
            t_max_pool = T_field.max()
            
        rec = {
            "time_s": t_val,
            "time_str": t_str,
            "molten_cells": int(n_molten),
            "pool_volume_mm3": float(pool_vol_mm3),
            "width_mm": float(width_mm),
            "depth_mm": float(depth_mm),
            "length_mm": float(length_mm),
            "u_max_pool_m_s": float(u_max_pool),
            "u_mean_pool_m_s": float(u_mean_pool),
            "t_max_K": float(t_max_pool)
        }
        history.append(rec)
        
        latest_field_data = {
            "time_s": t_val,
            "T": T_field,
            "U": U_field,
            "U_mag": U_mag,
            "alpha": alpha_field,
            "molten_mask": molten_mask
        }
        
    print(f"[{label}] Processed {len(history)} snapshots.")
    return {
        "cx": cx, "cy": cy, "cz": cz,
        "history": history,
        "latest": latest_field_data
    }

def main():
    base_dir = "/Users/pandeyji/Desktop/WAAM/beamweldfoam/beamWeldFoam_ported/cases"
    uva_case_dir = os.path.join(base_dir, "uva_pranay")
    baseline_case_dir = os.path.join(base_dir, "waam_arc")
    
    out_dir = os.path.join(uva_case_dir, "meltpool_analysis_results")
    os.makedirs(out_dir, exist_ok=True)
    
    print("=" * 70)
    print(" Melt Pool Field Comparative Post-Processor (OpenFOAM)")
    print(f" UVA Case:      {uva_case_dir}")
    print(f" Baseline Case: {baseline_case_dir}")
    print(f" Output Dir:    {out_dir}")
    print("=" * 70)
    
    uva_res = analyze_case(uva_case_dir, label="UVA (+Acoustics)")
    base_res = analyze_case(baseline_case_dir, label="Baseline (No Acoustics)")
    
    cx = uva_res["cx"]
    cy = uva_res["cy"]
    cz = uva_res["cz"]
    
    # ─────────────────────────────────────────────────────────────────────────
    # 3. Longitudinal Cross-Section (X ~ 0 plane) Slice Comparison
    # ─────────────────────────────────────────────────────────────────────────
    print("\nGenerating Figure 1: Longitudinal Cross-Section Comparison (X=0 plane)...")
    tol_x = 1.0e-3
    mid_mask = np.abs(cx) <= tol_x
    
    z_mid = cz[mid_mask] * 1e3   # mm
    y_mid = cy[mid_mask] * 1e3   # mm
    
    T_uva = uva_res["latest"]["T"][mid_mask]
    T_base = base_res["latest"]["T"][mid_mask]
    
    Uz_uva = uva_res["latest"]["U"][mid_mask, 2]
    Uy_uva = uva_res["latest"]["U"][mid_mask, 1]
    
    Uz_base = base_res["latest"]["U"][mid_mask, 2]
    Uy_base = base_res["latest"]["U"][mid_mask, 1]
    
    grid_z, grid_y = np.mgrid[z_mid.min():z_mid.max():150j, y_mid.min():y_mid.max():100j]
    
    grid_T_uva = griddata((z_mid, y_mid), T_uva, (grid_z, grid_y), method="cubic", fill_value=300.0)
    grid_T_base = griddata((z_mid, y_mid), T_base, (grid_z, grid_y), method="cubic", fill_value=300.0)
    
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True, sharey=True)
    
    # Clean up any NaN from interpolation and eliminate interpolation undershoot (<300K)
    grid_T_uva = np.nan_to_num(grid_T_uva, nan=300.0)
    grid_T_base = np.nan_to_num(grid_T_base, nan=300.0)
    grid_T_uva = np.clip(grid_T_uva, 300.0, None)
    grid_T_base = np.clip(grid_T_base, 300.0, None)
    
    # Dynamic colormap based on actual thermal field
    T_max_plot = max(float(T_uva.max()), float(T_base.max()), 1000.0)
    cmap = plt.cm.inferno
    norm = Normalize(vmin=300.0, vmax=T_max_plot)
    
    levels_contour = np.linspace(300.0, T_max_plot, 60)
    isotherm_levels = [T_val for T_val in [400.0, 600.0, 800.0, 1000.0, 1200.0, 1400.0] if T_val < T_max_plot]
    
    # (a) Baseline
    ax0 = axes[0]
    ax0.set_facecolor("black")
    c0 = ax0.contourf(grid_z, grid_y, grid_T_base, levels=levels_contour, cmap=cmap, norm=norm, extend="both")
    if isotherm_levels:
        cs0 = ax0.contour(grid_z, grid_y, grid_T_base, levels=isotherm_levels, colors="white", linewidths=1.2, alpha=0.85)
        ax0.clabel(cs0, inline=True, fontsize=8, fmt="%d K")
    # Substrate line
    ax0.axhline(3.0, color="cyan", linestyle=":", linewidth=1.5, label="Substrate Surface (Y=3mm)")
    ax0.set_title(f"(a) Baseline WAAM (No Ultrasonics) — Longitudinal Cross-Section (t = {base_res['latest']['time_s']:.3f} s)\n"
                  f"Peak T = {base_res['latest']['T'].max():.1f} K | Ambient Reference: 300 K", fontsize=11, fontweight="bold")
    ax0.set_ylabel("Depth Y (mm)", fontsize=10)
    ax0.invert_yaxis()
    ax0.grid(alpha=0.25, color="gray", linestyle="--")
    
    # (b) UVA
    ax1 = axes[1]
    ax1.set_facecolor("black")
    c1 = ax1.contourf(grid_z, grid_y, grid_T_uva, levels=levels_contour, cmap=cmap, norm=norm, extend="both")
    if isotherm_levels:
        cs1 = ax1.contour(grid_z, grid_y, grid_T_uva, levels=isotherm_levels, colors="white", linewidths=1.2, alpha=0.85)
        ax1.clabel(cs1, inline=True, fontsize=8, fmt="%d K")
    ax1.axhline(3.0, color="cyan", linestyle=":", linewidth=1.5, label="Substrate Surface (Y=3mm)")
    
    # Quiver of acoustic velocity vectors
    skip = 4
    sub_mask = (T_uva >= 350.0)
    if np.sum(sub_mask) > 0:
        ax1.quiver(z_mid[sub_mask][::skip], y_mid[sub_mask][::skip],
                   Uz_uva[sub_mask][::skip], Uy_uva[sub_mask][::skip],
                   color="lime", scale=0.4, width=0.003, alpha=0.85, label="Melt Flow Vectors")
    
    ax1.set_title(f"(b) UVA-WAAM (With Acoustic Streaming Body Force 23.68 m/s²) — (t = {uva_res['latest']['time_s']:.3f} s)\n"
                  f"Peak T = {uva_res['latest']['T'].max():.1f} K | Acoustic Circulating Plume", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Travel Direction Z (mm)", fontsize=10)
    ax1.set_ylabel("Depth Y (mm)", fontsize=10)
    ax1.grid(alpha=0.25, color="gray", linestyle="--")
    
    # Colorbar
    cbar_ax = fig.add_axes([0.92, 0.15, 0.02, 0.7])
    cb = fig.colorbar(c1, cax=cbar_ax)
    cb.set_label("Temperature (K)", fontsize=11, fontweight="bold")
    
    fig_path1 = os.path.join(out_dir, "meltpool_longitudinal_comparison.png")
    plt.savefig(fig_path1, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"Saved: {fig_path1}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 4. Transverse Cross-Section (Z ~ Z_torch for each case) Bead Profile
    # ─────────────────────────────────────────────────────────────────────────
    print("\nGenerating Figure 2: Transverse Bead Profile Comparison (Z ~ Z_torch)...")
    # Identify torch center Z individually for Baseline and UVA
    z_torch_base = cz[base_res["latest"]["T"].argmax()]
    z_torch_uva = cz[uva_res["latest"]["T"].argmax()]
    tol_z = 1.5e-3
    
    cs_mask_base = np.abs(cz - z_torch_base) <= tol_z
    cs_mask_uva = np.abs(cz - z_torch_uva) <= tol_z
    
    x_cs_b = cx[cs_mask_base] * 1e3
    y_cs_b = cy[cs_mask_base] * 1e3
    T_base_cs = base_res["latest"]["T"][cs_mask_base]
    
    x_cs_u = cx[cs_mask_uva] * 1e3
    y_cs_u = cy[cs_mask_uva] * 1e3
    T_uva_cs = uva_res["latest"]["T"][cs_mask_uva]
    
    grid_x_b, grid_y_b = np.mgrid[x_cs_b.min():x_cs_b.max():120j, y_cs_b.min():y_cs_b.max():100j]
    grid_T_base_cs = np.nan_to_num(griddata((x_cs_b, y_cs_b), T_base_cs, (grid_x_b, grid_y_b), method="cubic", fill_value=300.0), nan=300.0)
    grid_T_base_cs = np.clip(grid_T_base_cs, 300.0, None)
    
    grid_x_u, grid_y_u = np.mgrid[x_cs_u.min():x_cs_u.max():120j, y_cs_u.min():y_cs_u.max():100j]
    grid_T_uva_cs = np.nan_to_num(griddata((x_cs_u, y_cs_u), T_uva_cs, (grid_x_u, grid_y_u), method="cubic", fill_value=300.0), nan=300.0)
    grid_T_uva_cs = np.clip(grid_T_uva_cs, 300.0, None)
    
    fig, (ax_b, ax_u) = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    plt.subplots_adjust(wspace=0.25)
    
    # Baseline cross-section
    ax_b.set_facecolor("black")
    cb0 = ax_b.contourf(grid_x_b, grid_y_b, grid_T_base_cs, levels=levels_contour, cmap=cmap, norm=norm, extend="both")
    if isotherm_levels:
        cs_b = ax_b.contour(grid_x_b, grid_y_b, grid_T_base_cs, levels=isotherm_levels, colors="white", linewidths=1.2, alpha=0.85)
        ax_b.clabel(cs_b, inline=True, fontsize=8, fmt="%d K")
    ax_b.axhline(3.0, color="cyan", linestyle=":", linewidth=1.5, label="Substrate Top")
    ax_b.set_title(f"Baseline Transverse Bead\n(Z = {z_torch_base*1e3:.1f} mm, t = {base_res['latest']['time_s']:.3f} s) | Peak T = {T_base_cs.max():.1f} K", fontsize=10, fontweight="bold")
    ax_b.set_xlabel("Transverse X (mm)", fontsize=10)
    ax_b.set_ylabel("Depth Y (mm)", fontsize=10)
    ax_b.invert_yaxis()
    ax_b.grid(alpha=0.25, color="gray", linestyle="--")
    
    # UVA cross-section
    ax_u.set_facecolor("black")
    cb1 = ax_u.contourf(grid_x_u, grid_y_u, grid_T_uva_cs, levels=levels_contour, cmap=cmap, norm=norm, extend="both")
    if isotherm_levels:
        cs_u = ax_u.contour(grid_x_u, grid_y_u, grid_T_uva_cs, levels=isotherm_levels, colors="white", linewidths=1.2, alpha=0.85)
        ax_u.clabel(cs_u, inline=True, fontsize=8, fmt="%d K")
    ax_u.axhline(3.0, color="cyan", linestyle=":", linewidth=1.5, label="Substrate Top")
    ax_u.set_title(f"UVA-WAAM Transverse Bead\n(Z = {z_torch_uva*1e3:.1f} mm, t = {uva_res['latest']['time_s']:.3f} s) | Peak T = {T_uva_cs.max():.1f} K", fontsize=10, fontweight="bold")
    ax_u.set_xlabel("Transverse X (mm)", fontsize=10)
    ax_u.grid(alpha=0.25, color="gray", linestyle="--")
    
    fig_path2 = os.path.join(out_dir, "meltpool_transverse_comparison.png")
    plt.savefig(fig_path2, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"Saved: {fig_path2}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 5. Time-Series Melt Pool Metrics Evolution
    # ─────────────────────────────────────────────────────────────────────────
    print("\nGenerating Figure 3: Melt Pool Dimensions & Hydrodynamics Evolution...")
    
    t_uva_s = [h["time_s"] * 1e3 for h in uva_res["history"]]  # ms
    v_uva = [h["pool_volume_mm3"] for h in uva_res["history"]]
    d_uva = [h["depth_mm"] for h in uva_res["history"]]
    w_uva = [h["width_mm"] for h in uva_res["history"]]
    umax_uva = [h["u_max_pool_m_s"] for h in uva_res["history"]]
    tmax_uva = [h["t_max_K"] for h in uva_res["history"]]
    
    t_base_s = [h["time_s"] * 1e3 for h in base_res["history"]]
    v_base = [h["pool_volume_mm3"] for h in base_res["history"]]
    d_base = [h["depth_mm"] for h in base_res["history"]]
    w_base = [h["width_mm"] for h in base_res["history"]]
    umax_base = [h["u_max_pool_m_s"] for h in base_res["history"]]
    tmax_base = [h["t_max_K"] for h in base_res["history"]]
    
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    
    # (a) Volume evolution
    axes[0, 0].plot(t_uva_s, v_uva, "ro-", linewidth=2.0, markersize=4, label=f"UVA (to {uva_res['latest']['time_s']*1e3:.0f} ms)")
    axes[0, 0].plot(t_base_s, v_base, "b--", linewidth=1.5, label=f"Baseline (to {base_res['latest']['time_s']:.2f} s)")
    axes[0, 0].set_title("Melt Pool Volume Evolution $V_{pool}(t)$", fontweight="bold")
    axes[0, 0].set_xlabel("Physical Time (ms)")
    axes[0, 0].set_ylabel(r"Melt Pool Volume ($\mathrm{mm}^3$)")
    axes[0, 0].set_ylim(-0.01, max(0.1, max(v_uva + v_base) * 1.1))
    axes[0, 0].grid(alpha=0.3)
    axes[0, 0].legend()
    
    # (b) Penetration Depth
    axes[0, 1].plot(t_uva_s, d_uva, "bs-", linewidth=2.0, markersize=4, label="UVA Depth")
    axes[0, 1].plot(t_uva_s, w_uva, "c^--", linewidth=1.5, markersize=4, label="UVA Width")
    axes[0, 1].plot(t_base_s, d_base, "k:", linewidth=1.5, label="Baseline Depth")
    axes[0, 1].set_title("Melt Pool Dimensions: Depth & Width", fontweight="bold")
    axes[0, 1].set_xlabel("Physical Time (ms)")
    axes[0, 1].set_ylabel("Dimension (mm)")
    axes[0, 1].set_ylim(-0.01, max(0.2, max(d_uva + w_uva + d_base) * 1.1))
    axes[0, 1].grid(alpha=0.3)
    axes[0, 1].legend()
    
    # (c) Max Circulation Velocity
    axes[1, 0].plot(t_uva_s, umax_uva, "mo-", linewidth=2.0, markersize=4, label=r"UVA $|\mathbf{U}|_{max}$")
    axes[1, 0].plot(t_base_s, umax_base, "b--", linewidth=1.5, label=r"Baseline $|\mathbf{U}|_{max}$")
    axes[1, 0].set_title("Hydrodynamic Flow Velocity in Melt Pool", fontweight="bold")
    axes[1, 0].set_xlabel("Physical Time (ms)")
    axes[1, 0].set_ylabel("Velocity (m/s)")
    axes[1, 0].set_ylim(-0.01, max(0.1, max(umax_uva + umax_base) * 1.1))
    axes[1, 0].grid(alpha=0.3)
    axes[1, 0].legend()
    
    # (d) Peak Temperature: Compare UVA vs Baseline
    axes[1, 1].plot(t_uva_s, tmax_uva, "ro-", linewidth=2.0, markersize=4, label=f"UVA $T_{{max}}$ (to {uva_res['latest']['time_s']*1e3:.0f} ms)")
    axes[1, 1].plot(t_base_s, tmax_base, "k.-", linewidth=1.5, alpha=0.8, label=f"Baseline $T_{{max}}$ (to {base_res['latest']['time_s']:.2f} s)")
    axes[1, 1].axhline(1928.0, color="r", linestyle="--", label=r"Liquidus $T_{liq} = 1928\ \mathrm{K}$")
    axes[1, 1].axhline(1878.0, color="orange", linestyle=":", label=r"Solidus $T_{sol} = 1878\ \mathrm{K}$")
    axes[1, 1].set_title("Thermal Response: Peak Pool Temperature", fontweight="bold")
    axes[1, 1].set_xlabel("Physical Time (ms)")
    axes[1, 1].set_ylabel("Temperature (K)")
    axes[1, 1].grid(alpha=0.3)
    axes[1, 1].legend(loc="lower right")
    
    plt.tight_layout()
    fig_path3 = os.path.join(out_dir, "meltpool_metrics_evolution.png")
    plt.savefig(fig_path3, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"Saved: {fig_path3}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 6. Save JSON Summary
    # ─────────────────────────────────────────────────────────────────────────
    summary_data = {
        "case_uva": uva_case_dir,
        "case_baseline": baseline_case_dir,
        "comparison_metrics": {
            "uva_final_time_s": uva_res["history"][-1]["time_s"],
            "uva_pool_volume_mm3": uva_res["history"][-1]["pool_volume_mm3"],
            "uva_pool_depth_mm": uva_res["history"][-1]["depth_mm"],
            "uva_pool_width_mm": uva_res["history"][-1]["width_mm"],
            "uva_pool_length_mm": uva_res["history"][-1]["length_mm"],
            "uva_u_max_m_s": uva_res["history"][-1]["u_max_pool_m_s"],
            "uva_t_max_K": uva_res["history"][-1]["t_max_K"],
            "baseline_pool_depth_mm": base_res["history"][-1]["depth_mm"],
            "depth_increase_pct": float(
                ((uva_res["history"][-1]["depth_mm"] - base_res["history"][-1]["depth_mm"]) /
                 max(1e-3, base_res["history"][-1]["depth_mm"])) * 100.0
            ) if base_res["history"][-1]["depth_mm"] > 0 else 0.0
        },
        "uva_history": uva_res["history"],
        "baseline_history": base_res["history"]
    }
    
    json_path = os.path.join(out_dir, "meltpool_comparison_summary.json")
    with open(json_path, "w") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Saved JSON: {json_path}")
    print("\nPost-processing complete successfully!")

if __name__ == "__main__":
    main()
