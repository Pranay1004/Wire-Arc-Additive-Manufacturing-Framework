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
    VOF (Volume of Fluid) alpha equation with sub-cycling for beamWeldFoam.

    The VOF method tracks the interface between two immiscible fluids
    (liquid metal and gas) using a volume fraction field alpha1:
        alpha1 = 1: cell is filled with liquid/solid metal
        alpha1 = 0: cell is filled with gas
        0 < alpha1 < 1: cell contains the interface

    Sub-cycling improves stability by taking multiple smaller time steps
    for the alpha equation than for the momentum/energy equations.

    After the alpha equation is solved, the density field is updated:
        rho = alpha1*rho1 + alpha2*rho2

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

if (nAlphaSubCycles > 1)
{
    // ========================================================================
    // SUB-CYCLING MODE (nAlphaSubCycles > 1)
    // ========================================================================

    // ---- Save the total time step ----
    dimensionedScalar totalDeltaT = runTime.deltaT();

    // ---- Accumulate rhoPhi over sub-cycles ----
    // rhoPhiSum = sum of (rho*phi) over all sub-cycles
    // This ensures mass conservation when sub-cycling
    surfaceScalarField rhoPhiSum
    (
        IOobject
        (
            "rhoPhiSum",
            runTime.timeName(),
            mesh
        ),
        mesh,
        dimensionedScalar("0", rhoPhi.dimensions(), 0)
    );

    // ---- LTS support ----
    // For local time stepping, compute the sub-cycle time step ratio
    tmp<volScalarField> trSubDeltaT;

    if (LTS)
    {
        trSubDeltaT =
            fv::localEulerDdt::localRSubDeltaT(mesh, nAlphaSubCycles);
    }

    // ---- Sub-cycle loop ----
    // Take nAlphaSubCycles smaller time steps for the alpha equation
    // Each sub-cycle solves alphaEqn.H with deltaT/nAlphaSubCycles
    for
    (
        subCycle<volScalarField> alphaSubCycle(alpha1, nAlphaSubCycles);
        !(++alphaSubCycle).end();
    )
    {
        // ---- Solve alpha equation for this sub-cycle ----
        #include "alphaEqn.H"

        // ---- Accumulate mass flux ----
        // Weight by the sub-cycle time step ratio
        rhoPhiSum += (runTime.deltaT()/totalDeltaT)*rhoPhi;
    }

    // ---- Use the accumulated mass flux ----
    rhoPhi = rhoPhiSum;
}
else
{
    // ========================================================================
    // SINGLE STEP MODE (nAlphaSubCycles = 1)
    // ========================================================================

    // ---- Solve alpha equation once ----
    #include "alphaEqn.H"
}

// ========================================================================
// UPDATE DENSITY FIELD
// ========================================================================

// ---- rho = alpha1*rho1 + alpha2*rho2 ----
// After the alpha equation is solved, update the density field
// This ensures consistency between alpha and rho
rho == alpha1*rho1 + alpha2*rho2;
