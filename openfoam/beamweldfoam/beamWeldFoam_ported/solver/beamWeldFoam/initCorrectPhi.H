/*---------------------------------------------------------------------------*\
  Phi Initialization for Moving Meshes (beamWeldFoam)

  Initializes the face flux (phi) correction for moving meshes.
  This is called at the start of the simulation to ensure that phi
  is consistent with the initial mesh and velocity fields.

  OF2412 changes:
      - rAU is now tmp<volScalarField> (not scalarField)
      - The rAU field is stored for later use in pEqn.H
      - CorrectPhi() uses dimensionedScalar for rAUf

  Two modes:
      1. correctPhi=true: Store rAU and call correctPhiLocal.H
      2. correctPhi=false: Call CorrectPhi directly with constant rAUf

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

// ---- Reciprocal diagonal coefficient ----
// rAU = 1/A(U) where A(U) is the diagonal of the momentum equation
// Stored as tmp<volScalarField> for use in pEqn.H
tmp<volScalarField> rAU;

if (correctPhi)
{
    // ---- Initialize rAU field ----
    // This field stores the reciprocal diagonal for the pressure equation
    // It's computed from the momentum equation diagonal coefficients
    rAU = new volScalarField
    (
        IOobject
        (
            "rAU",
            runTime.timeName(),
            mesh,
            IOobject::READ_IF_PRESENT,
            IOobject::AUTO_WRITE
        ),
        mesh,
        dimensionedScalar("rAU", dimTime/dimDensity, 1)
    );

    // ---- Correct phi using the stored rAU ----
    #include "correctPhiLocal.H"
}
else
{
    // ---- Direct correction with constant rAUf ----
    // If correctPhi is disabled, use a constant rAUf
    // This is the simpler path for static meshes
    CorrectPhi
    (
        U,
        phi,
        p_rgh,
        dimensionedScalar("rAUf", dimTime/rho.dimensions(), 1),
        geometricZeroField(),
        pimple
    );

    // ---- Check continuity errors ----
    #include "continuityErrs.H"
}
