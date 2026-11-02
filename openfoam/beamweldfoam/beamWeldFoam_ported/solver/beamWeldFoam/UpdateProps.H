/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     | Website:  https://openfoam.org
    \\  /    A nd           | Copyright (C) 2011-2018 OpenFOAM Foundation
     \\/     M anipulation  |
-------------------------------------------------------------------------------
License
    This file is part of OpenFOAM.

    OpenFOAM is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    OpenFOAM is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
    FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
    for more details.

    You should have received a copy of the GNU General Public License
    along with OpenFOAM.  If not, see <http://www.gnu.org/licenses/>.

Description
    Material property update routine for beamWeldFoam.
    Called after each temperature solve to update all temperature-dependent
    and phase-dependent material properties.

    Original authors:
        Thomas F. Flint, University of Manchester
        Gowthaman Parivendhan, University College Dublin
        Alojz Ivankovic, University College Dublin
        Michael C. Smith, University of Manchester
        Philip Cardiff, University College Dublin

    OpenFOAM 2412 port by:
        Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
        github.com/Pranay1004

    Properties updated:
        cp      - Effective specific heat (liquid vs solid, blended by phases)
        kappa   - Effective thermal conductivity (liquid vs solid, blended)
        TSolidus - Phase-weighted solidus temperature
        TLiquidus - Phase-weighted liquidus temperature
        LatentHeat - Phase-weighted latent heat
        beta    - Phase-weighted thermal expansion coefficient
        rhok    - Normalized density (Boussinesq approximation)
        nneps1  - Interface normal vector (from epsilon1 gradient)
        epsilon1mask - Binary mask for epsilon1 (for Darcy damping)
        gh, ghf - Gravity fields (masked by epsilon1 for buoyancy)

\*---------------------------------------------------------------------------*/

// ========================================================================
// EFFECTIVE MATERIAL PROPERTIES (LIQUID/SOLID BLENDING)
// ========================================================================

// ---- Effective specific heat ----
// cp = eps * (liquid cp) + (1-eps) * (solid cp)
// In liquid (eps=1): cp = alpha1*cp1 + alpha2*cp2
// In solid (eps=0): cp = alpha1*cp1solid + alpha2*cp2solid
// In mushy zone: linear interpolation between liquid and solid
cp =
    (epsilon1*(alpha1*cp1 + alpha2*cp2))
  + ((1.0-epsilon1)*(alpha1*cp1solid + alpha2*cp2solid));

// ---- Effective thermal conductivity ----
// kappa = eps * (liquid kappa) + (1-eps) * (solid kappa)
// Same blending as cp above
kappa =
    (epsilon1*(alpha1*kappa1 + alpha2*kappa2))
  + ((1.0-epsilon1)*(alpha1*kappa1solid + alpha2*kappa2solid));

// ---- Phase-weighted phase change temperatures ----
// TSolidus and TLiquidus are weighted by the volume fraction
// This allows different Tsolidus/Tliquidus for different phases
TSolidus = alpha1*Tsolidus1 + alpha2*Tsolidus2;
TLiquidus = alpha1*Tliquidus1 + alpha2*Tliquidus2;

// ---- Phase-weighted latent heat ----
LatentHeat = alpha1*LatentHeat1 + alpha2*LatentHeat2;

// ---- Phase-weighted thermal expansion ----
beta = alpha1*beta1 + alpha2*beta2;

// ========================================================================
// NORMALIZED DENSITY (BOUSSINESQ APPROXIMATION)
// ========================================================================

// ---- rhok = 1 - beta*(T - TSolidus) ----
// This is the Boussinesq approximation for natural convection:
//   rho = rho0 * (1 - beta*(T - T0))
//   rhok = rho/rho0 = 1 - beta*(T - T0)
// Only the thermal expansion part is included (no solutal expansion)
rhok = (1.0 - max(epsilon1*beta*(Temperature - TSolidus), 0.0));

// ========================================================================
// INTERFACE NORMAL VECTOR
// ========================================================================

// ---- Gradient of epsilon1 ----
const volVectorField gradepsilon1(fvc::grad(epsilon1));

// ---- Normalized interface normal ----
// nneps1 = grad(eps) / (|grad(eps)| + deltaN)
// Points from liquid (eps=1) to solid/air (eps=0)
// deltaN prevents division by zero away from the interface
nneps1 = fvc::grad(epsilon1)/((mag(gradepsilon1) + deltaN));

// ========================================================================
// EPSILON1 MASK (FOR DARCY DAMPING)
// ========================================================================

// ---- Cell-averaged epsilon1 ----
// e1temp = volume-weighted average of epsilon1 in each cell
// Used to create a smooth mask for the Darcy term
const volScalarField e1temp(fvc::average(epsilon1));

// ---- Create binary mask ----
// epsilon1mask = 0 if cell-averaged eps < 0.95 (mostly solid/air)
// epsilon1mask = eps if cell-averaged eps >= 0.95 (mostly liquid)
// This prevents the Darcy term from acting in cells that are
// completely liquid (where epsilon1mask ~ 1 -> DC ~ 0)
scalarField& epsilon1maskI = epsilon1mask.primitiveFieldRef();
const scalarField& e1tempI = e1temp.internalField();
const scalarField& epsilon1I = epsilon1.internalField();

forAll(epsilon1maskI, celli)
{
    if (e1tempI[celli] <= 0.95)
    {
        epsilon1maskI[celli] = 0.0;
    }
    else
    {
        epsilon1maskI[celli] = epsilon1I[celli];
    }
}

epsilon1mask.correctBoundaryConditions();

// ========================================================================
// GRAVITY FIELDS (MASKED BY PHASE)
// ========================================================================

// ---- gh = epsilon1mask * (g & C) ----
// Gravity is only applied to liquid cells (where eps > 0.95)
// This prevents buoyancy-driven flow in solid/air regions
gh = epsilon1mask*(g & mesh.C());
ghf = fvc::interpolate(epsilon1mask)*(g & mesh.Cf());
