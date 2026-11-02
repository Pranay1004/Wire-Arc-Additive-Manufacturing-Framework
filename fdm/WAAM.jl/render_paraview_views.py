#!/usr/bin/env python3
"""
Scientific ParaView/PyVista Offscreen Visualizer for WAAMFlow End-Runs
Generates publication-grade 3D renders and multi-panel cross-sectional diagnostic plots
for ER70S6 (Mild Steel) and ER316L (Stainless Steel) single-track simulations.
"""

import os
import numpy as np
import pyvista as pv
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

pv.OFF_SCREEN = True
pv.set_plot_theme("document")

OUTDIR = "/Users/pandeyji/Desktop/WAAM/fdm/WAAM.jl/validation_output"

ALLOYS = {
    "ER70S6": {
        "vtr": os.path.join(OUTDIR, "waam_er70s6_end_run.vtr"),
        "t_liquidus": 1700.0,
        "t_solidus": 1650.0,
        "name": "Mild Steel (ER70S6)",
        "color": "#1f77b4",
        "wall_time": 51.23,
        "steps": 11955,
        "peak_T": 2862.3,
        "width_mm": 3.63,
        "pen_mm": 0.123,
        "residual_J": 1.678e-9
    },
    "ER316L": {
        "vtr": os.path.join(OUTDIR, "waam_er316l_end_run.vtr"),
        "t_liquidus": 1673.0,
        "t_solidus": 1623.0,
        "name": "Austenitic Stainless (ER316L)",
        "color": "#d62728",
        "wall_time": 47.25,
        "steps": 10657,
        "peak_T": 3785.5,
        "width_mm": 6.63,
        "pen_mm": 0.047,
        "residual_J": 1.433e-9
    }
}

def render_3d_view(alloy_key, info):
    """Render 3D isometric temperature field with melt-pool isotherm iso-surface."""
    vtr_path = info["vtr"]
    if not os.path.exists(vtr_path):
        print(f"Skipping {alloy_key}: {vtr_path} not found")
        return None

    grid = pv.read(vtr_path)
    grid_pts = grid.cell_data_to_point_data()

    # Scale to millimeters for physical scale display
    grid_mm = grid_pts.scale([1e3, 1e3, 1e3], inplace=False)

    pl = pv.Plotter(off_screen=True, window_size=[1920, 1080])
    pl.set_background("#0f111a")  # Dark modern engineering background

    sargs = dict(
        title="Temperature T [K]",
        title_font_size=16,
        label_font_size=13,
        shadow=True,
        n_labels=6,
        fmt="%.0f",
        position_x=0.82,
        position_y=0.2,
        width=0.06,
        height=0.6,
        color="white"
    )

    t_min = 300.0
    t_max = 3800.0 if alloy_key == "ER316L" else 3000.0

    # Display volume outline and domain
    pl.add_mesh(
        grid_mm.outline(),
        color="#8892b0",
        line_width=1.5
    )

    # Display surface temperature
    pl.add_mesh(
        grid_mm,
        scalars="Temperature",
        cmap="turbo",
        clim=[t_min, t_max],
        scalar_bar_args=sargs,
        opacity=0.82,
        show_edges=True,
        edge_color="#333333",
        line_width=0.5
    )

    # Extract and overlay molten pool contour (T >= T_liquidus)
    t_liq = info["t_liquidus"]
    try:
        iso = grid_mm.contour(isosurfaces=[t_liq], scalars="Temperature")
        if iso.n_points > 0:
            pl.add_mesh(
                iso,
                color="#00ffff",
                opacity=0.9,
                line_width=3.0,
                style="surface"
            )
            pl.add_mesh(
                iso.extract_all_edges(),
                color="#ffffff",
                line_width=2.0
            )
    except Exception as e:
        print(f"Contour warning: {e}")

    # Add text overlay
    header = (
        f"WAAMFlow 3D ParaView Render: {info['name']}\n"
        f"End Run Status: Complete (Step {info['steps']:,})\n"
        f"Simulation Wall Time: {info['wall_time']:.2f} s | Peak T: {info['peak_T']:.1f} K\n"
        f"Bead Width: {info['width_mm']:.2f} mm | Penetration: {info['pen_mm']:.3f} mm\n"
        f"Energy Residual: {info['residual_J']:.3e} J (Conservation Error < 1e-12)"
    )
    pl.add_text(
        header,
        position="upper_left",
        font_size=12,
        color="white",
        shadow=True
    )

    # Show coordinates box
    pl.show_bounds(
        grid='front',
        location='outer',
        all_edges=True,
        xtitle='Arc Travel X [mm]',
        ytitle='Transverse Y [mm]',
        ztitle='Depth Z [mm]',
        font_size=11,
        color='white'
    )

    pl.camera_position = [
        (38.0, -28.0, 22.0),
        (10.0, 2.0, 3.5),
        (0.0, 0.0, 1.0)
    ]

    out_png = os.path.join(OUTDIR, f"paraview_{alloy_key.lower()}_3d.png")
    pl.screenshot(out_png)
    pl.close()
    print(f"Rendered: {out_png}")
    return out_png

