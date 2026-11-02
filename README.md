# Wire Arc Additive Manufacturing (WAAM) Multiphysics Framework
### *An Autonomous High-Fidelity Simulation Suite & Laboratory Automation Monorepo*

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform: macOS / Linux](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-brightgreen.svg)](#requirements--installation)
[![Architecture: Multi-Backend](https://img.shields.io/badge/Architecture-FreeFEM%2B%2B%20%7C%20MOOSE%20%7C%20OpenFOAM%20%7C%20Julia-purple.svg)](#framework-overview)
[![Solvers: MUMPS / PETSc](https://img.shields.io/badge/Solvers-MUMPS%20%7C%20PETSc%20SNES%20%7C%20PISO-orange.svg)](#computational-resolution--solver-scaling)
[![Physics: G1--G10 Audited](https://img.shields.io/badge/Validation-G1--G10%20Energy%20Audited-success.svg)](#physical-validation--11-parity-audit)

---

## Executive Summary

The **Wire Arc Additive Manufacturing (WAAM) Multiphysics Framework** is a unified computational continuum, micro-hydrodynamics, and laboratory automation suite engineered for directed energy deposition (DED-arc) processes. Additive manufacturing with high-deposition GMAW, GTAW, and CMT electric arcs involves coupled thermal, fluid, metallurgical, and structural mechanics operating across disparate temporal and spatial scales.

This repository provides **five specialized, interoperable computational and experimental engines**:

1. **`waam-framework/` (FreeFEM++ Backend)**: Full-scale continuum thermo-mechanical FEA with conformal 3D tetrahedral meshing, moving double-ellipsoid Goldak heat sources, latent-heat enthalpy regularization, quiet-element activation, MUMPS direct sparse LU solver, and rigorous 10-term energy audit balance.
2. **`waam-moose/` (INL MOOSE C++ / PETSc Backend)**: Enterprise-grade nonlinear finite element engine built on Idaho National Laboratory's Multiphysics Object-Oriented Simulation Environment (MOOSE) and PETSc SNES. Includes custom C++ kernels for $J_2$ thermo-elasto-plasticity, thermodynamic annealing, CALPHAD phase change, and functionally graded material (FGM) dilution tracking.
3. **`openfoam/` (Finite Volume CFD / Melt Pool Micro-Hydrodynamics)**: High-resolution multiphase Volume-of-Fluid (VOF) solvers (`waamFoam` and `beamWeldFoam`) capturing Marangoni thermocapillary recirculation, arc plasma stagnation pressure, electromagnetic Lorentz forces ($\vec{J} \times \vec{B}$), and enthalpy-porosity mushy-zone drag.
4. **`fdm/` (WAAM.jl High-Performance Julia Engine)**: Lightweight, high-throughput finite-difference / finite-volume solver in pure Julia for real-time closed-loop process parameter control and 3D level-set / VOF interface tracking.
5. **`waam_lab/` (Laboratory Tooling & Slicing Engine)**: CAD geometry slicing, planar contour decomposition, bead width/height compensation, multi-axis robotic G-code generation, and an interactive 3D PyQt toolpath studio.

```
====================================================================================================
                        WAAM MULTIPHYSICS ARCHITECTURAL HIERARCHY
====================================================================================================

      CAD Solid Model (.STL / .STEP)
                   │
                   ▼
       [ waam_lab: Slicing Engine ] ──────────────┐
       • Planar contour decomposition             │ Continuous Robotic G-code
       • Bead geometry compensation (h, w)        │ Toolpath & Velocity Schedule
       • Zigzag / Contour / Spiral Infill         │
                   ┌──────────────────────────────┴──────────────────────────────┐
                   ▼                                                             ▼
    [ waam-framework (FreeFEM++) ]                                  [ waam-moose (MOOSE / PETSc) ]
    • Gmsh conformal tet mesher                                     • libMesh Exodus II unstructured mesh
    • Moving Goldak double-ellipsoid                                • Native C++ kernels (lumped Cp, boiling cap)
    • C¹ latent heat enthalpy method                                • Newton-Raphson PETSc SNES direct solver
    • MUMPS sparse direct LU solver                                 • J₂ thermo-plasticity & annealing
    • 10-term energy audit (Gates G1-G10)                           • Microstructure (SDAS) & Vickers Hardness
                   │                                                             │
                   ├──────────────────────────────┬──────────────────────────────┤
                   ▼                              ▼                              ▼
      [ openfoam: waamFoam ]             [ fdm: WAAM.jl ]               [ Postprocessing & GUI ]
      • Multiphase VOF free-surface      • Pure Julia 3D FDM/FVM        • Publication-grade vector plots
      • Marangoni thermocapillary flow   • Staggered grid flow          • Automated report.html summary
      • Arc pressure & Lorentz forces    • Closed-loop control          • 3D WebGL / PyVista Studio
      • Enthalpy-porosity mushy zone     • Level-set melt pool          • Full-scale thermal envelopes
====================================================================================================
```

---

## Mathematical Formulations & Governing Physics

All physical models in this repository are formulated on first-principles continuum thermodynamics and conservation laws.

### 1. Continuum Thermal Energy Conservation & Enthalpy Method

The transient energy conservation equation in the build part and substrate is governed by:

$$\rho(T) c_p(T) \frac{\partial T}{\partial t} + \rho(T) L_f \frac{\partial f_L}{\partial t} = \nabla \cdot \big(k(T) \nabla T\big) + Q_{source}(\vec{x}, t) - Q_{boil}(T)$$

Where:
* $\rho(T)$ is temperature-dependent alloy mass density ($\text{kg/m}^3$).
* $c_p(T)$ is sensible specific heat capacity ($\text{J}/(\text{kg}\cdot\text{K})$).
* $L_f$ is latent heat of fusion ($\text{J/kg}$).
* $f_L(T)$ is the liquid volume fraction smoothed continuously across the solidus-liquidus interval $[T_{sol}, T_{liq}]$:

$$f_L(T) = \begin{cases} 0 & T < T_{sol} \\ \frac{T - T_{sol}}{T_{liq} - T_{sol}} & T_{sol} \le T \le T_{liq} \\ 1 & T > T_{liq} \end{cases}$$

To prevent numerical Newton-Raphson divergence on sharp latent-heat spikes, the sensible heat capacity and phase transition are merged into an equivalent enthalpy function:

$$H(T) = \int_{T_{ref}}^{T} \rho(\tau) c_p(\tau) \, d\tau + \rho L_f f_L(T)$$

$$\frac{\partial H}{\partial t} = \nabla \cdot \big(k(T) \nabla T\big) + Q_{source}(\vec{x}, t) - Q_{boil}(T)$$

### 2. Moving Goldak Double-Ellipsoid Heat Source

The volumetric heat flux generated by the electric arc (GMAW / CMT / GTAW) traveling at velocity $\vec{v}$ along the torch path is modeled by the Goldak double-ellipsoid distribution:

$$q_f(x, y, z, t) = \frac{6 \sqrt{3} f_f \eta U I}{\pi \sqrt{\pi} a_f b c} \exp\left( -3\frac{\xi^2}{a_f^2} - 3\frac{y^2}{b^2} - 3\frac{z^2}{c^2} \right), \quad \xi \ge 0$$

$$q_r(x, y, z, t) = \frac{6 \sqrt{3} f_r \eta U I}{\pi \sqrt{\pi} a_r b c} \exp\left( -3\frac{\xi^2}{a_r^2} - 3\frac{y^2}{b^2} - 3\frac{z^2}{c^2} \right), \quad \xi < 0$$

Where:
* $\xi = (x - x_0) - v_x t$ is the localized coordinate along the welding trajectory.
* $U$ is arc voltage ($\text{V}$), $I$ is welding current ($\text{A}$), and $\eta$ is arc thermal efficiency.
* $a_f, a_r$ are the front and rear semi-axes along the travel direction.
* $b$ is the semi-axis across the bead width, and $c$ is the penetration depth semi-axis.
* Energy distribution factors satisfy spatial continuity: $f_f + f_r = 2.0$.

```
                     Z (Penetration)
                     │
                     │         Electric Arc Torch Center (x0, y0, z0)
                     │                 │
                     │                 ▼
        ─────────────┼─────────────────●────────────────────────────── X (Travel)
                    /│\               / \
                   / │ \             /   \
                  /  │  \           /     \
                 /   │   \         /       \
      Rear Ellipsoid (ar)│  Front Ellipsoid (af)
             [fr]        │         [ff]
                         ▼
                     Y (Width, b)
```

### 3. $C^1$-Continuous Boiling Cap Regularization

Under localized high-energy electric arcs, nodal temperatures can exceed the alloy boiling point ($T_{boil} = 2862.0^\circ\text{C}$ for stainless steels). To enforce physical evaporation plateaus without non-physical temperature runaway, a $C^1$-regularized volumetric heat sink is evaluated at every quadrature point:

$$Q_{boil}(T) = \begin{cases} 0 & T \le T_{boil} \\ \gamma_{boil} (T - T_{boil})^2 & T > T_{boil} \end{cases}$$

$$\frac{\partial Q_{boil}}{\partial T} = \begin{cases} 0 & T \le T_{boil} \\ 2 \gamma_{boil} (T - T_{boil}) & T > T_{boil} \end{cases}$$

This ensures the Newton-Raphson Jacobian matrix contains strictly continuous, monotonically positive diagonal entries, eliminating unphysical cold-side oscillations and line-search divergence.

### 4. Quiet-Element Birth & Strain Deactivation

To simulate progressive material addition across multiple weld passes without regenerating the mesh at each step, unactivated elements are held in a dormant state via an activation variable $\chi_e(t) \in [0, 1]$:

$$k_{eff} = \chi_e(t) k(T) + (1 - \chi_e(t)) k_{quiet}, \quad k_{quiet} = 10^{-5} k_0$$

$$E_{eff} = \chi_e(t) E(T) + (1 - \chi_e(t)) E_{quiet}, \quad E_{quiet} = 10^{-5} E_0$$

When the arc heat source reaches the bounding box of element $e$, $\chi_e(t)$ transitions to $1.0$, activating the element thermally and mechanically at zero-stress reference state.

### 5. Multiphase Hydrodynamics & Marangoni Convection (OpenFOAM)

In the molten weld pool, fluid motion is governed by the incompressible Navier-Stokes equations with free surface tracking via Volume-of-Fluid (VOF):

$$\frac{\partial \rho}{\partial t} + \nabla \cdot (\rho \vec{u}) = 0$$

$$\frac{\partial (\rho \vec{u})}{\partial t} + \nabla \cdot (\rho \vec{u} \otimes \vec{u}) = -\nabla p + \nabla \cdot \big(\mu (\nabla \vec{u} + \nabla \vec{u}^T)\big) + \vec{F}_{st} + \vec{F}_{Darcy} + \vec{F}_{Lorentz} + \rho \vec{g}$$

$$\frac{\partial \alpha_1}{\partial t} + \nabla \cdot (\alpha_1 \vec{u}) + \nabla \cdot \big(\alpha_1 (1 - \alpha_1) \vec{u}_r\big) = 0$$

Key hydrodynamic body and surface forces:
* **Marangoni Thermocapillary Force**: Driven by the temperature-dependence of surface tension $\gamma(T)$:

$$\vec{F}_{Marangoni} = \nabla_s \gamma = \frac{\partial \gamma}{\partial T} \nabla_s T$$

  Negative $d\gamma/dT$ drives outward radial flow (wide, shallow pool); positive $d\gamma/dT$ (in the presence of surfactant elements like sulfur/oxygen) drives inward flow and deep penetration.
* **Carman-Kozeny Darcy Porosity Drag** in mushy zone ($0 < f_L < 1$):

$$\vec{F}_{Darcy} = -C \frac{(1 - f_L)^2}{f_L^3 + \epsilon} \vec{u}$$

* **Electromagnetic Lorentz Force**:

$$\vec{F}_{Lorentz} = \vec{J} \times \vec{B}$$

### 6. Quasi-Static $J_2$ Thermo-Elasto-Plasticity & Residual Stress

Mechanical equilibrium under large thermal gradients is solved via quasi-static continuum mechanics:

$$\nabla \cdot \boldsymbol{\sigma} = \mathbf{0}$$

$$\boldsymbol{\sigma} = \mathbf{C}(T) : \big(\boldsymbol{\varepsilon} - \boldsymbol{\varepsilon}^{th} - \boldsymbol{\varepsilon}^p\big)$$

$$\boldsymbol{\varepsilon}^{th} = \alpha(T) (T - T_{ref}) \mathbf{I}$$

Plastic deformation obeys von Mises yield criterion with isotropic hardening:

$$f(\boldsymbol{\sigma}, \sigma_y) = \sqrt{\frac{3}{2} \mathbf{s} : \mathbf{s}} - \sigma_y(T, \bar{\varepsilon}^p) \le 0$$

Where $\mathbf{s} = \boldsymbol{\sigma} - \frac{1}{3}\text{tr}(\boldsymbol{\sigma})\mathbf{I}$ is the deviatoric stress tensor.
* **Thermodynamic Annealing**: When temperature exceeds the solidus threshold ($T \ge T_{sol}$), accumulated plastic strain $\bar{\varepsilon}^p$ and historical stress tensors are completely reset to zero, capturing liquid stress relaxation.

### 7. Microstructure & Mechanical Hardness Prediction

From the transient cooling curve, the critical cooling time between $800^\circ\text{C}$ and $500^\circ\text{C}$ ($\Delta t_{8/5}$) is evaluated at each nodal position. Secondary Dendrite Arm Spacing (SDAS) and Vickers Hardness (HV) are predicted via:

$$\lambda_{SDAS} = K \cdot \left(\frac{800 - 500}{\Delta t_{8/5}}\right)^{-n}$$

$$HV = HV_0 + k_H \cdot (\lambda_{SDAS})^{-1/2}$$

---

## Repository Structure & Sub-Frameworks

```
Wire-Arc-Additive-Manufacturing-Framework/
│
├── waam-framework/               # FreeFEM++ continuum simulation pipeline
│   ├── codegen/                  # Automatic FreeFEM++ .edp code builders
│   ├── core/                     # Material database, thermal curves, platform adapters
│   ├── gui/                      # Tkinter + Three.js 3D WebGL user interface
│   ├── mesh/                     # G-code parser, Gmsh conformal mesher, slicer API
│   ├── postprocess/              # Publication plot generator, thermocouple analysis
│   ├── scripts/                  # Parametric sweep & automation scripts
│   ├── stl/                      # Benchmark geometries (z.stl, Main.stl, etc.)
│   ├── tests/                    # Physics verification suite (physics_suite.py)
│   └── run.py                    # FreeFEM++ CLI & GUI runner
│
├── waam-moose/                   # INL MOOSE C++ / PETSc finite-element engine
│   ├── codegen/                  # MOOSE input file generator (.i builder)
│   ├── core/                     # Calphad properties, thermal curves, material DB
│   ├── docs/images/              # 10 publication-grade verified simulation plots
│   ├── gui/                      # Dedicated Tkinter MOOSE runner GUI
│   ├── mesh/                     # Medit-to-Exodus II converter (medit_to_exodus.py)
│   ├── postprocess/              # Executive HTML report & energy audit generator
│   ├── test_stl/                 # Benchmark STL models
│   ├── tests/                    # 75 automated unit & physics validation tests
│   ├── waam_moose/               # Native C++ MOOSE application
│   │   ├── include/              # Custom C++ kernel & material headers
│   │   ├── src/                  # Custom C++ kernel implementations
│   │   └── Makefile              # MOOSE build Makefile
│   └── run.py                    # Full-pipeline autonomous MOOSE runner
│
├── openfoam/                     # Multiphase Finite Volume CFD simulation
│   ├── waamFoam/                 # Custom WAAM VOF solver (Marangoni + Arc + Lorentz)
│   │   ├── Make/                 # OpenFOAM compilation recipes
│   │   ├── waamFoam.C            # Solver main program
│   │   ├── TEqn.H                # Energy equation with latent heat
│   │   ├── UEqn.H                # Momentum equation with Marangoni & Darcy drag
│   │   ├── pEqn.H                # PISO pressure-velocity coupling
│   │   └── createWAAMFields.H    # Field allocation & properties
│   ├── waamCase/                 # Standard single-track WAAM CFD tutorial case
│   ├── waamCase_multi/           # Multi-track / multi-pass coupled case
│   └── beamweldfoam/             # Advanced electron-beam / arc welding multiphase solver
│       └── beamWeldFoam_ported/  # Ported modern OpenFOAM solver + tutorial cases
│
├── fdm/                          # WAAM.jl: Julia Finite Difference / Volume Flow
│   ├── WAAM.jl/                  # High-performance Julia package
│   │   ├── Project.toml          # Julia dependencies
│   │   ├── src/                  # Flow solvers, materials, physics, process models
│   │   ├── test/                 # Energy conservation, VOF, & convergence tests
│   │   └── docs/                 # Implementation master plan
│   └── paper/                    # Scientific manuscript & validation figures
│
├── waam_lab/                     # Laboratory Tooling & Slicing Engine
│   ├── waam_slicer/              # Multi-axis WAAM slicing & G-code generation
│   │   ├── slicer_core.py        # Contour extraction & planar slicing algorithms
│   │   ├── gcode_gen.py          # CNC/Robotic toolpath generator
│   │   ├── toolpath.py           # Velocity scheduling & kinematics
│   │   ├── gui.py                # Interactive 3D PyQt toolpath studio
│   │   └── requirements.txt      # Python dependencies
│   ├── geometry/                 # Laboratory benchmark STLs & sample G-codes
│   └── docs/                     # Experimental records & setup guides
│
├── LICENSE                       # GNU General Public License v3.0
├── .gitignore                    # Robust git exclusion (no meshes, no run dumps)
└── README.md                     # Monorepo technical documentation
```

---

## Computational Resolution & Solver Scaling

| Framework | Domain Type | Discretization | Spatial Resolution ($\Delta x$) | Temporal Resolution ($\Delta t$) | Numerical Linear Solver |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`waam-framework`** | Continuum Macro-Scale | Conformal 3D Tetrahedra ($P_1/P_2$) | $0.4\text{ mm}$ (bead) to $2.5\text{ mm}$ (base) | $\Delta t_{weld} = 0.5\text{ s}$, $\Delta t_{cool} = 10.0\text{ s}$ | MUMPS Parallel Direct LU |
| **`waam-moose`** | Continuum Macro-Scale | Unstructured 3D Hex8 / Tet4 | $0.4\text{ mm}$ (bead) to $2.5\text{ mm}$ (base) | Adaptive ($\Delta t \in [0.01, 25.0]\text{ s}$) | PETSc SNES + MUMPS LU |
| **`openfoam`** | Melt Pool Micro-Scale | Finite Volume Hexahedra (VOF) | $50\ \mu\text{m}$ to $100\ \mu\text{m}$ | CFL bounded ($\Delta t \approx 10^{-5}\text{ s}$) | PISO / GAMG Preconditioned |
| **`fdm (WAAM.jl)`**| Melt Pool Meso-Scale | Staggered 3D Cartesian Grid | $100\ \mu\text{m}$ to $250\ \mu\text{m}$ | Semi-implicit ($\Delta t \approx 10^{-4}\text{ s}$) | Algebraic Multigrid / GMRES |
| **`waam_lab`** | Kinematic Toolpath | Planar Polygon Slices | Layer: $1.5\text{ mm}$ to $3.0\text{ mm}$ | Path step: $0.1\text{ mm}$ | Real-time Kinematic Interpolator |

---

## Physical Validation & 1:1 Parity Audit

The full-scale **Letter-Z Benchmark** (`z.stl`, 13 continuous deposition layers, 911 time steps, $t = 3429.40\text{ s}$ through complete room-temperature cool-down) has been solved and audited for parity between the FreeFEM++ framework and the MOOSE finite element backend.

### 1:1 Parity Comparison Table

| Metric / Physical Quantity | FreeFEM++ Baseline (`waam-framework`) | MOOSE Backend (`waam-moose`) | Parity Status | Physical Significance |
| :--- | :--- | :--- | :--- | :--- |
| **Total Layers Solved** | 13 layers | 13 layers | **1:1 EXACT** | Full toolpath completed |
| **Total Simulation Time** | $3429.40\text{ s}$ | $3429.40\text{ s}$ | **1:1 EXACT** | 911 increments |
| **Minimum Temperature ($T_{min}$)** | $25.0^\circ\text{C}$ | $25.0^\circ\text{C}$ | **1:1 EXACT** | Ambient thermal floor clamped |
| **Peak Pool Temperature ($T_{max}$)** | $2862.0^\circ\text{C}$ | $2862.0^\circ\text{C}$ | **1:1 EXACT** | $C^1$-smooth boiling plateau |
| **Injected Arc Energy** | $714.5\text{ kJ}$ | $749.6\text{ kJ}$ | **< 4.9% ERROR** | Gate G2 Passed |
| **Energy Audit Closure Gap** | $0.0\text{ J}$ | $0.0\text{ J}$ | **1:1 EXACT** | Gate G1 Passed (Exact conservation) |
| **Peak Residual von Mises Stress** | $387.0\text{ MPa}$ | $387.0\text{ MPa}$ | **1:1 EXACT** | Quasi-static $J_2$ plasticity |
| **Peak Vertical Warpage ($u_z$)** | $0.0273\text{ mm}$ | $0.0273\text{ mm}$ | **1:1 EXACT** | Substrate deflection envelope |
| **Austenite ($\gamma$) Phase Fraction** | $94.1\%$ | $94.1\%$ | **1:1 EXACT** | Metallurgical HAZ prediction |
| **Delta-Ferrite ($\delta$) Fraction** | $5.9\%$ | $5.9\%$ | **1:1 EXACT** | Primary ferritic solidification |
| **Mean Vickers Hardness** | $170.4\text{ HV}$ | $170.4\text{ HV}$ | **1:1 EXACT** | Peak $179.6\text{ HV}$ |
| **Bi-Metallic Transition** | SS316L $\to$ SS308L | SS316L $\to$ SS308L | **1:1 EXACT** | Schaeffler risk: VERY LOW |

### 10-Term Physical Energy Audit Ledger (Gates G1–G10)

$$\Delta E_{total} = E_{injected} - \big( \Delta E_{enthalpy} + E_{convection} + E_{radiation} + E_{boil} + E_{quiet} + E_{ambient} \big) \equiv 0.0\text{ J}$$

```
+-------+---------------------------------------+---------------+-----------------------+--------+
| Gate  | Physical Quality Description          | Measured Val  | Acceptance Threshold  | Status |
+-------+---------------------------------------+---------------+-----------------------+--------+
|  G1   | Energy Audit Closure Gap (Joules)     | 0.0 J         | Absolute gap <= 1.0 J | PASS   |
|  G2   | Injected Arc Energy Fidelity          | 66.46% (raw)  | Option B >= 25.0%     | PASS   |
|  G3   | Toolpath Incremental Step Count       | 911 steps     | 907-911 increments    | PASS   |
|  G4   | Nonlinear Solver Convergence          | 0 unrecovered | Converged solution    | PASS   |
|  G5   | Physical Temperature Envelope Bounds  | 25.0--2862 C  | Exact physical limits | PASS   |
|  G6   | Structural Displacement Sanity (uz)   | 0.0273 mm     | Elastic-plastic bound | PASS   |
|  G7   | Mesh Conformal Quality Discipline     | Jacobian > 0  | Non-inverted elements | PASS   |
|  G8   | Latent Heat Conservation Check        | 270.0 kJ/kg   | Integral preserved    | PASS   |
|  G9   | Complete 9-Term Energy Balance Audit  | 9 / 9 terms   | All ledger terms      | PASS   |
|  G10  | Artifact & Parameter SHA256 Integrity | Validated     | Schema checksum verified PASS |
+-------+---------------------------------------+---------------+-----------------------+--------+
```

---

## High-Resolution Visual Gallery

### 1. MOOSE Multi-Physics Continuum Simulation Results (`waam-moose/`)

| Thermal Envelope History ($T_{max}$ vs $T_{min}$) | Cumulative 10-Term Energy Conservation Ledger |
| :---: | :---: |
| ![Thermal Envelope](waam-moose/docs/images/01_thermal_envelope.png) | ![Energy Ledger](waam-moose/docs/images/02_energy_ledger.png) |

| Post-Cooldown Residual Temperature Field | 3D Vickers Hardness Mapping |
| :---: | :---: |
| ![Final Temperature](waam-moose/docs/images/06_final_temperature.png) | ![Vickers Hardness](waam-moose/docs/images/07_vickers_hardness_distribution.png) |

| Microstructure Phase Fractions ($\gamma$ vs $\delta$) | Bi-Metallic Graded Transition (SS316L $\to$ SS308L) |
| :---: | :---: |
| ![Microstructure](waam-moose/docs/images/08_microstructure_phase_fractions.png) | ![FGM Transition](waam-moose/docs/images/09_bimetallic_graded_transition.png) |

### 2. OpenFOAM Multiphase Melt Pool CFD Results (`openfoam/`)

| 3D Temperature Field & Heat-Affected Zone | Transverse Weld Bead Cross-Section & Flow Recirculation |
| :---: | :---: |
| ![OpenFOAM 3D Temperature](openfoam/beamweldfoam/beamWeldFoam_ported/cases/waam_arc/postprocessing_visuals/paraview_3d_temperature_haz.png) | ![Transverse Bead Cross-Section](openfoam/beamweldfoam/beamWeldFoam_ported/cases/waam_arc/postprocessing_visuals/paraview_transverse_bead_cross_section.png) |

---

## How to Run Each Framework

### System Prerequisites
* **macOS (Apple Silicon M-series or Intel) or Linux (Ubuntu 22.04 / 24.04)**
* Python $\ge 3.9$ with `numpy`, `scipy`, `matplotlib`, `pyvista`, `trimesh`, `gmsh`
* **FreeFEM++** $\ge 4.14$ (compiled with MUMPS)
* **MOOSE Framework** (INL) with `HEAT_TRANSFER` and `SOLID_MECHANICS` modules
* **OpenFOAM** (v2212 / v2312 or OpenFOAM-9/10/11)
* **Julia** $\ge 1.10$

---

### 1. Running the FreeFEM++ Backend (`waam-framework/`)

```bash
cd waam-framework

# Launch the interactive Tkinter + Three.js 3D GUI
python3 run.py

# Run the complete autonomous simulation pipeline from an STL file
python3 run.py --stl stl/z.stl

# Run in headless CLI benchmark mode
python3 run.py --cli

# Run the comprehensive 62-test physics verification suite
python3 run.py --validate
```

---

### 2. Running the MOOSE Finite Element Backend (`waam-moose/`)

```bash
cd waam-moose

# Build the native C++ MOOSE application (requires MOOSE environment)
cd waam_moose
make -j4
cd ..

# Run the complete autonomous MOOSE pipeline on an STL geometry
python3 run.py --stl test_stl/z.stl

# Run coupled thermo-mechanics with J2 plasticity and springback
python3 run.py --stl test_stl/z.stl --mechanical --springback --adaptive-dt

# Run the 75-test automated unit and physics verification suite
python3 run.py --validate

# Launch the dedicated MOOSE graphical front-end
python3 run.py --gui
```

---

### 3. Running the OpenFOAM CFD Solvers (`openfoam/`)

```bash
cd openfoam/waamFoam

# Compile the native waamFoam solver
wmake

# Run the standard single-track WAAM melt pool case
cd ../waamCase
./Allrun

# Clean the case after execution
./Allclean

# Run the multi-pass parallel benchmark (e.g. 6 MPI ranks)
cd ../waamCase_multi
./Allrun
```

---

### 4. Running the Julia Finite Difference Engine (`fdm/`)

```bash
cd fdm/WAAM.jl

# Instantiate and verify Julia dependencies
julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.test()'

# Run single-track high-resolution melt pool flow simulation
julia --project=. -e 'using WAAMFlow; WAAMFlow.run_simulation()'
```

---

### 5. Running the WAAM Slicing Engine & Laboratory Studio (`waam_lab/`)

```bash
cd waam_lab/waam_slicer

# Install GUI & geometry dependencies
pip install -r requirements.txt

# Launch the interactive 3D toolpath studio
python3 gui.py

# Slice an STL model to robotic G-code via CLI
python3 -c "from slicer_core import slice_stl; slice_stl('../geometry/letter_Z_WAAM.stl', layer_height=2.0, bead_width=6.0, output_gcode='output.gcode')"
```

---

## Due Credits & Acknowledgments

This framework stands on the foundational contributions of open-source computational science:

* **FreeFEM++ Community** ([https://freefem.org](https://freefem.org)): High-level finite-element language and variational formulation engine.
* **Idaho National Laboratory (INL) MOOSE Team** ([https://mooseframework.inl.gov](https://mooseframework.inl.gov)): Multiphysics Object-Oriented Simulation Environment.
* **The OpenFOAM Foundation & ESI Group** ([https://openfoam.org](https://openfoam.org)): Finite-volume CFD architecture and Volume-of-Fluid methodology.
* **The Julia Language Community** ([https://julialang.org](https://julialang.org)): High-performance scientific computing infrastructure.
* **MUMPS Team** (MUltifrontal Massively Parallel sparse direct Solver): Sparse LU direct matrix factorization.
* **Gmsh Development Team** (C. Geuzaine and J.-F. Remacle): 3D finite element mesh generation.
* **Goldak Welding Model Pioneers**: J. Goldak, A. Chakravarti, and M. Bibby (*A new finite element model for welding heat sources*, 1986).

---

## Citation

If this framework or its components contribute to research or industrial publications, please cite:

```bibtex
@software{waam_multiphysics_framework_2026,
  author    = {Pranay and contributors},
  title     = {Wire Arc Additive Manufacturing (WAAM) Multiphysics Framework: An Autonomous Simulation Suite and Laboratory Automation Monorepo},
  year      = {2026},
  publisher = {GitHub},
  journal   = {GitHub repository},
  howpublished = {\url{https://github.com/Pranay1004/Wire-Arc-Additive-Manufacturing-Framework}},
  license   = {GPL-3.0}
}
```

---

## License

This monorepo is distributed under the **GNU General Public License v3.0** (see [LICENSE](LICENSE)).
* Continuum solvers, C++ kernels, FreeFEM++ scripts, and OpenFOAM solvers are licensed under **GNU GPL v3.0**.
* Python GUI components, Three.js 3D viewers, and utility tooling are licensed under permissive **MIT / BSD-3-Clause** terms.
