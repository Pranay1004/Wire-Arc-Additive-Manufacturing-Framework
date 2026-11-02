/*---------------------------------------------------------------------------*\
  Alpha Source Terms for beamWeldFoam

  Initializes the source terms for the VOF alpha equation.
  In beamWeldFoam, there are no explicit source terms for alpha1
  (no mass transfer between phases in the basic model).

  These fields are set to zero and can be extended for:
      - Phase change (melting/solidification mass transfer)
      - Evaporation (liquid to gas)
      - Condensation (gas to liquid)

  For the Voller-Prakash mass transfer model (used in some tutorials),
  these fields would be populated with the phase change rate.

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

// ---- Explicit source term [kg/(m^3 s)] ----
// Su = positive source (creates alpha1, e.g., melting)
zeroField Su;

// ---- Implicit source term [1/s] ----
// Sp = negative coefficient (removes alpha1, e.g., solidification)
// The equation is: ddt(alpha1) + div(...) = Su + Sp*alpha1
// Sp should be <= 0 for stability
zeroField Sp;

// ---- Velocity divergence ----
// divU = div(U), used for the alpha equation
// For incompressible flow: divU = 0
zeroField divU;
