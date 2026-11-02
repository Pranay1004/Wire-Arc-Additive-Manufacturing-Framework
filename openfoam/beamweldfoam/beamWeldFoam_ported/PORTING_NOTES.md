# beamWeldFoam - OpenFOAM 6 to 2412 Porting Notes

## Overview

This document details all changes made to port beamWeldFoam from OpenFOAM 6 to OpenFOAM 2412. The solver was successfully compiled and tested on macOS (Apple M4 Air, 16GB RAM) with OpenFOAM 2412 installed via Homebrew Cask.

## Attribution

**Original authors:**
- Thomas F. Flint, University of Manchester
- Gowthaman Parivendhan, University College Dublin
- Alojz Ivankovic, University College Dublin
- Michael C. Smith, University of Manchester
- Philip Cardiff, University College Dublin

**OpenFOAM 2412 port by:**
- Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
- GitHub: https://github.com/Pranay1004

**License:** GNU GPL v3 (same as original)

## Summary of Changes

| Category | Files Changed | Key Changes |
|----------|---------------|-------------|
| Main solver | beamWeldFoam.C | PIMPLE control, includes, createFields |
| Field creation | createFields.H | Turbulence model, gravity, IOdictionary |
| Equations | UEqn.H, TEqn.H, pEqn.H | API compatibility (mostly unchanged) |
| VOF | VoF/*.H | alphaCourantNo, setDeltaT APIs |
| Heat source | DivergingOscillatingGaussian.H | dimensionSet |
| Helpers | correctPhiLocal.H, initCorrectPhi.H | Renamed, new APIs |
| Build | Make/files, Make/options | Include paths, library links |

## Detailed Changes

### 1. beamWeldFoam.C (Main Solver)

#### 1.1 PIMPLE Control

**OF6:**
```cpp
#include "pimpleControl.H"
// ...
pimpleControl pimple(runTime);
```

**OF2412:**
```cpp
#define PIMPLE_CONTROL
#include "createControl.H"
// pimple is created by createPimpleControl.H via createDyMControls.H
```

**Rationale:** In OF2412, the PIMPLE control is set up via preprocessor defines rather than direct instantiation. The `#define PIMPLE_CONTROL` before including `createControl.H` tells the build system to create the appropriate pimple control.

#### 1.2 Root Case Setup

**OF6:**
```cpp
#include "setRootCaseLists.H"
```

**OF2412:**
```cpp
#include "setRootCase.H"
```

**Rationale:** OF2412 split `setRootCaseLists.H` into separate files for better organization.

#### 1.3 Dynamic Mesh Creation

**OF6:**
```cpp
#include "createDynamicFvMesh.H"
// Internally calls: dynamicFvMesh::New(runTime)
```

**OF2412:**
```cpp
#include "createDynamicFvMesh.H"
// Internally calls: dynamicFvMesh::New(args, runTime)
```

**Rationale:** OF2412 requires the `args` parameter in the mesh constructor for command-line argument handling.

#### 1.4 Turbulence Model Validation

**OF6:**
```cpp
turbulence->validate();
```

**OF2412:**
```cpp
// validate() removed - model validated during construction
```

**Rationale:** The `validate()` method was removed in OF2412. Validation is now performed during the turbulence model construction.

#### 1.5 Include Path Changes

**OF6:**
```cpp
#include "turbulentTransportModel.H"
```

**OF2412:**
```cpp
#include "incompressibleInterPhaseTransportModel.H"
```

**Rationale:** The turbulence model architecture changed in OF2412. The `incompressibleInterPhaseTransportModel` wraps the turbulence model for two-phase flows.

#### 1.6 CorrectPhi Include

**OF6:**
```cpp
#include "CorrectPhi.H"
```

**OF2412:**
```cpp
#include "correctPhiLocal.H"
```

**Rationale:** On macOS (case-insensitive filesystem), including `CorrectPhi.H` shadows the library header `finiteVolume/cfdTools/general/CorrectPhi/CorrectPhi.H`. Renamed to `correctPhiLocal.H` to avoid collision.

### 2. createFields.H (Field Initialization)

#### 2.1 Turbulence Model

**OF6:**
```cpp
autoPtr<incompressible::turbulenceModel> turbulence
(
    incompressible::turbulenceModel::New(U, phi, laminarTransport)
);
```

**OF2412:**
```cpp
typedef incompressibleInterPhaseTransportModel
    <
        immiscibleIncompressibleTwoPhaseMixture
    > transportModelType;

autoPtr<transportModelType> turbulence
(
    new transportModelType(rho, U, phi, rhoPhi, mixture)
);
```

**Rationale:** OF2412 uses `incompressibleInterPhaseTransportModel` which wraps the turbulence model for two-phase flows. The constructor takes `rho`, `U`, `phi`, `rhoPhi`, and `mixture` instead of just `U`, `phi`, and `transport`.

#### 2.2 Gravitational Acceleration

**OF6:**
```cpp
#include "uniformDimensionedFields.H"
uniformDimensionedVectorField g
(
    IOobject
    (
        "g",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::NO_WRITE
    )
);
```

**OF2412:**
```cpp
#include "readGravitationalAcceleration.H"
// g is now meshObjects::gravity::New(runTime)
```

**Rationale:** OF2412 moved gravity to the `meshObjects` framework. The `readGravitationalAcceleration.H` include reads gravity from `constant/g` and creates the appropriate mesh object.

#### 2.3 Reference Height (hRef)

**OF6:**
```cpp
uniformDimensionedScalarField hRef
(
    IOobject
    (
        "hRef",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::NO_WRITE
    )
);
```

**OF2412:**
```cpp
#include "readhRef.H"
// Reads from IOdictionary on mesh.thisDb()
```

**Rationale:** In OF2412, `hRef` is read from an `IOdictionary` on the mesh database rather than a `uniformDimensionedScalarField`.

#### 2.4 Density Old Time

**OF6:**
```cpp
volScalarField rho(alpha1*rho1 + alpha2*rho2);
```

**OF2412:**
```cpp
volScalarField rho(alpha1*rho1 + alpha2*rho2);
rho.oldTime();
```

**Rationale:** OF2412's `ddt(rho,U)` formulation requires `rho.oldTime()` to be called for temporal discretization.

#### 2.5 dimensionSet

**OF6:**
```cpp
dimensionedScalar("name", dimSet(0,1,-1,0,0), value);
```

**OF2412:**
```cpp
dimensionedScalar("name", dimensionSet(0,1,-1,0,0), value);
```

**Rationale:** `dimSet()` was a shorthand macro that was removed in OF2412. Use the full `dimensionSet()` constructor.

### 3. VOF Files

#### 3.1 alphaCourantNo.H

**OF6:**
```cpp
scalar maxAlphaCo
(
    runTime.controlDict().lookupOrDefault<scalar>("maxAlphaCo", 0.5)
);
```

**OF2412:**
```cpp
scalar maxAlphaCo
(
    runTime.controlDict().get<scalar>("maxAlphaCo")
);
```

**Rationale:** OF2412 changed `lookupOrDefault` to `get` for required entries.

#### 3.2 setDeltaT.H

**OF6:**
```cpp
if (adjustTimeStep)
{
    if ((runTime.timeIndex() == 0) && (CoNum > SMALL))
    {
        runTime.setDeltaT
        (
            min
            (
                maxCo*runTime.deltaTValue()/CoNum,
                min(runTime.deltaTValue(), maxDeltaT)
            )
        );
    }
}
```

**OF2412:** (Same structure, no changes needed)

**Rationale:** The time step control logic is compatible between versions.

### 4. correctPhiLocal.H

**OF6:**
```cpp
// Included as CorrectPhi.H
CorrectPhi(U, phi, p_rgh, rAUf, geometricZeroField(), pimple);
```

**OF2412:**
```cpp
// Renamed to correctPhiLocal.H to avoid macOS collision
CorrectPhi
(
    U,
    phi,
    p_rgh,
    surfaceScalarField("rAUf", fvc::interpolate(rAU())),
    geometricZeroField(),
    pimple
);
```

**Rationale:** Two changes:
1. Renamed to avoid macOS case-insensitive filesystem collision
2. `rAU` is now `tmp<volScalarField>`, so we create the face field inline

### 5. initCorrectPhi.H

**OF6:**
```cpp
scalarField rAU(1.0/UEqn.A());
```

**OF2412:**
```cpp
tmp<volScalarField> rAU;
if (correctPhi)
{
    rAU = new volScalarField(...);
    #include "correctPhiLocal.H"
}
else
{
    CorrectPhi(U, phi, p_rgh, dimensionedScalar(...), geometricZeroField(), pimple);
}
```

**Rationale:** OF2412 uses `tmp<volScalarField>` instead of `scalarField` for `rAU`. The initialization also handles the case where `correctPhi` is disabled.

### 6. Make/options (Build Configuration)

#### 6.1 Include Paths

**OF6:**
```
EXE_INC = \
    -I$(LIB_SRC)/TurbulenceModels/incompressible/turbulentTransportModel \
    -I$(LIB_SRC)/transportModels/incompressible/singlePhaseTransportModel \
    -I$(LIB_SRC)/finiteVolume/cfdTools/general \
    -I$(LIB_SRC)/dynamicFvMesh/lnInclude
```

**OF2412:**
```
EXE_INC = \
    -I$(LIB_SRC)/TurbulenceModels/phaseIncompressible/VOFphase/VOFphaseTurbulentTransportModels/lnInclude \
    -I$(LIB_SRC)/TurbulenceModels/phaseIncompressible/VOFphase/VOFphaseIncompressibleTurbulenceModels/lnInclude \
    -I$(LIB_SRC)/TurbulenceModels/phaseIncompressible/lnInclude \
    -I$(LIB_SRC)/transportModels/incompressible/singlePhaseTransportModel \
    -I$(LIB_SRC)/transportModels/incompressible/lnInclude \
    -I$(LIB_SRC)/finiteVolume/cfdTools/general \
    -I$(LIB_SRC)/finiteVolume/lnInclude \
    -I$(LIB_SRC)/dynamicFvMesh/lnInclude \
    -I$(LIB_SRC)/phaseSystemModels/twoPhaseInter/incompressibleInterPhaseTransportModel/lnInclude \
    -I$(LIB_SRC)/MRFModels/lnInclude \
    -I$(LIB_SRC)/regionModels/lnInclude \
    -I$(LIB_SRC)/sampling/lnInclude
```

**Rationale:** OF2412 reorganized the turbulence model includes. The key additions are:
- `phaseIncompressible` paths for two-phase turbulence
- `incompressibleInterPhaseTransportModel` for the new transport model
- `MRFModels` and `regionModels` for compatibility

#### 6.2 Library Links

**OF6:**
```
LIBS = \
    -lfiniteVolume \
    -ldynamicFvMesh
```

**OF2412:**
```
LIBS = \
    -lfiniteVolume \
    -ldynamicFvMesh \
    -lVoFphaseTurbulentTransportModels \
    -lincompressibleInterPhaseTransportModels \
    -lwaveModels
```

**Rationale:** OF2412 requires additional libraries:
- `VoFphaseTurbulentTransportModels` for VOF turbulence
- `incompressibleInterPhaseTransportModels` for two-phase transport
- `waveModels` for wave dynamics (not used but required for linking)

### 7. Tutorial Fixes

#### 7.1 fvSolution relaxationFactors

**Original (OF6):**
```
relaxationFactors
{
}
    "U.*"           0.82;
}
```

**Fixed (OF2412):**
```
relaxationFactors
{
    equations
    {
        "U.*"           0.82;
    }
}
```

**Rationale:** OF2412 requires relaxation factors to be wrapped in the `equations` sub-dictionary. The original format had the `"U.*"` entry outside the block.

#### 7.2 turbulenceProperties

Many tutorials were missing `constant/turbulenceProperties`. Added:
```
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}

simulationType  laminar;
```

#### 7.3 dynamicMeshDict

Some tutorials were missing `constant/dynamicMeshDict`. Added:
```
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      dynamicMeshDict;
}

dynamicFvMesh   staticFvMesh;
```

#### 7.4 Legacy Fields

Some tutorials contained fields not used by beamWeldFoam (`D`, `gradTSol`, `TRHS`, `sourceTerm`). These were removed from the initial conditions to avoid confusion.

## Testing Results

All tutorials were tested with a short endTime (1e-06 s) to verify compilation and basic functionality:

| Tutorial | Status | Timesteps | Notes |
|----------|--------|-----------|-------|
| ArcCase | ✅ PASS | 10 | 2D arc welding, aluminium |
| Test | ✅ PASS | 10 | Single particle melting |
| SingleParticleMelting2D | ✅ PASS | 10 | Single particle on substrate |
| PowderBed2D | ✅ PASS | 2 | 150+ powder particles |
| PowderBed3D | ✅ PASS | 7 | 3D powder bed, 216k cells |
| EB_3D | ✅ PASS | 1 | 3D electron beam, 216k cells |
| SenDavies | ✅ PASS | 1 | Natural convection benchmark |
| Tancase | ✅ PASS | 10 | Tin melting benchmark |
| GalluimCase | ✅ PASS | 10 | Gallium melting (2D) |
| GalluimCase3D | ⚠️ SKIP | - | 6.7M cells, needs >16GB RAM |

## Known Issues

1. **GalluimCase3D**: Requires >16GB RAM (6.7M cells). Not tested on 16GB hardware.

2. **writeCompression warning**: The `uncompressed` keyword in controlDict generates a warning in OF2412:
   ```
   Unknown compression specifier 'uncompressed' using compression off
   ```
   This is cosmetic and does not affect functionality.

3. **macOS case-insensitive filesystem**: The `CorrectPhi.H` include was renamed to `correctPhiLocal.H` to avoid collision with the library header.

## Future Work

1. **Radiation model**: Would need separate coupling for radiation heat transfer
2. **Solid mechanics**: Use FreeFEM coupling for stress/deformation analysis
3. **Acoustic coupling**: Use FreeFEM coupling for vibration analysis
4. **Parallel testing**: Verify parallel decomposition works correctly
5. **Performance optimization**: Profile and optimize for M4 hardware

## References

1. Tom Flint, "beamWeldFoam", GitHub repository: https://github.com/tomflint22/beamWeldFoam
2. OpenFOAM Foundation, "OpenFOAM 2412 Documentation": https://openfoam.org
3. Goldak, J., Chakravarti, A., & Bibby, M. (1984). "A new finite element model for welding heat sources." Metallurgical Transactions B, 15(2), 299-305.
