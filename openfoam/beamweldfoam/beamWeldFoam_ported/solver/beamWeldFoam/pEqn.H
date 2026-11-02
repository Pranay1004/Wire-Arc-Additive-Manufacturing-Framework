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
    Pressure equation for beamWeldFoam.
    Solves the pressure Poisson equation with:
        - Surface tension pressure
        - Vapor recoil pressure
        - Gravity (buoyancy)
        - Non-orthogonal correction

    The pressure equation enforces the continuity constraint (div(U) = 0)
    by solving a Poisson equation for the pressure correction.

    Algorithm (PISO/PIMPLE):
        1. Compute HbyA = U + rAU * grad(p_rgh)
        2. Compute phiHbyA = face flux from HbyA
        3. Add surface tension, recoil, gravity to phiHbyA
        4. Solve Laplacian(p_rgh) = div(phiHbyA)
        5. Correct U and phi from pressure solution

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

{
    // ========================================================================
    // RECIPROCAL DIAGONAL COEFFICIENT
    // ========================================================================

    // ---- rAU = 1/A(U) [m^3 s/kg] ----
    // A(U) is the diagonal coefficient of the momentum equation
    // rAU = 1/diag(UEqn) = 1/(rho*V/dt + ...)
    // For moving meshes (correctPhi), we store as reference for aliasing
    if (correctPhi)
    {
        rAU.ref() = 1.0/UEqn.A();
    }
    else
    {
        rAU = 1.0/UEqn.A();
    }

    // ---- Interpolate rAU to faces ----
    // rAUf = face-interpolated rAU for the pressure equation
    surfaceScalarField rAUf("rAUf", fvc::interpolate(rAU()));

    // ========================================================================
    // HbyA VECTOR (INTERMEDIATE VELOCITY)
    // ========================================================================

    // ---- HbyA = rAU * H(U) ----
    // H(U) = off-diagonal terms of momentum equation
    // HbyA is the velocity that would result if pressure gradient were zero
    volVectorField HbyA(constrainHbyA(rAU()*UEqn.H(), U, p_rgh));

    // ---- Face flux from HbyA ----
    // phiHbyA = HbyA & Sf + time derivative correction
    // The ddtCorr term accounts for the temporal discretization
    surfaceScalarField phiHbyA
    (
        "phiHbyA",
        fvc::flux(HbyA)
      + MRF.zeroFilter(fvc::interpolate(rho*rAU())*fvc::ddtCorr(U, phi, Uf))
    );
    MRF.makeRelative(phiHbyA);

    // ---- Reference pressure correction ----
    // If p_rgh has a reference value, adjust phiHbyA to maintain consistency
    if (p_rgh.needReference())
    {
        fvc::makeRelative(phiHbyA, U);
        adjustPhi(phiHbyA, U, p_rgh);
        fvc::makeAbsolute(phiHbyA, U);
    }

    // ========================================================================
    // PRESSURE GRADIENT CONTRIBUTIONS
    // ========================================================================

    // ---- phig = face flux from pressure-related terms ----
    // Terms contributing to the pressure equation:
    //   1. Surface tension: sigma * kappa_n * grad(alpha1)
    //   2. Vapor recoil: pVap * snGrad(alpha1)
    //   3. Gravity: -ghf * snGrad(rho*rhok)
    //   4. Pressure gradient: -snGrad(p_rgh)
    // All multiplied by rAUf and mesh.magSf() for face integration
    surfaceScalarField phig
    (
        (
            mixture.surfaceTensionForce()*fvc::interpolate(damper)
        + fvc::interpolate(pVap)*fvc::snGrad(alpha1)*fvc::interpolate(damper)
          - ghf*fvc::snGrad(rho*rhok)
        )*rAUf*mesh.magSf()
    );

    // ---- Add phig to phiHbyA ----
    // phiHbyA now contains all contributions to the face flux
    phiHbyA += phig;

    // ---- Constrain pressure boundary conditions ----
    // Ensures that the boundary flux is consistent with the velocity BCs
    constrainPressure(p_rgh, U, phiHbyA, rAUf, MRF);

    // ========================================================================
    // PRESSURE POISSON EQUATION (NON-ORTHOGONAL CORRECTION)
    // ========================================================================

    // ---- Solve for p_rgh ----
    // Laplacian(rAUf, p_rgh) = div(phiHbyA)
    // This is the pressure Poisson equation enforcing continuity
    // Non-orthogonal correction: iterate to handle non-orthogonal meshes
    while (pimple.correctNonOrthogonal())
    {
        // ---- Assemble pressure equation ----
        fvScalarMatrix p_rghEqn
        (
            fvm::laplacian(rAUf, p_rgh) == fvc::div(phiHbyA)
        );

        // ---- Set reference cell ----
        // Fixes pressure at one cell to remove the null space
        p_rghEqn.setReference(pRefCell, getRefCellValue(p_rgh, pRefCell));

        // ---- Solve the pressure equation ----
        // Uses the selected solver from fvSolution (e.g., GAMG, PCG)
        p_rghEqn.solve(mesh.solver(p_rgh.select(pimple.finalInnerIter())));

        // ---- Update flux and velocity on final iteration ----
        if (pimple.finalNonOrthogonalIter())
        {
            // ---- Correct face flux ----
            // phi = phiHbyA - p_rghEqn.flux()
            // The flux correction ensures continuity is satisfied
            phi = phiHbyA - p_rghEqn.flux();

            // ---- Relax pressure ----
            p_rgh.relax();

            // ---- Correct velocity from pressure ----
            // U = HbyA + rAU * grad(p_rgh)
            // This is the pressure-correction step
            U = HbyA + rAU()*fvc::reconstruct((phig - p_rghEqn.flux())/rAUf);
            U.correctBoundaryConditions();
            fvOptions.correct(U);
        }
    }

    // ---- Check continuity errors ----
    // Reports the divergence of phi (should be ~0 for incompressible flow)
    #include "continuityErrs.H"

    // ---- OF2412: Correct face velocity for moving meshes ----
    // fvc::correctUf ensures Uf is consistent with U and phi
    fvc::correctUf(Uf, U, phi);

    // ---- Make fluxes relative to mesh motion ----
    // For static meshes, this is a no-op
    fvc::makeRelative(phi, U);

    // ========================================================================
    // COMPUTE TOTAL PRESSURE
    // ========================================================================

    // ---- p = p_rgh + rho*gh*rhok ----
    // Recovers the total pressure from the modified pressure
    p == p_rgh + rho*gh*rhok;

    // ---- Apply reference pressure correction ----
    if (p_rgh.needReference())
    {
        p += dimensionedScalar
        (
            "p",
            p.dimensions(),
            pRefValue - getRefCellValue(p, pRefCell)
        );
        p_rgh = p - rho*gh*rhok;
    }

    // ---- Clear rAU if not needed for phi correction ----
    if (!correctPhi)
    {
        rAU.clear();
    }

    // ---- Diagnostic: divergence of velocity ----
    // Num_divU = div(phi), should be ~0 for incompressible flow
    Num_divU=fvc::div(phi);

}
