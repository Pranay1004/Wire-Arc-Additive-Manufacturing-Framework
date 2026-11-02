# beamWeldFoam - OpenFOAM 2412 Port

A transient solver for incompressible, laminar two-phase flow with phase change (melting/solidification), Marangoni convection, vapor recoil pressure, and a Goldak-style volumetric heat source for arc/laser/electron beam welding simulation.

## Original Repository

**beamWeldFoam** by:
- Thomas F. Flint, University of Manchester
- Gowthaman Parivendhan, University College Dublin
- Alojz Ivankovic, University College Dublin
- Michael C. Smith, University of Manchester
- Philip Cardiff, University College Dublin

GitHub: https://github.com/ElsevierSoftwareX/SOFTX-D-21-00212
Original version: OpenFOAM 6
License: GNU GPL v3

## Ported Version

**Ported to OpenFOAM 2412** by:
- Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
- GitHub: https://github.com/Pranay1004

Date: September 2026
Tested on: Apple M4 Air, 16GB RAM

## Physical Models

- **Goldak heat source**: Diverging oscillating Gaussian for arc/laser/electron beam
- **VOF interface tracking**: Volume of Fluid with MULES for boundedness
- **Marangoni convection**: Surface tension gradient drives flow along interface
- **Vapor recoil pressure**: Evaporation-driven surface deformation
- **Darcy damping**: Carman-Kozeny permeability model in mushy zone
- **Latent heat**: Energy absorption/release during phase change
- **Viscous dissipation**: Kinetic energy to heat conversion

## Key OF6 → OF2412 Changes

### 1. PIMPLE Control

**OF6:**
```cpp
#include "pimpleControl.H"
pimpleControl pimple(runTime);
```

**OF2412:**
```cpp
#define PIMPLE_CONTROL
#include "createControl.H"
// pimple is created by createPimpleControl.H
```

### 2. Dynamic Mesh Creation

**OF6:**
```cpp
#include "createDynamicFvMesh.H"
// Internally: dynamicFvMesh::New(runTime)
```

**OF2412:**
```cpp
#include "createDynamicFvMesh.H"
// Internally: dynamicFvMesh::New(args, runTime)
// args is now required in the constructor
```

### 3. Turbulence Model

**OF6:**
```cpp
#include "turbulentTransportModel.H"
autoPtr<incompressible::turbulenceModel> turbulence
(
    incompressible::turbulenceModel::New(U, phi, laminarTransport)
);
```

**OF2412:**
```cpp
#include "incompressibleInterPhaseTransportModel.H"
typedef incompressibleInterPhaseTransportModel
    <
        immiscibleIncompressibleTwoPhaseMixture
    > transportModelType;
autoPtr<transportModelType> turbulence
(
    new transportModelType(rho, U, phi, rhoPhi, mixture)
);
```

### 4. Gravitational Acceleration

**OF6:**
```cpp
#include "uniformDimensionedFields.H"
uniformDimensionedVectorField g
(
    IOobject("g", runTime.timeName(), mesh, IOobject::MUST_READ, IOobject::NO_WRITE)
);
```

**OF2412:**
```cpp
#include "readGravitationalAcceleration.H"
// Uses meshObjects::gravity::New(runTime)
// g is now a meshObject, not a uniformDimensionedVectorField
```

### 5. Reference Height (hRef)

**OF6:**
```cpp
uniformDimensionedScalarField hRef
(
    IOobject("hRef", runTime.timeName(), mesh, IOobject::READ_IF_PRESENT, IOobject::NO_WRITE)
);
```

**OF2412:**
```cpp
#include "readhRef.H"
// Reads from IOdictionary on mesh.thisDb()
// In OF6, this read from runTime; in OF2412, from mesh database
```

### 6. Density Old Time

**OF6:**
```cpp
volScalarField rho(alpha1*rho1 + alpha2*rho2);
```

**OF2412:**
```cpp
volScalarField rho(alpha1*rho1 + alpha2*rho2);
rho.oldTime();  // Required for ddt(rho,U) in OF2412
```

### 7. IOdictionary Lookup

**OF6:**
```cpp
IOdictionary dict(IOobject(...), mesh);
// lookup() returns const T&
```

**OF2412:**
```cpp
IOdictionary dict(IOobject(...), mesh);
// getOrDefault() is preferred for optional entries
// lookup() still works but may be stricter
```

### 8. dimensionSet

**OF6:**
```cpp
dimensionedScalar("name", dimSet(0,1,-1,0,0), value);
```

