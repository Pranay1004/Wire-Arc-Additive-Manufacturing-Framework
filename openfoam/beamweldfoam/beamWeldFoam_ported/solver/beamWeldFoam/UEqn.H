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
    Momentum equation for beamWeldFoam.
    Solves the incompressible Navier-Stokes equations with:
        - Darcy damping in the mushy zone
        - Marangoni convection (surface tension gradient)
        - Vapor recoil pressure
        - Surface tension force
        - Gravity (Boussinesq approximation)

    Equation:
        ddt(rho,U) + div(rho*phi,U) + MRF.DDt(rho,U)
        + laplacian(mu,U) + DC*U - Marangoni*damper
        = surfaceTension + pVap*grad(alpha1) - grad(p_rgh) - rho*gh

    Where:
        DC = Darcy coefficient = large*(1-eps)^2/(eps^3 + small)
        Marangoni = dsigmadT * (grad(T) - n*(n.grad(T))) * |grad(alpha)|
        pVap = Clausius-Clapeyron vapor pressure
        damper = density-weighted oscillation damping factor

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

    // ---- MRF boundary velocity correction ----
    // Corrects boundary velocities for Multiple Reference Frame (not used here)
    MRF.correctBoundaryVelocity(U);

    // ========================================================================
    // DARCY DAMPING IN MUSHY ZONE
    // ========================================================================

    // ---- Darcy constants ----
    // DarcyConstantlarge = maximum permeability coefficient [kg/(m^3 s)]
    // DarcyConstantsmall = regularization parameter (prevents division by zero)
    // High DC in solid (epsilon1=0) -> strong velocity damping
    // Low DC in liquid (epsilon1=1) -> no damping
    const dimensionedScalar DarcyConstantlarge
    (
        "DarcyConstantlarge", dimensionSet(1,-3,-1,0,0), scalar(1.0e6)
    );
    const dimensionedScalar DarcyConstantsmall
    (
        "DarcyConstantsmall",
        dimensionSet(0,0,0,0,0),
        scalar(1.0e-12)
    );

    // ---- Temperature smoothing width ----
    // TSmooth = width of the smoothing function for vapor pressure [K]
    // Used to smoothly transition the vapor recoil pressure
    const dimensionedScalar TSmooth("TSmooth",dimensionSet(0, 0, 0, 1, 0),50.0);

    // ---- Compute Darcy coefficient ----
    // DC = large * (1-eps)^2 / (eps^3 + small)
    // eps = epsilon1mask (0 in solid, 1 in liquid)
    // This gives a Carman-Kozeny type permeability model
    DC =
        (
            DarcyConstantlarge*Foam::pow((1.0 - epsilon1mask), 2)
           /(Foam::pow(epsilon1mask, 3) + DarcyConstantsmall)
        );

    // ========================================================================
    // MARANGONI CONVECTION
    // ========================================================================

    // ---- Interface normal vector ----
    // gradAlpha = gradient of alpha1 (points from gas to liquid)
    const volVectorField gradAlpha(fvc::grad(alpha1));

    // ---- Normalized interface normal ----
    // nHatM = gradAlpha / (|gradAlpha| + deltaN)
    // deltaN prevents division by zero away from the interface
    const volVectorField nHatM(gradAlpha/(mag(gradAlpha) + deltaN));

    // ---- Marangoni force ----
    // Marangoni = dsigmadT * (gradT - nHatM*(nHatM & gradT)) * |gradAlpha|
    // The term (gradT - nHatM*(nHatM & gradT)) extracts the tangential
    // component of the temperature gradient along the interface
    // dsigmadT < 0 means flow from hot to cold (typical for metals)
    Marangoni = Marangoni_Constant*(gradT-nHatM*(nHatM & gradT))*mag(gradAlpha);

    // ========================================================================
    // OSCILLATION DAMPING
    // ========================================================================

    // ---- Damper field ----
    // damper = 2*rho/(rho1+rho2) when damperSwitch=true
    // This damps velocity oscillations at the interface
    // damper = 1 in liquid (rho=rho1), small in gas (rho=rho2)
    if(damperSwitch)
    {
        damper = 2.0 * rho /(rho1+rho2);
    }

    // ========================================================================
    // VAPOR RECOIL PRESSURE
    // ========================================================================

    // ---- Clausius-Clapeyron vapor pressure ----
    // pVap = 0.54 * p0 * exp(LatentHeatVap * Mm * (T-Tvap) / (R*T*Tvap))
    // The smooth step function (0 to 1) activates only when T > Tvap - TSmooth/2
    // pVap pushes the liquid surface downward (recoil from evaporation)
    // ---- Clamp temperature for vapor recoil model ----
    // Prevents exp() overflow (sigFpe) when T transiently goes negative
    // during PIMPLE iterations at the onset of melting
    const volScalarField TclampU(max(Temperature, dimensionedScalar("TminU", dimTemperature, 1.0)));

    // Cap pVap to physical atmospheric recoil scale (2 bar) to prevent explosive shockwaves
    pVap = min
    (
        min
        (
            max((Temperature - (Tvap - (TSmooth/2.0)))/TSmooth, 0.0),
            1.0
        )*0.54*p0*Foam::exp
        (
            LatentHeatVap*Mm*((TclampU-Tvap)/(R*TclampU*Tvap))
        ),
        dimensionedScalar("pVapMax", dimPressure, 2.0e5)
    );

    // ========================================================================
    // MOMENTUM EQUATION
    // ========================================================================

    // ---- Assemble the momentum equation ----
    // Terms:
    //   fvm::ddt(rho, U)              - temporal acceleration
    //   fvm::div(rhoPhi, U)           - convective transport
    //   MRF.DDt(rho, U)               - MRF contribution (zero if no MRF)
    //   turbulence->divDevRhoReff      - viscous diffusion (includes turbulence)
    //   fvm::Sp(DC, U)                 - Darcy damping (implicit for stability)
    //   - Marangoni*damper              - Marangoni force (explicit, damped)
    //   == fvOptions(rho, U)           - finite volume options (source terms)
    fvVectorMatrix UEqn
    (
        fvm::ddt(rho, U) + fvm::div(rhoPhi, U)
      + MRF.DDt(rho, U)
      + turbulence->divDevRhoReff(rho, U)
      + fvm::Sp(DC, U)
      - Marangoni*damper
     ==
        fvOptions(rho, U)
    );

    // ---- Under-relaxation ----
    // Improves stability for explicit terms
    UEqn.relax();

    // ---- Apply fvOptions constraints ----
    // Can clip values, fix boundary conditions, etc.
    fvOptions.constrain(UEqn);

    // ========================================================================
    // MOMENTUM PREDICTOR
    // ========================================================================

    // ---- Solve for velocity (predictor step) ----
    // This is the first guess for U before pressure correction
    // Only done if momentumPredictor=yes in fvSolution
    if (pimple.momentumPredictor())
    {
        solve
        (
            UEqn
         ==
            fvc::reconstruct
            (
                // ---- Surface tension force ----
                // mixture.surfaceTensionForce() = sigma * kappa_n * grad(alpha1)
                // kappa_n = interface curvature (from alpha1 gradient)
                (
                    mixture.surfaceTensionForce()*fvc::interpolate(damper)

                    // ---- Vapor recoil pressure gradient ----
                    // pVap * snGrad(alpha1) pushes the interface away from vapor
                  + fvc::interpolate(pVap)*fvc::snGrad(alpha1)
                   *fvc::interpolate(damper)

                    // ---- Gravity term ----
                    // ghf * snGrad(rho*rhok) = buoyancy force
                  - ghf*fvc::snGrad(rho*rhok)

                    // ---- Pressure gradient ----
                    // -snGrad(p_rgh) drives the flow
                  - fvc::snGrad(p_rgh)
                )*mesh.magSf()
            )
        );

        // ---- Correct velocity for fvOptions ----
        fvOptions.correct(U);
    }
