# ParaView Postprocessing & Multi-Core Deployment Guide

This guide documents the automated ParaView postprocessing pipeline and multi-core parallel execution configuration for the `waam_arc` case in **beamWeldFoam** (OpenFOAM 2412).

---

## 1. Hardware Profile & Decomposition Strategy

The case is configured for an **Intel Core i9 14th Gen workstation**:

| Hardware Component | Specification | Configuration / Role |
| :--- | :--- | :--- |
| **CPU** | Intel Core i9 14th Gen | 20 physical cores allotted for OpenFOAM MPI |
| **RAM** | 128 GB DDR5 | Large domain & multi-timestep caching in memory |
| **GPU** | NVIDIA T1000 | Hardware-accelerated OpenGL / OptiX ray-tracing in ParaView |
| **Storage** | 2 TB NVMe SSD | High-throughput sequential I/O for `purgeWrite 0;` timesteps |

### Subdomain Decomposition (`system/decomposeParDict`)

The domain is partitioned into **20 subdomains**:
- **Primary Method**: `scotch` (dual-graph partitioning minimizing inter-processor boundary communication).
- **Fallback Method**: `hierarchical` with `(2 2 5)` decomposition:
  - 2 subdomains along X (transverse)
  - 2 subdomains along Y (vertical / depth)
  - 5 subdomains along Z (travel direction)

---

## 2. Running in Parallel on 20 Cores

An automated execution script is provided: `Allrun.parallel`.

### Quick Run
```bash
# Run with default 20 cores (i9-14900 profile)
./Allrun.parallel

# Or explicitly pass core count
./Allrun.parallel 20
```

### What `Allrun.parallel` executes:
1. Validates initial conditions in `0/` (copied from `initial/`).
2. Checks mesh presence or generates via `blockMesh` + `setFields`.
3. Synchronizes `system/decomposeParDict` with the requested core count.
4. Decomposes the mesh into `processor0` ... `processor19` via `decomposePar -force`.
5. Launches parallel solver execution: `mpirun -np 20 beamWeldFoam -parallel 2>&1 | tee solver.log`.
6. Reconstructs the latest timestep via `reconstructPar -latestTime`.
7. Touches `waam_arc.foam` for instant ParaView ingestion.

---

## 3. Automated ParaView Postprocessing

The automated postprocessing script `postprocess_paraview.py` generates publication-ready 2D and 3D visualisations and extracts thermal metrics.

### Executing Headlessly via CLI

#### On macOS:
```bash
/Applications/ParaView-5.13.3.app/Contents/bin/pvpython postprocess_paraview.py
```

#### On Linux / i9 Workstation:
```bash
pvpython postprocess_paraview.py
```

### Generated Artifacts (`postprocessing_visuals/`):
- **`paraview_3d_temperature_haz.png`**: 3D perspective view showing domain bounding box outline, semi-transparent base substrate, Heat Affected Zone (`T >= 1000 K`), and liquid melt pool threshold.
- **`paraview_longitudinal_centerline_slice.png`**: Longitudinal cut along the weld centerline ($X = 0$) showing the thermal plume comet-tail, smooth isotherms (500 K, 800 K, 1000 K, 1200 K, 1400 K, 1723 K), and velocity vectors ($U$).
- **`paraview_transverse_bead_cross_section.png`**: Cross-section perpendicular to torch motion ($Z = -5 \text{ mm}$) displaying penetration depth and bead profile.
- **`waam_thermal_timelapse.gif`**: Animated GIF depicting the motion of the arc heat source along the welding path over time.
- **`waam_visualization.pvsm`**: Complete ParaView pipeline state file.

---

## 4. Interactive GUI Workflows

### Workflow A: Instant State Restoration (Recommended)
1. Launch ParaView GUI (`paraview`).
2. Click **File -> Load State...**.
3. Select `waam_visualization.pvsm`.
4. Choose **Search files under specified directory** and point to `cases/waam_arc`.
5. All three camera layouts, slices, contours, and thresholds load pre-configured.

### Workflow B: Postprocessing Decomposed Cases Directly
If running large parallel cases on the i9 workstation, you do not need to run `reconstructPar`:
1. In ParaView, open `waam_arc.foam`.
2. In the Properties panel, change **Case Type** from `Reconstructed Case` to `Decomposed Case`.
3. Click **Apply**. ParaView will read directly from all 20 `processor*` directories in parallel using multi-threaded I/O on the NVMe SSD.

### Workflow C: Running the Python Script Inside GUI
1. In ParaView GUI, go to **View -> Python Shell**.
2. Click **Run Script** and select `postprocess_paraview.py`.
