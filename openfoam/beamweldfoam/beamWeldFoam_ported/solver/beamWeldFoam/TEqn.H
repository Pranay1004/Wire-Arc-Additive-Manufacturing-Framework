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
    Energy equation for beamWeldFoam.
    Solves the temperature equation with:
        - Convective transport (rho*cp*T)
        - Thermal diffusion (kappa * laplacian(T))
        - Latent heat source (from phase change)
        - Viscous dissipation heating
        - Volumetric heat source (from beam)
        - Iterative correction for phase fraction (epsilon1)

    Equation:
        ddt(rho*cp, T) + div(rho*cp*phi, T) - laplacian(kappa, T)
        = fvOptions + sourceTerm - Qv*|grad(alpha)| - TRHS

    Where:
        TRHS = LatentHeat * (ddt(rho,eps) + div(rho*phi,eps))
        Qv = evaporative heat loss
        sourceTerm = volumetric heat source from beam

    The temperature and phase fraction (epsilon1) are solved iteratively
    until convergence (residual < epsilonTol or iter > maxTCorr).

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
    // ITERATIVE CONVERGENCE VARIABLES
    // ========================================================================

    // ---- Iteration counter ----
    int iter = 0;

    // ---- Convergence residuals ----
    // residual = max change in epsilon1 between iterations
    // meanResidual = volume-weighted mean change in epsilon1
    // Tresidual = temperature residual (not currently used)
    dimensionedScalar residual
    (
        "residual", dimensionSet(0, 0, 0, 0, 0), scalar(1.0)
    );
    dimensionedScalar meanResidual
    (
        "meanResidual", dimensionSet(0, 0, 0, 0, 0), scalar(1.0)
    );
    dimensionedScalar Tresidual
    (
        "Tresidual", dimensionSet(0, 0, 0, 0, 0), scalar(1.0)
    );

    // ---- Reset temperature RHS ----
    // TRHS accumulates the latent heat source term
    TRHS *= 0.0;

    // ========================================================================
    // DENSITY-CP PRODUCT AND MASS FLUX
    // ========================================================================

    // ---- rhoCp = rho * cp [J/(m^3 K)] ----
    // Effective volumetric heat capacity
    const volScalarField rhoCp(rho*cp);

    // ---- rhophicp = rho * phi * cp [W/K] ----
    // Convective mass flux weighted by specific heat
    const surfaceScalarField rhophicp(fvc::interpolate(cp)*rhoPhi);

    // ========================================================================
    // ITERATIVE TEMPERATURE-PHASE FRACTION COUPLING
    // ========================================================================

    // ---- Do-while loop for temperature/epsilon1 coupling ----
    // The temperature equation and phase fraction are coupled:
    //   1. Solve temperature equation
    //   2. Update epsilon1 from temperature (lever rule)
    //   3. Check convergence
    //   4. Repeat until converged or max iterations reached
        do
        {
            iter++;

            // ---- Store previous iteration values ----
            // Needed for convergence check (compare current vs previous)
            epsilon1.storePrevIter();
            Temperature.storePrevIter();

            // ---- Latent heat source term ----
            // TRHS = LatentHeat * (ddt(rho,eps) + div(rho*phi,eps))
            // This represents the energy absorbed/released during phase change
            // It's subtracted from the temperature equation RHS
            TRHS = LatentHeat*((fvc::ddt(rho,epsilon1) + fvc::div(rhoPhi, epsilon1)));

            // ========================================================================
            // VISCOUS DISSIPATION
            // ========================================================================

            // ---- Velocity gradient tensor ----
            // gradU = gradient of velocity [1/s]
            const volTensorField gradU(fvc::grad(U));

            // ---- Viscous stress tensor ----
            // tau = mu*(gradU + gradU^T) - (2/3)*mu*div(U)*I
            // For incompressible flow: div(U) = 0, so tau = mu*(gradU + gradU^T)
            const volTensorField tau(((mixture.mu()*gradU) + (mixture.mu()*gradU.T()))-((2.0/3.0)*mixture.mu()*(fvc::div(phi))*I));

            // ========================================================================
            // EVAPORATIVE HEAT LOSS
            // ========================================================================

            // ---- Evaporative heat flux ----
            // Qv = Hertz-Knudsen evaporation rate * latent heat
            // Activated when T > Tvap - TSmooth/2
            // Qv = 0.82 * LatentHeatVap * Mm * p0 * exp(...) / sqrt(2*pi*Mm*R*T)
            // ---- Clamp temperature for evaporation model ----
            // Prevents pow(negative, 0.5) FPE during transient PIMPLE iterations
            const volScalarField Tclamp(max(Temperature, dimensionedScalar("Tmin", dimTemperature, 1.0)));

            Qv = min
            (
                max((Temperature - (Tvap - (TSmooth/2.0)))/TSmooth, 0.0),
                1.0
            )*0.82*LatentHeatVap*Mm*p0*Foam::exp
            (
                LatentHeatVap*Mm*((Tclamp-Tvap)/(R*Tclamp*Tvap))
            )/Foam::pow(2*M_PI*Mm*R*Tclamp,0.5);

            // ========================================================================
            // THERMAL DAMPING
            // ========================================================================

            // ---- Thermal damper ----
            // thermalDamper = 2*rhoCp/(rho1*cp1 + rho2*cp2)
            // Damps thermal oscillations at the interface
            if (damperSwitch)
            {
                thermalDamper = 2.0*(rhoCp)/(rho1*cp1 + rho2*cp2);
            }

            // ---- Viscous dissipation ----
            // ViscousDissipation = tau : gradU [W/m^3]
            // Converts kinetic energy to heat (important in high-shear regions)
            ViscousDissipation = (tau && gradU);

            // ========================================================================
            // TEMPERATURE EQUATION
            // ========================================================================

            // ---- Assemble the temperature equation ----
            // Terms:
            //   fvm::ddt(rhoCp, T)           - temporal heat storage
            //   fvm::div(rhophicp, T)         - convective heat transport
            //   - fvm::Sp(...)                 - implicit correction for stability
            //   - fvm::laplacian(kappa, T)     - thermal diffusion (Fourier's law)
            //   - (tau && gradU)               - viscous dissipation (explicit)
            //   == fvOptions                   - finite volume options
            //   + sourceTerm                   - volumetric heat source (beam)
            //   - Qv*|grad(alpha)|             - evaporative heat loss
            //   - TRHS                         - latent heat (absorbed/released)
            fvScalarMatrix  TEqn
            (
                fvm::ddt(rhoCp,Temperature)
              + fvm::div(rhophicp, Temperature)
              - fvm::Sp(fvc::ddt(rhoCp) + fvc::div(rhophicp), Temperature)
              - fvm::laplacian(kappa, Temperature)
              - (tau && gradU) // Viscous dissipation
             ==
                fvOptions(rhoCp,Temperature)
              + sourceTerm
              - Qv*mag(gradAlpha)*thermalDamper
              - TRHS
            );

            // ---- Under-relaxation ----
            TEqn.relax();

            // ---- Apply fvOptions constraints ----
            fvOptions.constrain(TEqn);

            // ---- Solve for temperature ----
            TEqn.solve();

            // ---- Correct temperature for fvOptions ----
            fvOptions.correct(Temperature);

            // ---- Physical boiling cap (as in DEFAULT.edp) ----
            // Latent heat of vaporization caps liquid temperature near Tvap (3300 K)
            Temperature = min
            (
                max(Temperature, dimensionedScalar("TminBound", dimTemperature, 200.0)),
                dimensionedScalar("TmaxCap", dimTemperature, 3300.0)
            );

            // ========================================================================
            // PHASE FRACTION UPDATE (LEVER RULE)
            // ========================================================================

            // ---- Temperature correction for epsilon1 ----
            // Tcorr = (Tliquidus - Tsolidus)*eps + Tsolidus
            // This maps epsilon1 to a temperature in the mushy zone
            Tcorr = (TLiquidus - TSolidus)*epsilon1 + TSolidus;

            // ---- Update epsilon1 using iterative correction ----
            // epsilon1 = eps + (epsilonRel*cp/LatentHeat)*(T - Tcorr)
            // This is a Picard iteration for the phase fraction:
            //   - If T > Tcorr: eps increases (melting)
            //   - If T < Tcorr: eps decreases (solidification)
            // epsilonRel = relaxation factor (0.95 typical) for stability
            epsilon1 = max
            (
                min
                (
                    epsilon1+(epsilonRel*cp/LatentHeat)*(Temperature-Tcorr),
                    scalar(1)
                ),
                scalar(0)
            );

            // ========================================================================
            // CONVERGENCE CHECK
            // ========================================================================

            // ---- Maximum residual (pointwise) ----
            // Checks the maximum change in epsilon1 across all cells
            residual = gMax
            (
                mag
                (
                    epsilon1.primitiveField()
                  - epsilon1.prevIter().primitiveField()
                )
            );

            // ---- Mean residual (volume-weighted) ----
            // Checks the average change in epsilon1 across all cells
            meanResidual = gSum
            (
                mag
                (
                    epsilon1.primitiveField() - epsilon1.prevIter().primitiveField()
                )*mesh.V()
            )/gSum(mesh.V().field());

            // ---- Print convergence info ----
            Info<< "Correcting epsilon1, mean residual = "
                << meanResidual.value()
                << ", max residual = " << residual.value()
                << endl;

            // ---- Rate of change of epsilon1 ----
            // ddte1 = d(eps)/dt, used for boundedness in fvSchemes
            ddte1 = fvc::ddt(epsilon1);
        }
        // ---- Loop termination criteria ----
        // Continue if:
        //   - iter < minTCorr (minimum iterations, e.g., 1)
        //   OR
        //   - residual > epsilonTol (not yet converged)
        // AND
        //   - iter <= maxTCorr (maximum iterations, e.g., 150)
        while
        (
            (iter < minTCorr || (residual > epsilonTol) ) && iter <= maxTCorr
        );

    // ---- Correct boundary conditions for temperature ----
    Temperature.correctBoundaryConditions();

    // ---- Compute temperature gradient ----
    // gradT = gradient of Temperature [K/m]
    // Used for Marangoni force calculation in UEqn.H
    gradT = fvc::grad(Temperature);
}
