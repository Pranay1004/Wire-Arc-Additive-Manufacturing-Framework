# Ultrasonic-Assisted (UVA) WAAM Melt Pool Case: `uva_pranay`

Created by Pranay K. Pandey  
Location: `beamweldfoam/beamWeldFoam_ported/cases/uva_pranay/`  
Solver: `beamWeldFoam` (OpenFOAM 2412 Port)

---

## 1. Physical Description

This case models full 3D two-phase (mild steel liquid/solid + shielding gas) fluid dynamics during **Ultrasonic Vibration Assisted Wire Arc Additive Manufacturing (UVA-WAAM)**.

### Coupled Phenomena:
1. **Diverging-Oscillating Gaussian WAAM Arc Heat Source**:
   - Total Net Power: `P_net = 850 W` (surface-calibrated from 3840 W gross arc)
   - Arc Radius: `HS_a = 3.5 mm`
   - Travel Speed: `v_scan = 10 mm/s` along `+Z`
2. **Eckart Acoustic Streaming (`fvOptions`)**:
   - Ultrasonic Horn frequency: `f_us = 20 kHz`
   - Transducer vibration amplitude: `A_us = 10 μm`
   - Acoustic intensity: `I_ac = 2.238e+07 W/m²`
   - Specific radiation body force: `a_ac = 23.68 m/s²` directed upward (`-Y` into the pool)
   - Result: Dominates natural buoyancy by `~330x`, generating vigorous convective stirring.
3. **Marangoni Convection**:
   - Surface tension: `sigma = 0.8 N/m`
   - Marangoni temperature gradient coefficient: `dsigma/dT = -0.43e-4 N/(m.K)`
4. **Mushy-Zone Darcy Permeability Damping**:
   - Damping coefficient: `DC = large * (1-eps)^2 / (eps^3 + small)`
5. **Thermodynamic Evaporation & Recoil Pressure**:
   - Clamped Clausius-Clapeyron recoil pressure preventing unphysical runaway overheating.

---

## 2. Directory Structure

```
cases/uva_pranay/
├── constant/
│   ├── acousticProperties      # 20 kHz frequency, 10 um amplitude, sound speed, attenuation
│   ├── transportProperties     # ER70S-6 steel & gas, surface tension, Marangoni dsigma/dT
│   ├── dynamicMeshDict         # Static mesh specification
│   ├── g                       # Gravity vector (0 -9.81 0)
│   └── turbulenceProperties    # Laminar flow regime
├── system/
│   ├── blockMeshDict           # Refined 3D mesh (30mm x 13mm x 50mm, 34,944 cells)
│   ├── controlDict             # OpenFOAM 2412 runtime parameters (maxCo = 0.2)
│   ├── fvSchemes               # TVD vanLeer and linearUpwind schemes
│   ├── fvSolution              # PIMPLE linear solvers and MELTING heat source dict
│   ├── fvOptions               # vectorSemiImplicitSource acoustic streaming body force
│   ├── decomposeParDict        # 4-subdomain Scotch parallel decomposition
│   └── setFieldsDict           # Substrate initialization (alpha.phase1 = 1)
├── initial/                    # Clean initial conditions (U, Temperature, p_rgh, alpha.phase1)
├── Allrun                      # Serial execution script
├── Allrun.parallel             # 4-core MPI parallel execution script
├── Allclean                    # Directory cleanup script
├── postprocess_cfd_uva.py      # Force scaling and melt pool diagnostic script
├── open_in_paraview.py         # 1-click ParaView visualization launcher
├── uva_pranay.foam             # ParaView case proxy
└── README.md                   # This documentation
```

---

## 3. How to Run

### Serial Execution
```bash
cd /Users/pandeyji/Desktop/WAAM/beamweldfoam/beamWeldFoam_ported/cases/uva_pranay
./Allrun
```

### 4-Core Parallel Execution
```bash
cd /Users/pandeyji/Desktop/WAAM/beamweldfoam/beamWeldFoam_ported/cases/uva_pranay
./Allrun.parallel
```

### Post-Processing & ParaView Visualization
```bash
python3 postprocess_cfd_uva.py
python3 open_in_paraview.py
```
