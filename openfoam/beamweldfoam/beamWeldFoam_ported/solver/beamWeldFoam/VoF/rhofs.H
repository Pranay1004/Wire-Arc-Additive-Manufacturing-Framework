/*---------------------------------------------------------------------------*\
  Phase Density References for beamWeldFoam

  Creates const references to the phase densities for use in the
  alpha equation and mass flux computation.

  rho1f = density of phase1 (liquid/solid metal) [kg/m^3]
  rho2f = density of phase2 (gas) [kg/m^3]

  These are used in alphaEqn.H to compute the mass flux:
      rhoPhi = alphaPhi10*(rho1f - rho2f) + phi*rho2f

  This ensures that the mass flux is consistent with the VOF field.

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

// ---- Phase 1 (liquid/solid) density reference ----
const dimensionedScalar& rho1f(rho1);

// ---- Phase 2 (gas) density reference ----
const dimensionedScalar& rho2f(rho2);
