/*---------------------------------------------------------------------------*\
  Alpha Flux Initialization for beamWeldFoam

  Initializes the face flux fields needed for VOF advection.
  These fields are used by MULES to ensure boundedness of alpha1.

  Fields created:
      alphaPhi10 - Face flux from previous time step (for Crank-Nicolson)
      talphaPhi1Corr0 - MULES correction flux (cached between iterations)
      alphaPhiUn - Uncompressed alpha flux (for scalar transport)

  Supports restart from checkpoint files.

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

// ---- Alpha flux from previous time step ----
// Used for Crank-Nicolson time stepping and MULES correction
IOobject alphaPhi10Header
(
    IOobject::groupName("alphaPhi0", alpha1.group()),
    runTime.timeName(),
    mesh,
    IOobject::READ_IF_PRESENT,
    IOobject::AUTO_WRITE
);

// ---- Check for restart ----
// If alphaPhi0 exists on disk, this is a restart
const bool alphaRestart =
    alphaPhi10Header.typeHeaderOk<surfaceScalarField>(true);

if (alphaRestart)
{
    Info << "Restarting alpha" << endl;
}

// ---- Initialize alpha flux from previous time step ----
// alphaPhi10 = phi * interpolate(alpha1)
// This is the face flux weighted by the volume fraction
surfaceScalarField alphaPhi10
(
    alphaPhi10Header,
    phi*fvc::interpolate(alpha1)
);

// ---- MULES correction flux ----
// talphaPhi1Corr0 caches the compression flux between iterations
// Used for the MULES correction algorithm
tmp<surfaceScalarField> talphaPhi1Corr0;

// ---- Uncompressed alpha flux ----
// alphaPhiUn = uncompressed face flux for alpha1
// Used by scalarTransportFoam if needed
surfaceScalarField alphaPhiUn
(
    IOobject
    (
        "alphaPhiUn",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar(phi.dimensions(), Zero)
);
