/*---------------------------------------------------------------------------*\
  Alpha Courant Number for beamWeldFoam

  Computes the Courant number specifically for the VOF interface.
  This is different from the standard Courant number because it only
  considers cells near the interface (where alpha1 is between 0 and 1).

  The alpha Courant number is used to limit the time step to ensure
  stable advection of the interface.

  Co_alpha = 0.5 * max(|phi| * nearInterface / V) * dt

  Where:
      phi = face flux [m^3/s]
      nearInterface = 1 if 0 < alpha1 < 1, 0 otherwise
      V = cell volume [m^3]
      dt = time step [s]

  The time step is adjusted to keep Co_alpha < maxAlphaCo (from controlDict).

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

// ---- Maximum alpha Courant number (from controlDict) ----
scalar maxAlphaCo
(
    runTime.controlDict().get<scalar>("maxAlphaCo")
);

// ---- Alpha Courant numbers ----
scalar alphaCoNum = 0.0;
scalar meanAlphaCoNum = 0.0;

if (mesh.nInternalFaces())
{
    // ---- Sum face fluxes near the interface ----
    // sumPhi = sum of |phi| for faces where 0 < alpha1 < 1
    // This only counts flux across the interface, not throughout the domain
    scalarField sumPhi
    (
        mixture.nearInterface()().primitiveField()
       *fvc::surfaceSum(mag(phi))().primitiveField()
    );

    // ---- Maximum alpha Courant number ----
    // alphaCoNum = 0.5 * max(sumPhi/V) * dt
    // The 0.5 factor accounts for the fact that flux enters through two faces
    alphaCoNum = 0.5*gMax(sumPhi/mesh.V().field())*runTime.deltaTValue();

    // ---- Mean alpha Courant number ----
    meanAlphaCoNum =
        0.5*(gSum(sumPhi)/gSum(mesh.V().field()))*runTime.deltaTValue();
}

// ---- Print alpha Courant numbers ----
Info<< "Interface Courant Number mean: " << meanAlphaCoNum
    << " max: " << alphaCoNum << endl;

// ************************************************************************* //
