/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     | Website:  https://openfoam.org
    \\  /    A nd           | Copyright (C) 2011-2018 OpenFOAM Foundation
     \\/     M anipulation  |
-------------------------------------------------------------------------------
License
    beamWeldFoam - Numerical simulation of high energy density processes
    Copyright (C) 2022 Thomas F. Flint, Gowthaman Parivendhan, Alojz Ivankovic,
                        Michael C. Smith, Philip Cardiff

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    Original work: https://github.com/ElsevierSoftwareX/SOFTX-D-21-00212
    OpenFOAM port: Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
    GitHub: https://github.com/Pranay1004
    Date: September 2026

Application
    beamWeldFoam

Description
    Solver for 2 incompressible, non-isothermal immiscible fluids experiencing
    fusion state changes using a VOF (volume of fluid) phase-fraction based
    interface capturing approach, with optional mesh motion and mesh topology
    changes including adaptive re-meshing. Captures the melting and fusion of
    an alloy with arc/laser/electron beam heat source.

    Physical models:
        - Goldak-style diverging oscillating Gaussian heat source
        - Marangoni convection (surface tension gradient)
        - Vapor recoil pressure (evaporation-driven deformation)
        - Darcy damping in mushy zone
        - Latent heat of fusion
        - Viscous dissipation heating

    Original authors:
        Tom Flint, University of Manchester
        Gowthaman Parivendhan, University College Dublin
        Alojz Ivankovic, University College Dublin
        Michael C. Smith, University of Manchester
        Philip Cardiff, University College Dublin

    OpenFOAM 2412 port by:
        Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
        github.com/Pranay1004

    Key OF6 -> OF2412 changes:
        - pimpleControl.H -> #define PIMPLE_CONTROL + createControl.H
        - dynamicFvMesh::New(runTime) -> dynamicFvMesh::New(args, runTime)
        - incompressible::turbulenceModel::New -> incompressibleInterPhaseTransportModel
        - uniformDimensionedVectorField -> meshObjects::gravity::New(runTime)
        - readhRef: IOobject(runTime...) -> IOobject(..., mesh.thisDb(), ...)
        - dimSet() -> dimensionSet()
        - CorrectPhi.H path changed
        - New libraries: VoFphaseTurbulentTransportModels, incompressibleInterPhaseTransportModels

\*---------------------------------------------------------------------------*/

// ---- Standard OpenFOAM includes ----
#include "fvCFD.H"
#include "dynamicFvMesh.H"
#include "CMULES.H"
#include "EulerDdtScheme.H"
#include "localEulerDdtScheme.H"
#include "CrankNicolsonDdtScheme.H"
#include "subCycle.H"
#include "immiscibleIncompressibleTwoPhaseMixture.H"

// ---- OF2412: New turbulence model includes ----
// In OF2412, the incompressible interphase transport model is a separate class
// that wraps the turbulence model for two-phase flows.
#include "incompressibleInterPhaseTransportModel.H"

// ---- OF2412: PIMPLE control ----
// In OF2412, include pimpleControl.H directly (not via #define)
// This creates the pimpleControl class and sets PIMPLE_CONTROL define
#include "pimpleControl.H"

#include "fvOptions.H"

#include "CorrectPhi.H"

#include "fvcSmooth.H"

// ---- Standard includes for heat source and material models ----
#include <vector>

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