**OF2412:**
```cpp
dimensionedScalar("name", dimensionSet(0,1,-1,0,0), value);
// dimSet() was a shorthand, now uses full dimensionSet()
```

### 9. Include Paths

**OF6 Make/options:**
```
EXE_INC = \
    -I$(LIB_SRC)/TurbulenceModels/incompressible/turbulentTransportModel \
    -I$(LIB_SRC)/transportModels/incompressible/singlePhaseTransportModel
```

**OF2412 Make/options:**
```
EXE_INC = \
    -I$(LIB_SRC)/TurbulenceModels/phaseIncompressible/VOFphase \
    -I$(LIB_SRC)/transportModels/incompressible/singlePhaseTransportModel \
    -I$(LIB_SRC)/phaseSystemModels/twoPhaseInter/incompressibleInterPhaseTransportModel \
    -I$(LIB_SRC)/transportModels/incompressible/VoFphaseIncompressibleTurbulenceModels
```

### 10. Library Links

**OF6 Make/options:**
```
LIBS = \
    -lfiniteVolume \
    -ldynamicFvMesh
```

**OF2412 Make/options:**
```
LIBS = \
    -lfiniteVolume \
    -ldynamicFvMesh \
    -lVoFphaseTurbulentTransportModels \
    -lincompressibleInterPhaseTransportModels \
    -lwaveModels
```

### 11. validate() Removed

**OF6:**
```cpp
turbulence->validate();
```

**OF2412:**
```cpp
// validate() is removed in OF2412
// The turbulence model is validated during construction
```

### 12. macOS Case-Insensitive Filesystem

The original solver included `CorrectPhi.H` which shadows the library header on macOS:
```cpp
// Original: #include "CorrectPhi.H"
// Problem: macOS filesystem is case-insensitive, so this shadows
//          finiteVolume/cfdTools/general/CorrectPhi/CorrectPhi.H
// Solution: Renamed to correctPhiLocal.H
```

## Tutorial Compatibility

All tutorials from the original repository have been tested and verified:

| Tutorial | Status | Cells | Notes |
|----------|--------|-------|-------|
| ArcCase | ✅ PASS | 72,000 | 2D arc welding, aluminium |
| Test | ✅ PASS | 3,600 | Single particle melting |
| SingleParticleMelting2D | ✅ PASS | 3,600 | Single particle on substrate |
| PowderBed2D | ✅ PASS | 115,200 | 150+ powder particles |
| PowderBed3D | ✅ PASS | 216,000 | 3D powder bed, titanium |
| EB_3D | ✅ PASS | 216,000 | 3D electron beam, titanium |
| SenDavies | ✅ PASS | 115,200 | Natural convection benchmark |
| Tancase | ✅ PASS | 7,500 | Tin melting benchmark |
| GalluimCase | ✅ PASS | 14,000 | Gallium melting (2D) |
| GalluimCase3D | ⚠️ SKIP | 6,720,000 | Too large for 16GB RAM |

## Installation

### Prerequisites

- OpenFOAM 2412 (installed via Homebrew Cask on macOS)
- Git

### Build

```bash
cd beamWeldFoam_ported
source /opt/homebrew/bin/openfoam2412
cd solver/beamWeldFoam
wmake
```

### Run a Tutorial

```bash
source /opt/homebrew/bin/openfoam2412
cd cases/ArcCase
cp -r initial 0
blockMesh -dict system/blockMeshDict
setFields
beamWeldFoam
```

## File Structure

