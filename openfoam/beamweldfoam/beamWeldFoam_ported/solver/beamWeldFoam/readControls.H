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
    Read solver controls from system/fvSolution for beamWeldFoam.
    Reads the MELTING sub-dictionary which contains:
        - Temperature convergence parameters
        - Heat source parameters
        - Oscillation parameters
        - Damper switch

    Original authors:
        Thomas F. Flint, University of Manchester
        Gowthaman Parivendhan, University College Dublin
        Alojz Ivankovic, University College Dublin
        Michael C. Smith, University of Manchester
        Philip Cardiff, University College Dublin

    OpenFOAM 2412 port by:
        Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
        github.com/Pranay1004

    These are read at the start of each timestep and can be modified
    during the simulation.

\*---------------------------------------------------------------------------*/

// ---- Time step controls ----
// readTimeControls.H reads endTime, maxCo, maxAlphaCo, maxDeltaT from controlDict
#include "readTimeControls.H"

// ========================================================================
// MELTING DICT (from system/fvSolution)
// ========================================================================

// ---- Read the MELTING sub-dictionary ----
const dictionary& meltingDict = mesh.solutionDict().subDict("MELTING");

// ========================================================================
// TEMPERATURE CONVERGENCE PARAMETERS
// ========================================================================

// ---- Minimum temperature correctors ----
// minTCorr = minimum number of iterations in the temperature/epsilon1 loop
// Even if converged, at least this many iterations are performed
int minTCorr(readLabel(meltingDict.lookup("minTempCorrector")));

// ---- Maximum temperature correctors ----
// maxTCorr = maximum number of iterations in the temperature/epsilon1 loop
// Prevents infinite loops if the solution doesn't converge
int maxTCorr(readLabel(meltingDict.lookup("maxTempCorrector")));

// ---- Epsilon tolerance ----
// epsilonTol = convergence criterion for epsilon1 [dimensionless]
// Loop continues until max|eps_new - eps_old| < epsilonTol
dimensionedScalar epsilonTol(readScalar(meltingDict.lookup("epsilonTolerance")));

// ---- Epsilon relaxation ----
// epsilonRel = under-relaxation factor for epsilon1 update [0-1]
// epsilon1_new = epsilon1_old + epsilonRel * (epsilon1_calculated - epsilon1_old)
// Lower values = more stable but slower convergence
dimensionedScalar epsilonRel(readScalar(meltingDict.lookup("epsilonRelaxation")));

// ========================================================================
// HEAT SOURCE PARAMETERS
// ========================================================================

// ---- Beam radius at focus [m] ----
// HS_a = characteristic radius of the Gaussian beam
// Smaller = more concentrated beam, larger = more spread beam
scalar HS_a(readScalar(meltingDict.lookup("HS_a")));

// ---- Background Gaussian offset [m] ----
// HS_bg = offset of the beam center in the x-direction
// 0 = beam centered, non-zero = beam offset
scalar HS_bg(readScalar(meltingDict.lookup("HS_bg")));

// ---- Beam travel speed [m/s] ----
// HS_velocity = speed of the beam in the z-direction
// 0 = stationary beam, >0 = moving beam
scalar HS_velocity(readScalar(meltingDict.lookup("HS_velocity")));

// ---- Large Gaussian offset [m] ----
// HS_lg = offset of the beam in the z-direction
// 0 = beam at origin, non-zero = beam offset
scalar HS_lg(readScalar(meltingDict.lookup("HS_lg")));

// ---- Total beam power [W] ----
// HS_Q = total power of the heat source
// This is the integrated power over the Gaussian distribution
scalar HS_Q(readScalar(meltingDict.lookup("HS_Q")));

// ========================================================================
// DEPOSITION AND OSCILLATION PARAMETERS
// ========================================================================

// ---- Heat deposition cutoff [-] ----
// HS_deposition_cutoff = alpha1 threshold for heat deposition
// 0.99 = conduction mode (beam only hits surface cells with alpha1 > 0.99)
// 0.01 = keyhole mode (beam deposits heat deep into the melt pool)
scalar HS_deposition_cutoff(readScalar(meltingDict.lookup("HS_deposition_cutoff")));

// ---- Beam oscillation amplitude [m] ----
// Oscillation_Amplitude = amplitude of sinusoidal oscillation in x
// 0 = no oscillation, >0 = beam oscillates
scalar Oscillation_Amplitude(readScalar(meltingDict.lookup("Oscillation_Amplitude")));

// ---- Beam oscillation frequency [Hz] ----
// Oscillation_Frequency = frequency of sinusoidal oscillation
// x_oscillation = Oscillation_Amplitude * cos(2*pi*frequency*t)
scalar Oscillation_Frequency(readScalar(meltingDict.lookup("Oscillation_Frequency")));

// ---- Damper switch ----
// damperSwitch = enable/disable oscillation damping
// When true: damper = 2*rho/(rho1+rho2) damps velocity at the interface
// When false: damper = 1 (no damping)
bool damperSwitch = meltingDict.lookupOrDefault<bool>("damperSwitch", false);