int main(int argc, char *argv[])
{
    #include "postProcess.H"

    // ---- OF2412: Root case setup ----
    // In OF6: setRootCaseLists.H was sufficient
    // In OF2412: needs setRootCase.H for the new argument handling
    #include "setRootCase.H"
    #include "createTime.H"

    // ---- OF2412: Create dynamic mesh ----
    // In OF6: #include "createDynamicFvMesh.H" called dynamicFvMesh::New(runTime)
    // In OF2412: dynamicFvMesh::New(args, runTime) - needs args parameter
    #include "createDynamicFvMesh.H"

    #include "initContinuityErrs.H"

    // ---- OF2412: PIMPLE controls ----
    // In OF6: #include "createDyMControls.H" which included pimpleControl.H
    // In OF2412: createDyMControls.H includes pimpleControl.H via defines
    #include "createDyMControls.H"

    // ---- Ray-tracing setup ----
    // Finds unique X/Y/Z coordinates for the Goldak heat source ray-tracing
    Info<< "\nFinding Number of Unique X co-ordinates for Ray-Tracing\n" << endl;
    #include "uniqueX.H"

    // ---- Field initialization ----
    // Creates all fields: U, Temperature, alpha.phase1, p_rgh, and derived fields
    #include "createFields.H"

    // ---- OF2412: Alpha fluxes and phi correction ----
    // createAlphaFluxes.H initializes the face flux for VOF advection
    #include "createAlphaFluxes.H"

    // ---- OF2412: Initialize phi correction ----
    // initCorrectPhi.H sets up the face flux correction for moving meshes
    // In OF2412, this uses CorrectPhi() with rAU as tmp<volScalarField>
    #include "initCorrectPhi.H"

    // ---- OF2412: Uf (face velocity) for ALE meshes ----
    // createUfIfPresent.H creates the face velocity field if mesh motion is enabled
    // In OF2412, this is used with the new dynamicFvMesh interface
    #include "createUfIfPresent.H"

    // ---- OF2412: Validate turbulence model ----
    // In OF6: turbulence->validate() was called
    // In OF2412: validate() is removed; the model is validated during construction
    // We keep this comment to document the change

    // ---- Initial Courant number and time step ----
    if (!LTS)
    {
        #include "CourantNo.H"
        #include "setInitialDeltaT.H"
    }

    // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //
    Info<< "\nStarting time loop\n" << endl;

    while (runTime.run())
    {
        // ---- Read solver controls ----
        // readControls.H reads the MELTING dict from fvSolution:
        //   - Heat source parameters (HS_a, HS_Q, HS_velocity, etc.)
        //   - Temperature convergence criteria
        //   - Damper switch for oscillation damping
        #include "readControls.H"

        // ---- OF2412: Read dynamic mesh controls ----
        // readDyMControls.H reads mesh motion controls (correctPhi, meshCourantNo, etc.)
        #include "readDyMControls.H"

        // ---- Time step control ----
        if (LTS)
        {
            #include "setRDeltaT.H"
        }
        else
        {
            // ---- Standard Courant number check ----
            #include "CourantNo.H"

            // ---- Alpha (VOF) Courant number check ----
            // alphaCourantNo.H computes the Courant number for the VOF equation
            #include "alphaCourantNo.H"

            // ---- Adaptive time step ----
            // setDeltaT.H adjusts deltaT based on maxCo and maxAlphaCo
            #include "setDeltaT.H"
        }

        runTime++;

        Info<< "Time = " << runTime.timeName() << nl << endl;

        // --- Pressure-velocity PIMPLE corrector loop ---
        while (pimple.loop())
        {
            // ---- Mesh motion (if enabled) ----
            if (pimple.firstIter() || moveMeshOuterCorrectors)
            {
                mesh.update();

                if (mesh.changing())
                {
                    // Do not apply previous time-step mesh compression flux
                    // if the mesh topology changed
                    if (mesh.topoChanging())
                    {
                        talphaPhi1Corr0.clear();
                    }

                    // ---- OF2412: Update gravity with new mesh ----
                    // In OF6: gh = (g & mesh.C()) - ghRef; (g was uniformDimensionedVectorField)
                    // In OF2412: g is meshObjects::gravity, same math but different API
                    gh = (g & mesh.C()) - ghRef;
                    ghf = (g & mesh.Cf()) - ghRef;

                    MRF.update();

                    if (correctPhi)
                    {
                        // Calculate absolute flux from the mapped surface velocity
                        phi = mesh.Sf() & Uf();

                        // ---- OF2412: Correct phi for mesh motion ----
                        // correctPhiLocal.H calls CorrectPhi() from finiteVolume library
                        // In OF2412, rAU is computed as tmp<volScalarField>
                        #include "correctPhiLocal.H"

                        // Make the flux relative to the mesh motion
                        fvc::makeRelative(phi, U);

                        mixture.correct();
                    }

                    if (checkMeshCourantNo)
                    {
                        #include "meshCourantNo.H"
                    }
                }
            }

            // ---- VOF alpha equation ----
            // alphaControls.H reads nAlphaCorr, nAlphaSubCycles, cAlpha from fvSolution
            #include "alphaControls.H"

            // ---- Alpha equation with MULES sub-cycling ----
            // alphaEqnSubCycle.H advects the VOF field using MULES (Multidimensional
            // Universal Limiter with Explicit Solution) for boundedness
            #include "alphaEqnSubCycle.H"

            // ---- Update material properties ----
            // UpdateProps.H recomputes kappa, cp, beta, rhok, epsilon1, etc.
            // based on the current temperature and phase fraction fields
            #include "UpdateProps.H"

            // ---- Compute heat source term ----
            // DivergingOscillatingGaussian.H computes the Goldak-style heat source:
            //   - Diverging Gaussian beam profile
            //   - Optional oscillation (amplitude, frequency)
            //   - Travel speed and power ramp
            //   - Ray-tracing for 3D deposition
            #include "DivergingOscillatingGaussian.H"

            mixture.correct();

            // ---- Momentum equation ----
            // UEqn.H solves:
            //   - Inertial terms (ddt(rho,U) + div(rho*phi,U))
            //   - Viscous diffusion (laplacian(mu,U))
            //   - Surface tension (Marangoni force)
            //   - Vapor recoil pressure
            //   - Darcy damping in mushy zone
            #include "UEqn.H"

            // ---- Energy equation ----
            // TEqn.H solves:
            //   - Inertial terms (ddt(rho*cp,T) + div(rho*cp*phi,T))
            //   - Thermal diffusion (laplacian(kappa,T))
            //   - Latent heat source
            //   - Viscous dissipation
            //   - Volumetric heat source (Qv from Goldak)
            #include "TEqn.H"

            // --- Pressure corrector loop ---
            while (pimple.correct())
            {
                // ---- Pressure equation ----
                // pEqn.H solves for p_rgh with:
                //   - Surface tension pressure
                //   - Vapor recoil pressure
                //   - Continuity constraint
                #include "pEqn.H"
            }

            // ---- Turbulence correction ----
            // For laminar flow, this is a no-op. For turbulent cases,
            // this updates the turbulence fields (k, epsilon, omega, etc.)
            if (pimple.turbCorr())
            {
                turbulence->correct();
            }
        }

        // ---- Write output ----
        runTime.write();

        Info<< "ExecutionTime = " << runTime.elapsedCpuTime() << " s"
            << "  ClockTime = " << runTime.elapsedClockTime() << " s"
            << nl << endl;
    }

    Info<< "End\n" << endl;

    return 0;
}


// ************************************************************************* //