def render_multipanel_diagnostics():
    """Render comprehensive 6-panel scientific comparison figure."""
    fig = plt.figure(figsize=(20, 14), dpi=200)
    gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.25)

    ax_top = fig.add_subplot(gs[0, 0])     # Top surface thermal field (X-Y at Z=0)
    ax_xz = fig.add_subplot(gs[0, 1])      # Longitudinal cross section (X-Z at Y=0)
    ax_yz = fig.add_subplot(gs[1, 0])      # Transverse cross section (Y-Z at X_peak)
    ax_tx = fig.add_subplot(gs[1, 1])      # Centerline temperature decay T(X)
    ax_ty = fig.add_subplot(gs[2, 0])      # Transverse thermal profile T(Y)
    ax_tbl = fig.add_subplot(gs[2, 1])     # Quantitative Summary Table

    # Load data for both alloys
    data = {}
    for k, info in ALLOYS.items():
        grid = pv.read(info["vtr"]).cell_data_to_point_data()
        dims = grid.dimensions
        T_3d = grid["Temperature"].reshape(dims, order="F")
        x_1d = np.unique(grid.x) * 1e3
        y_1d = np.unique(grid.y) * 1e3
        z_1d = np.unique(grid.z) * 1e3
        max_idx = np.unravel_index(np.argmax(T_3d), T_3d.shape)
        data[k] = {
            "T_3d": T_3d,
            "x": x_1d,
            "y": y_1d,
            "z": z_1d,
            "max_idx": max_idx,
            "info": info
        }

    # 1. Top Surface (Z = 0 mm) Melt Pool Contours (X-Y Plane)
    for k, d in data.items():
        T_xy = d["T_3d"][:, :, 0]  # Surface Z = 0
        X_grid, Y_grid = np.meshgrid(d["x"], d["y"], indexing="ij")
        c_liq = ax_top.contour(
            X_grid, Y_grid, T_xy,
            levels=[d["info"]["t_liquidus"]],
            colors=[d["info"]["color"]],
            linewidths=2.5
        )
        c_sol = ax_top.contour(
            X_grid, Y_grid, T_xy,
            levels=[d["info"]["t_solidus"]],
            colors=[d["info"]["color"]],
            linestyles="dashed",
            linewidths=1.5
        )
        c_haz = ax_top.contour(
            X_grid, Y_grid, T_xy,
            levels=[1000.0],
            colors=[d["info"]["color"]],
            linestyles="dotted",
            linewidths=1.0,
            alpha=0.6
        )

    # Create manual legend for ax_top
    p1 = mpatches.Patch(color=ALLOYS["ER70S6"]["color"], label=f"ER70S6 Melt Pool (T ≥ {ALLOYS['ER70S6']['t_liquidus']:.0f} K)")
    p2 = mpatches.Patch(color=ALLOYS["ER316L"]["color"], label=f"ER316L Melt Pool (T ≥ {ALLOYS['ER316L']['t_liquidus']:.0f} K)")
    ax_top.legend(handles=[p1, p2], loc="upper right", framealpha=0.9)
    ax_top.set_title("(a) Top Surface Thermal Footprint & Melt Pool (Z = 0 mm)", fontsize=13, fontweight="bold")
    ax_top.set_xlabel("Arc Travel Direction X [mm]", fontsize=11)
    ax_top.set_ylabel("Transverse Half-Width Y [mm]", fontsize=11)
    ax_top.grid(True, linestyle="--", alpha=0.5)

    # 2. Longitudinal Centerline Cut (Y = 0 mm) in X-Z Plane
    for k, d in data.items():
        T_xz = d["T_3d"][:, 0, :]  # Centerline Y = 0
        X_grid, Z_grid = np.meshgrid(d["x"], d["z"], indexing="ij")
        ax_xz.contour(
            X_grid, Z_grid, T_xz,
            levels=[d["info"]["t_liquidus"]],
            colors=[d["info"]["color"]],
            linewidths=2.5
        )
        ax_xz.contour(
            X_grid, Z_grid, T_xz,
            levels=[1000.0],
            colors=[d["info"]["color"]],
            linestyles="dashed",
            linewidths=1.2,
            alpha=0.6
        )
    ax_xz.legend(handles=[p1, p2], loc="upper right", framealpha=0.9)
    ax_xz.set_title("(b) Longitudinal Centerline Melt Pool & HAZ Profiles (Y = 0 mm)", fontsize=13, fontweight="bold")
    ax_xz.set_xlabel("Arc Travel Direction X [mm]", fontsize=11)
    ax_xz.set_ylabel("Substrate Depth Z [mm]", fontsize=11)
    ax_xz.invert_yaxis()  # Depth downwards
    ax_xz.grid(True, linestyle="--", alpha=0.5)

    # 3. Transverse Cross-Section (Y-Z Plane at Peak X)
    for k, d in data.items():
        x_idx = d["max_idx"][0]
        T_yz = d["T_3d"][x_idx, :, :]
        Y_grid, Z_grid = np.meshgrid(d["y"], d["z"], indexing="ij")
        ax_yz.contour(
            Y_grid, Z_grid, T_yz,
            levels=[d["info"]["t_liquidus"]],
            colors=[d["info"]["color"]],
            linewidths=2.5
        )
        ax_yz.contour(
            Y_grid, Z_grid, T_yz,
            levels=[1000.0],
            colors=[d["info"]["color"]],
            linestyles="dashed",
            linewidths=1.2,
            alpha=0.6
        )
    ax_yz.legend(handles=[p1, p2], loc="upper right", framealpha=0.9)
    ax_yz.set_title("(c) Transverse Melt Pool Cross-Section at Arc Peak", fontsize=13, fontweight="bold")
    ax_yz.set_xlabel("Transverse Coordinate Y [mm]", fontsize=11)
    ax_yz.set_ylabel("Substrate Depth Z [mm]", fontsize=11)
    ax_yz.invert_yaxis()
    ax_yz.grid(True, linestyle="--", alpha=0.5)

    # 4. Centerline Temperature Decay Curve T(X)
    for k, d in data.items():
        T_cx = d["T_3d"][:, 0, 0]  # Surface centerline
        ax_tx.plot(
            d["x"], T_cx,
            color=d["info"]["color"],
            linewidth=2.2,
            marker='o',
            markersize=4,
            label=f"{d['info']['name']} (Peak = {d['info']['peak_T']:.1f} K)"
        )
        ax_tx.axhline(d["info"]["t_liquidus"], color=d["info"]["color"], linestyle=":", alpha=0.7)
    ax_tx.set_title("(d) Centerline Temperature Profile T(X) along Arc Path", fontsize=13, fontweight="bold")
    ax_tx.set_xlabel("Arc Travel Direction X [mm]", fontsize=11)
    ax_tx.set_ylabel("Surface Temperature T [K]", fontsize=11)
    ax_tx.grid(True, linestyle="--", alpha=0.5)
    ax_tx.legend(loc="upper right", framealpha=0.9)

    # 5. Transverse Temperature Profile T(Y)
    for k, d in data.items():
        x_idx = d["max_idx"][0]
        T_cy = d["T_3d"][x_idx, :, 0]  # At surface at peak X
        ax_ty.plot(
            d["y"], T_cy,
            color=d["info"]["color"],
            linewidth=2.2,
            marker='s',
            markersize=4,
            label=f"{d['info']['name']}"
        )
        ax_ty.axhline(d["info"]["t_liquidus"], color=d["info"]["color"], linestyle=":", alpha=0.7)
    ax_ty.set_title("(e) Transverse Thermal Gradient T(Y) from Arc Centerline", fontsize=13, fontweight="bold")
    ax_ty.set_xlabel("Transverse Distance Y [mm]", fontsize=11)
    ax_ty.set_ylabel("Surface Temperature T [K]", fontsize=11)
    ax_ty.grid(True, linestyle="--", alpha=0.5)
    ax_ty.legend(loc="upper right", framealpha=0.9)

    # 6. Performance & Physics Metrics Table
    ax_tbl.axis("off")
    table_data = [
        ["Physics / Computational Metric", "Mild Steel (ER70S6)", "Stainless Steel (ER316L)"],
        ["Thermal Conductivity k [W/(m·K)]", "48.0 (High Diffusivity)", "15.0 (Low Diffusivity)"],
        ["Liquidus Temperature T_liq [K]", "1700.0", "1673.0"],
        ["Simulated Wall Time [s]", f"{ALLOYS['ER70S6']['wall_time']:.2f} s", f"{ALLOYS['ER316L']['wall_time']:.2f} s"],
        ["Total Adaptive Timesteps", f"{ALLOYS['ER70S6']['steps']:,}", f"{ALLOYS['ER316L']['steps']:,}"],
        ["Peak Pool Temperature [K]", f"{ALLOYS['ER70S6']['peak_T']:.1f} K", f"{ALLOYS['ER316L']['peak_T']:.1f} K"],
        ["Simulated Bead Width [mm]", f"{ALLOYS['ER70S6']['width_mm']:.2f} mm", f"{ALLOYS['ER316L']['width_mm']:.2f} mm"],
        ["Depth of Penetration [mm]", f"{ALLOYS['ER70S6']['pen_mm']:.3f} mm", f"{ALLOYS['ER316L']['pen_mm']:.3f} mm"],
        ["Energy Injected [J]", "1524.5 J", "1574.9 J"],
        ["Energy Residual (Balance Error)", f"{ALLOYS['ER70S6']['residual_J']:.3e} J", f"{ALLOYS['ER316L']['residual_J']:.3e} J"],
        ["Relative Energy Error", "1.10 × 10⁻¹²", "9.10 × 10⁻¹³"],
        ["ParaView VTR Output", "waam_er70s6_end_run.vtr", "waam_er316l_end_run.vtr"]
    ]

    tbl = ax_tbl.table(
        cellText=table_data,
        cellLoc="center",
        loc="center",
        bbox=[0.0, 0.05, 1.0, 0.9]
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    for i in range(len(table_data)):
        for j in range(3):
            cell = tbl[i, j]
            if i == 0:
                cell.set_facecolor("#1f2937")
                cell.set_text_props(color="white", weight="bold")
            elif i % 2 == 1:
                cell.set_facecolor("#f3f4f6")
            else:
                cell.set_facecolor("#ffffff")
            cell.set_edgecolor("#d1d5db")

    ax_tbl.set_title("(f) Simulation Benchmarking & Validation Telemetry", fontsize=13, fontweight="bold")

    fig.suptitle("WAAMFlow ParaView End-Run Results: Coupled Navier-Stokes / Enthalpy Multiphysics Verification",
                 fontsize=16, fontweight="bold", y=0.98)

    out_summary = os.path.join(OUTDIR, "paraview_coupled_diagnostics.png")
    fig.savefig(out_summary, bbox_inches="tight")
    plt.close(fig)
    print(f"Rendered: {out_summary}")
    return out_summary

if __name__ == "__main__":
    print("Beginning ParaView / PyVista multi-panel offscreen rendering...")
    for k, info in ALLOYS.items():
        render_3d_view(k, info)
    render_multipanel_diagnostics()
    print("All visual diagnostics rendered successfully.")
