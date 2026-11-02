/*---------------------------------------------------------------------------*\
  Phi Correction for Moving Meshes (beamWeldFoam)

  Corrects the face flux (phi) to ensure consistency with the mesh motion.
  This is called when the mesh is moving (dynamicFvMesh) and correctPhi=true.

  The CorrectPhi function:
      1. Computes the mesh velocity at faces
      2. Adjusts phi to account for mesh motion
      3. Ensures continuity is satisfied

  Renamed from CorrectPhi.H to correctPhiLocal.H to avoid macOS
  case-insensitive filesystem collision with the library header
  finiteVolume/cfdTools/general/CorrectPhi/CorrectPhi.H

  OF2412 changes:
      - rAU is now tmp<volScalarField> (not scalarField)
      - CorrectPhi() signature changed to use geometricZeroField
      - The pimple reference is passed directly

  Original authors:
      Thomas F. Flint, University of Manchester
      Gowthaman Parivendhan, University College Dublin
      Alojz Ivankovic, University College Dublin
      Michael C. Smith, University of Manchester
      Philip Cardiff, University College Dublin

  OpenFOAM 2412 port by:
      Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
      github.com/Pranay1004

\*---------------------------------------------------------------------------*/

// ---- Correct phi for mesh motion ----
// This adjusts the face flux to account for the moving mesh
CorrectPhi
(
    U,
    phi,
    p_rgh,
    surfaceScalarField("rAUf", fvc::interpolate(rAU())),
    geometricZeroField(),
    pimple
);

// ---- Check continuity errors ----
// Reports the divergence of phi (should be ~0 after correction)
#include "continuityErrs.H"