```
beamWeldFoam_ported/
├── README.md                       # This file
├── PORTING_NOTES.md                # Detailed porting changes
├── build.sh                        # Build script
├── test_all_tutorials.sh           # Test all tutorials
├── solver/beamWeldFoam/
│   ├── beamWeldFoam.C              # Main solver file
│   ├── createFields.H              # Field initialization
│   ├── UEqn.H                      # Momentum equation
│   ├── TEqn.H                      # Energy equation
│   ├── pEqn.H                      # Pressure equation
│   ├── readControls.H              # Solver controls
│   ├── UpdateProps.H               # Material property updates
│   ├── DivergingOscillatingGaussian.H  # Goldak heat source
│   ├── uniqueX.H                   # Ray-tracing coordinates
│   ├── correctPhiLocal.H           # Phi correction (renamed)
│   ├── initCorrectPhi.H            # Phi initialization
│   ├── setRDeltaT.H                # LTS time step (stub)
│   ├── Make/
│   │   ├── files                   # Build configuration
│   │   └── options                  # Include paths and libraries
│   └── VoF/
│       ├── alphaEqn.H              # VOF alpha equation
│       ├── alphaEqnSubCycle.H      # Sub-cycling for VOF
│       ├── alphaCourantNo.H        # Alpha Courant number
│       ├── setDeltaT.H             # Adaptive time step
│       ├── createAlphaFluxes.H     # Alpha flux initialization
│       ├── alphaSuSp.H             # Alpha source terms
│       └── rhofs.H                 # Phase density references
├── tutorials/
│   ├── ArcCase/                    # 2D arc welding
│   ├── Test/                       # Single particle test
│   ├── SingleParticleMelting2D/    # Single particle on substrate
│   ├── PowderBed2D/                # 2D powder bed
│   ├── PowderBed3D/                # 3D powder bed
│   ├── EB_3D/                      # 3D electron beam
│   ├── SenDavies/                  # Natural convection
│   ├── Tancase/                    # Tin melting
│   ├── GalluimCase/                # Gallium melting (2D)
│   └── GalluimCase3D/              # Gallium melting (3D)
└── cases/
    └── waam_arc/                   # WAAM-specific test case
```

## Material Properties

### Required Format (constant/transportProperties)

```cpp
phases (phase1 phase2);

phase1
{
    transportModel  Newtonian;
    nu              [m^2/s]   ;   // Kinematic viscosity
    rho             [kg/m^3]  ;   // Density
    cp              [J/(kg K)];   // Liquid specific heat
    cpsolid         [J/(kg K)];   // Solid specific heat
    kappa           [W/(m K)] ;   // Liquid thermal conductivity
    kappasolid      [W/(m K)] ;   // Solid thermal conductivity
    Tsolidus        [K]       ;   // Solidus temperature
    Tliquidus       [K]       ;   // Liquidus temperature
    LatentHeat      [J/kg]    ;   // Latent heat of fusion
    beta            [1/K]     ;   // Thermal expansion coefficient
}

phase2
{
    // Same structure as phase1 (typically gas phase)
}

sigma             [N/m]      ;   // Surface tension coefficient
dsigmadT          [N/(m K)]  ;   // Temperature derivative of surface tension
p0                [Pa]       ;   // Reference pressure
Tvap              [K]        ;   // Vaporization temperature
Mm                [kg/mol]   ;   // Molar mass
LatentHeatVap     [J/kg]     ;   // Latent heat of vaporization
```

### Material Data

| Material | rho [kg/m^3] | Tsolidus [K] | Tliquidus [K] | LatentHeat [J/kg] |
|----------|--------------|--------------|---------------|-------------------|
| Aluminium | 2710 | 927 | 945 | 396,666 |
| Titanium | 4500 | 1878 | 1933 | 360,000 |
| Gallium | 6093 | 302.4 | 303.2 | 80,160 |
| Tin | 9780 | 544.45 | 544.65 | 44,600 |

## Heat Source Parameters

| Parameter | Description | Typical Value |
|-----------|-------------|---------------|
| HS_a | Beam radius at focus [m] | 0.0002 - 0.0075 |
| HS_Q | Total beam power [W] | 250 - 780 |
| HS_velocity | Beam travel speed [m/s] | 0 - 0.4 |
| HS_deposition_cutoff | Alpha cutoff (0=keyhole, 0.99=conduction) | 0.01 - 0.99 |
| Oscillation_Amplitude | Beam oscillation amplitude [m] | 0 - 0.015 |
| Oscillation_Frequency | Beam oscillation frequency [Hz] | 0 - 200 |
| Y_R | Beam divergence ratio | 0.05 - 0.2 |
| focY | Y focus position [m] | -0.08 - 0.0165 |

## Limitations

- Incompressible formulation (rho = constant within each phase)
- No radiation model (would need separate coupling)
- Solid mechanics not included (use FreeFEM coupling for stress)
- Acoustic coupling not included (use FreeFEM coupling for vibration)
- GalluimCase3D requires >16GB RAM (6.7M cells)

## License

GNU General Public License v3.0

## Credits

**Original solver:**
- Tom Flint, University of Manchester
- Gowthaman Parivendhan, University College Dublin
- Alojz Ivankovic, University College Dublin
- Michael C. Smith, University of Manchester
- Philip Cardiff, University College Dublin

**Ported to OF2412:**
- Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
- GitHub: https://github.com/Pranay1004
