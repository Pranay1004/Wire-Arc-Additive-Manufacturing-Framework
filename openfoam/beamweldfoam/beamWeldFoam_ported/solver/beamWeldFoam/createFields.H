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
    Field initialization for beamWeldFoam solver.
    Creates all required and derived fields for the two-phase melting simulation.

    Key OF6 -> OF2412 changes:
        - incompressibleInterPhaseTransportModel replaces turbulenceModel::New
        - meshObjects::gravity replaces uniformDimensionedVectorField for g
        - readhRef uses mesh.thisDb() instead of runTime
        - rho.oldTime() needed for ddt(rho,U) in OF2412
        - dimensionSet() replaces dimSet()

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

// ---- LTS (local time stepping) support ----
// createRDeltaT.H sets up the local time stepping field if LTS is enabled
#include "createRDeltaT.H"

// ---- Interface normal length scale ----
// deltaN is used for interface sharpening in the VOF equation
// It scales with the average cell size: deltaN = 1e-8 / V^(1/3)
const dimensionedScalar deltaN=1e-8/pow(average(mesh.V()), 1.0/3.0);

// ========================================================================
// PRIMARY FIELDS (read from 0/ directory)
// ========================================================================

// ---- Pressure field (minus hydrostatic) ----
// p_rgh = p - rho*gh, where p is the total pressure
// This formulation removes the hydrostatic pressure to improve convergence
Info<< "Reading field p_rgh\n" << endl;
volScalarField p_rgh
(
    IOobject
    (
        "p_rgh",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::AUTO_WRITE
    ),
    mesh
);

// ---- Velocity field ----
// U is the fluid velocity [m/s]
// In the mushy zone, velocity is damped by the Darcy term
Info<< "Reading field U\n" << endl;
volVectorField U
(
    IOobject
    (
        "U",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::AUTO_WRITE
    ),
    mesh
);

// ---- Face flux field ----
// phi = face interpolate(U) dot Sf, used for divergence terms
#include "createPhi.H"

// ========================================================================
// TWO-PHASE MIXTURE AND TRANSPORT PROPERTIES
// ========================================================================

Info<< "Reading transportProperties\n" << endl;

// ---- immiscibleIncompressibleTwoPhaseMixture ----
// Creates the two-phase mixture model from transportProperties
// phase1 = liquid/solid (the metal), phase2 = gas (ambient)
immiscibleIncompressibleTwoPhaseMixture mixture(U, phi);

// ---- Phase fraction fields ----
// alpha1 = volume fraction of phase1 (liquid/solid metal)
// alpha2 = 1 - alpha1 (gas phase)
volScalarField& alpha1(mixture.alpha1());
volScalarField& alpha2(mixture.alpha2());

// ---- Phase densities ----
// rho1 = density of liquid/solid metal [kg/m^3]
// rho2 = density of gas phase [kg/m^3]
const dimensionedScalar& rho1 = mixture.rho1();
const dimensionedScalar& rho2 = mixture.rho2();

// ---- Transport properties dictionary ----
// Reads from constant/transportProperties
IOdictionary transportProperties
(
    IOobject
    (
        "transportProperties",
        runTime.constant(),
        mesh,
        IOobject::MUST_READ_IF_MODIFIED,
        IOobject::NO_WRITE
    )
);

// ---- Phase property sub-dictionaries ----
dictionary phase1 = transportProperties.subDict("phase1");
dictionary phase2 = transportProperties.subDict("phase2");

// ========================================================================
// MATERIAL PROPERTIES (temperature-dependent via UpdateProps.H)
// ========================================================================

// ---- Specific heat capacity ----
// cp1 = liquid specific heat [J/(kg K)]
// cp2 = gas specific heat [J/(kg K)]
dimensionedScalar cp1("cp1",dimensionSet(0, 2, -2, -1, 0),phase1.lookup("cp"));
dimensionedScalar cp2("cp2",dimensionSet(0, 2, -2, -1, 0),phase2.lookup("cp"));

// ---- Solid specific heat ----
// cp1solid = solid specific heat [J/(kg K)]
// Used when temperature < Tsolidus
dimensionedScalar cp1solid("cp1solid",dimensionSet(0, 2, -2, -1, 0),phase1.lookup("cpsolid"));
dimensionedScalar cp2solid("cp2solid",dimensionSet(0, 2, -2, -1, 0),phase2.lookup("cpsolid"));

// ---- Thermal conductivity ----
// kappa1 = liquid thermal conductivity [W/(m K)]
// kappa2 = gas thermal conductivity [W/(m K)]
dimensionedScalar kappa1("kappa1",dimensionSet(1, 1, -3, -1, 0),phase1.lookup("kappa"));
dimensionedScalar kappa2("kappa2",dimensionSet(1, 1, -3, -1, 0),phase2.lookup("kappa"));

// ---- Solid thermal conductivity ----
// kappasolid = solid thermal conductivity [W/(m K)]
// Used when temperature < Tsolidus
dimensionedScalar kappa1solid("kappa1solid",dimensionSet(1, 1, -3, -1, 0),phase1.lookup("kappasolid"));
dimensionedScalar kappa2solid("kappa2solid",dimensionSet(1, 1, -3, -1, 0),phase2.lookup("kappasolid"));

// ---- Phase change temperatures ----
// Tsolidus = temperature below which material is fully solid [K]
// Tliquidus = temperature above which material is fully liquid [K]
// Between Tsolidus and Tliquidus: mushy zone (partial melting)
dimensionedScalar Tsolidus1("Tsolidus1",dimensionSet(0, 0, 0, 1, 0),phase1.lookup("Tsolidus"));
dimensionedScalar Tsolidus2("Tsolidus2",dimensionSet(0, 0, 0, 1, 0),phase2.lookup("Tsolidus"));

dimensionedScalar Tliquidus1("Tliquidus1",dimensionSet(0, 0, 0, 1, 0),phase1.lookup("Tliquidus"));
dimensionedScalar Tliquidus2("Tliquidus2",dimensionSet(0, 0, 0, 1, 0),phase2.lookup("Tliquidus"));

// ---- Latent heat of fusion ----
// LatentHeat = energy absorbed/released during phase change [J/kg]
// Used in the energy equation as a source term
dimensionedScalar LatentHeat1("LatentHeat1",dimensionSet(0, 2, -2, 0, 0),phase1.lookup("LatentHeat"));
dimensionedScalar LatentHeat2("LatentHeat2",dimensionSet(0, 2, -2, 0, 0),phase2.lookup("LatentHeat"));

// ---- Thermal expansion coefficient ----
// beta = volumetric thermal expansion coefficient [1/K]
// Used for Boussinesq approximation in natural convection
dimensionedScalar beta1("beta1",dimensionSet(0, 0, 0, -1, 0),phase1.lookup("beta"));
dimensionedScalar beta2("beta2",dimensionSet(0, 0, 0, -1, 0),phase2.lookup("beta"));

// ========================================================================
// SURFACE TENSION AND EVAPORATION PROPERTIES
// ========================================================================

// ---- Marangoni coefficient ----
// dsigmadT = d(sigma)/dT [N/(m K)]
// Negative value means surface tension decreases with temperature
// This drives flow from hot (low sigma) to cold (high sigma) regions
dimensionedScalar Marangoni_Constant("Marangoni_Constant",dimensionSet(1, 0, -2, -1, 0),transportProperties.lookup("dsigmadT"));

// ---- Reference pressure ----
// p0 = ambient pressure [Pa]
dimensionedScalar p0("p0",dimensionSet(1,-1,-2,0,0,0,0),transportProperties.lookup("p0"));

// ---- Vaporization temperature ----
// Tvap = temperature at which significant evaporation occurs [K]
dimensionedScalar Tvap("Tvap",dimensionSet(0, 0, 0, 1, 0),transportProperties.lookup("Tvap"));

// ---- Molar mass ----
// Mm = molar mass of the metal [kg/mol]
// Used in the Clausius-Clapeyron equation for vapor pressure
dimensionedScalar Mm("Mm",dimensionSet(1, 0, 0, 0, -1),transportProperties.lookup("Mm"));

// ---- Latent heat of vaporization ----
// LatentHeatVap = energy for liquid-to-gas phase change [J/kg]
dimensionedScalar LatentHeatVap("LatentHeatVap",dimensionSet(0, 2, -2, 0, 0),transportProperties.lookup("LatentHeatVap"));

// ---- Universal gas constant ----
// R = 8.314 J/(mol K), used in Clausius-Clapeyron equation
dimensionedScalar R ("R", dimensionSet(1,2,-2,-1,-1,0,0),8.314);

// ========================================================================
// COMPUTED FIELDS (updated each timestep)
// ========================================================================

// ---- Effective specific heat ----
// cp = alpha1*cp1 + alpha2*cp2 [J/(kg K)]
// Blended between phases based on volume fraction
volScalarField cp
(
    IOobject
    (
        "cp",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("cp",dimensionSet(0, 2, -2, -1, 0),0.0)
);
cp=alpha1*cp1 + alpha2*cp2;

// ---- Effective thermal conductivity ----
// kappa = alpha1*kappa1 + alpha2*kappa2 [W/(m K)]
// Blended between phases based on volume fraction
volScalarField kappa
(
    IOobject
    (
        "kappa",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("kappa",dimensionSet(1, 1, -3, -1, 0),0.0)
);
kappa=alpha1*kappa1 + alpha2*kappa2;

// ---- Temperature field ----
// Temperature = fluid temperature [K]
// This is the primary thermal field, solved by TEqn.H
Info<< "Reading field Temperature\n" << endl;
volScalarField Temperature
(
    IOobject
    (
        "Temperature",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::AUTO_WRITE
    ),
    mesh
);

// ---- Solidus temperature field ----
// TSolidus = phase-weighted solidus temperature [K]
// Updated in UpdateProps.H based on alpha1
volScalarField TSolidus
(
    IOobject
    (
        "TSolidus",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("TSolidus",dimensionSet(0, 0, 0, 1, 0),0.0)
);
TSolidus=alpha1*Tsolidus1 + alpha2*Tsolidus2;

// ---- Liquidus temperature field ----
// TLiquidus = phase-weighted liquidus temperature [K]
// Updated in UpdateProps.H based on alpha1
volScalarField TLiquidus
(
    IOobject
    (
        "TLiquidus",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("TLiquidus",dimensionSet(0, 0, 0, 1, 0),1.0)
);
TLiquidus=alpha1*Tliquidus1 + alpha2*Tliquidus2;

// ---- Darcy coefficient ----
// DC = permeability coefficient for mushy zone damping [kg/(m^3 s)]
// High DC = strong damping (solid), low DC = no damping (liquid)
// Default 1e14 is typical for metal solidification
volScalarField DC
(
    IOobject
    (
        "DC",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("DC",dimensionSet(1,-3,-1,0,0),1.0e14)
);

// ---- Phase fraction for viscosity blending ----
// epsilon1 = max(min((T - Tsolidus)/(Tliquidus - Tsolidus), 1), 0)
// epsilon1 = 0 in solid, 1 in liquid
// Used to blend viscosity: mu_eff = mu * max(epsilon1, 1e-4)
volScalarField epsilon1
(
    IOobject
    (
        "epsilon1",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("epsilon1",dimensionSet(0,0,0,0,0),0.0)
);
epsilon1=max(min((Temperature-TSolidus)/(TLiquidus-TSolidus),scalar(1)),scalar(0));

// ---- Interface normal vector ----
// nneps1 = normalized gradient of epsilon1
// Used for interface tracking and surface tension calculation
volVectorField nneps1
(
    IOobject
    (
        "nneps1",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
        mesh,
         dimensionedVector("nneps1",dimensionSet(0, 0, 0, 0, 0),vector::zero)
);

// ---- Epsilon1 mask ----
// epsilon1mask = binary mask for epsilon1 (0 or 1)
// Used in fvSchemes for boundedness of alpha equation
volScalarField epsilon1mask
(
    IOobject
    (
        "epsilon1mask",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("epsilon1mask",dimensionSet(0,0,0,0,0),0.0)
);

// ---- Temperature gradient ----
// gradT = gradient of Temperature [K/m]
// Used for Marangoni force calculation
volVectorField gradT
(
    IOobject
    (
        "gradT",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedVector("gradT",dimensionSet(0, -1, 0, 1, 0),vector::zero)
);

// ---- Latent heat field ----
// LatentHeat = phase-weighted latent heat [J/kg]
// Updated in UpdateProps.H based on alpha1
volScalarField LatentHeat
(
    IOobject
    (
        "LatentHeat",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("LatentHeat",dimensionSet(0, 2, -2, 0, 0),0.0)
);
LatentHeat=alpha1*LatentHeat1 + alpha2*LatentHeat2;

// ========================================================================
// RAY-TRACING COORDINATE FIELDS
// ========================================================================

// ---- X-coordinate of cell centers ----
// xcoord = x-component of cell center position [m]
// Used for 3D heat source ray-tracing
volScalarField xcoord
(
    IOobject
    (
        "xcoord",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("xcoord", dimensionSet(0, 1, 0, 0, 0), 0.0)
);

// ---- Z-coordinate of cell centers ----
// zcoord = z-component of cell center position [m]
// Used for 3D heat source ray-tracing
volScalarField zcoord
(
    IOobject
    (
        "zcoord",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
        mesh,
         dimensionedScalar("zcoord", dimensionSet(0, 1, 0, 0, 0), 0.0)
);

// ---- Cell dimension fields ----
// xDim, yDim, zDim = cell dimensions in each direction [m]
// Used for volume-based heat source deposition
volScalarField yDim
(
    IOobject
    (
        "yDim",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("yDim", dimensionSet(0, 1, 0, 0, 0), 1.0)
);

volScalarField xDim
(
    IOobject
    (
        "xDim",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("xDim", dimensionSet(0, 1, 0, 0, 0), 1.0)
);

volScalarField zDim
(
    IOobject
    (
        "zDim",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("zDim", dimensionSet(0, 1, 0, 0, 0), 1.0)
);

// ---- Compute cell coordinates and dimensions ----
// Loop over all cells to extract x/z coordinates and cell dimensions
// These are used by DivergingOscillatingGaussian.H for heat source calculation
const faceList & ff = mesh.faces();
const pointField & pp = mesh.points();

forAll( mesh.C(), celli)
{
    vector XYZ = mesh.C()[celli];
    xcoord[celli]=XYZ.x();
    zcoord[celli]=XYZ.z();

    const cell & cc = mesh.cells()[celli];
    labelList pLabels(cc.labels(ff));
    pointField pLocal(pLabels.size(), vector::zero);

    forAll (pLabels, pointi)
    {
        pLocal[pointi] = pp[pLabels[pointi]];
    }

    xDim[celli] = Foam::max(pLocal & vector(1,0,0)) - Foam::min(pLocal & vector(1,0,0));
    yDim[celli] = Foam::max(pLocal & vector(0,1,0)) - Foam::min(pLocal & vector(0,1,0));
    zDim[celli] = Foam::max(pLocal & vector(0,0,1)) - Foam::min(pLocal & vector(0,0,1));
}

xDim.correctBoundaryConditions();
yDim.correctBoundaryConditions();
zDim.correctBoundaryConditions();

// ---- Cell cross-sectional area ----
// cellarea = xDim * zDim [m^2]
// Used for 2D heat source normalization
volScalarField cellarea
(
    IOobject
    (
        "cellarea",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
        mesh,
         dimensionedScalar("cellarea", dimensionSet(0, 2, 0, 0, 0), 0.0)
);

forAll( mesh.C(), celli)
{
    cellarea[celli]=(xDim[celli]*zDim[celli]);
}

cellarea.correctBoundaryConditions();

// ========================================================================
// SOURCE TERMS AND DIAGNOSTIC FIELDS
// ========================================================================

// ---- Combined source term ----
// sourceTerm = momentum source from surface tension + recoil pressure [Pa/m]
volScalarField sourceTerm
(
    IOobject
    (
        "sourceTerm",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("sourceTerm",dimensionSet(1, -1, -3, 0, 0),scalar(0.0))
);
sourceTerm.write();

// ---- Temperature RHS for convergence ----
// TRHS = right-hand side of temperature equation [K/s]
// Used for temperature convergence checking in MELTING loop
volScalarField TRHS
(
    IOobject
    (
        "TRHS",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("TRHS",dimensionSet(1, -1, -3, 0, 0),scalar(0.0))
);
TRHS.write();

// ---- Temperature correction ----
// Tcorr = temperature correction for iterative convergence [K]
volScalarField Tcorr
(
    IOobject
    (
        "Tcorr",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("Tcorr",dimensionSet(0, 0, 0, 1, 0),0.0)
);

// ---- Thermal expansion coefficient ----
// beta = phase-weighted thermal expansion [1/K]
// Used in Boussinesq approximation for natural convection
volScalarField beta
(
    IOobject
    (
        "beta",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("beta",dimensionSet(0, 0, 0, -1, 0),0.0)
);
beta=alpha1*beta1 + alpha2*beta2;

// ---- Normalized density ----
// rhok = rho/rhoRef (used in pressure equation)
volScalarField rhok
(
    IOobject
    (
        "rhok",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("rhok",dimensionSet(0,0,0,0,0),0.0)
);

// ========================================================================
// DENSITY AND MASS FLUX
// ========================================================================

// ---- Density field ----
// rho = alpha1*rho1 + alpha2*rho2 [kg/m^3]
// oldTime() is needed for OF2412's ddt(rho,U) formulation
volScalarField rho
(
    IOobject
    (
        "rho",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT
    ),
    alpha1*rho1 + alpha2*rho2
);
rho.oldTime();

// ---- Mass flux ----
// rhoPhi = rho * phi [kg/s]
// Used for mass-conservative advection of momentum and energy
surfaceScalarField rhoPhi
(
    IOobject
    (
        "rhoPhi",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    fvc::interpolate(rho)*phi
);

// ========================================================================
// PHYSICS SOURCE TERMS
// ========================================================================

// ---- Viscous dissipation ----
// ViscousDissipation = mu * (grad U : grad U^T) [W/m^3]
// Converts kinetic energy to heat in high-shear regions
volScalarField ViscousDissipation
(
    IOobject
    (
        "ViscousDissipation",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
        mesh,
        dimensionedScalar("ViscousDissipation",dimensionSet(1, -1, -3, 0, 0),scalar(0.0))
);

// ---- Beam intensity profile ----
// BeamProfile = normalized beam intensity [W/m^3]
// Computed by DivergingOscillatingGaussian.H
volScalarField BeamProfile
(
    IOobject
    (
        "BeamProfile",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
        mesh,
        dimensionedScalar("BeamProfile",dimensionSet(1, -1, -3, 0, 0),scalar(0.0))
);

// ---- Divergence of velocity (diagnostic) ----
// Num_divU = div(U) [1/s]
// Should be zero for incompressible flow; used for debugging
volScalarField Num_divU
(
    IOobject
    (
        "Num_divU",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("Num_divU",dimensionSet(0,0,-1,0,0),0.0)
);

// ---- Marangoni force ----
// Marangoni = dsigmadT * gradT [N/m^3]
// Surface tension gradient drives flow along the interface
volVectorField Marangoni
(
    IOobject
    (
        "Marangoni",
        runTime.timeName(),
        mesh,
        IOobject::READ_IF_PRESENT,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedVector("Marangoni",dimensionSet(1, -2, -2, 0, 0),vector::zero)
);

// ---- Vapor recoil pressure ----
// pVap = Clausius-Clapeyron vapor pressure [Pa]
// Computed from Temperature using the Clausius-Clapeyron equation
volScalarField pVap
(
    IOobject
    (
        "pVap",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("0", dimensionSet(1,-1,-2,0,0,0,0), 0.0)
);

// ---- Volumetric heat source ----
// Qv = heat source from beam [W/m^3]
// Computed by DivergingOscillatingGaussian.H
volScalarField Qv
(
    IOobject
    (
        "Qv",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("0", dimensionSet(1,0,-3,0,0,0,0), 0.0)
);

// ========================================================================
// OF2412: TURBULENCE MODEL
// ========================================================================

// ---- Inter-phase transport model ----
// In OF6, this was: turbulenceModel::New(U, phi, laminarTransport)
// In OF2412, this is: incompressibleInterPhaseTransportModel<ImmTurbModel>
// This wraps the turbulence model for two-phase flows
// For laminar flow, this is a Stokes (zero-viscosity) model
typedef incompressibleInterPhaseTransportModel
    <
        immiscibleIncompressibleTwoPhaseMixture
    > transportModelType;

autoPtr<transportModelType> turbulence
(
    new transportModelType
    (
        rho, U, phi, rhoPhi, mixture
    )
);

// ========================================================================
// GRAVITY AND HYDROSTATIC PRESSURE
// ========================================================================

// ---- OF2412: Read gravitational acceleration ----
// In OF6: read from uniformDimensionedVectorField g (IOobject with runTime)
// In OF2412: read from meshObjects::gravity (IOobject with mesh.thisDb())
#include "readGravitationalAcceleration.H"

// ---- OF2412: Read reference height for hydrostatic pressure ----
// In OF6: read from uniformDimensionedScalarField hRef (IOobject with runTime)
// In OF2412: read from IOdictionary on mesh.thisDb()
#include "readhRef.H"

// ---- Compute g*h field ----
// gh = (g & mesh.C()) - ghRef [m^2/s^2]
// Used to compute hydrostatic pressure: p_hydro = rho*gh
#include "gh.H"

// ---- Update material properties based on current temperature ----
// UpdateProps.H recomputes kappa, cp, beta, rhok, epsilon1, gradT, etc.
#include "UpdateProps.H"

// ========================================================================
// PRESSURE FIELD AND REFERENCE CELL
// ========================================================================

// ---- Total pressure field ----
// p = p_rgh + rho*gh [Pa]
volScalarField p
(
    IOobject
    (
        "p",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    p_rgh + rho*gh
);

// ---- Reference cell for pressure ----
// pRefCell and pRefValue fix the pressure at one cell to remove the
// null space of the pressure equation (pressure is determined up to a constant)
label pRefCell = 0;
scalar pRefValue = 0.0;
setRefCell
(
    p,
    p_rgh,
    pimple.dict(),
    pRefCell,
    pRefValue
);

if (p_rgh.needReference())
{
    p += dimensionedScalar
    (
        "p",
        p.dimensions(),
        pRefValue - getRefCellValue(p, pRefCell)
    );
    p_rgh = p - rho*gh;
}

// ---- Mark fields for flux computation ----
mesh.setFluxRequired(p_rgh.name());
mesh.setFluxRequired(alpha1.name());

// ========================================================================
// MRF AND FV OPTIONS
// ========================================================================

// ---- OF2412: MRF (Multiple Reference Frame) ----
// createMRF.H sets up the MRF zones for rotating reference frames
// Not used in beamWeldFoam but required for compilation
#include "createMRF.H"

// ---- OF2412: Finite volume options ----
// createFvOptions.H sets up fvOptions for source terms
// Can be used for additional physics (e.g., heating, damping)
#include "createFvOptions.H"

// ========================================================================
// ADDITIONAL FIELDS
// ========================================================================

// ---- Rate of change of epsilon1 ----
// ddte1 = d(epsilon1)/dt [1/s]
// Used for boundedness of the phase fraction field
volScalarField ddte1
(
    IOobject
    (
        "ddte1",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::AUTO_WRITE
    ),
    mesh,
    dimensionedScalar("ddte1",dimensionSet(0,0,-1,0,0),0.0),
    zeroGradientFvPatchScalarField::typeName
);

// ---- Damper field ----
// damper = oscillation damping factor [0-1]
// Reduces oscillation amplitude over time if damperSwitch=true
volScalarField damper
(
    IOobject
    (
        "damper",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("damper",dimless,1.0),
    zeroGradientFvPatchScalarField::typeName
);

// ---- Thermal damper field ----
// thermalDamper = temperature damping factor [0-1]
// Used for thermal oscillation damping
volScalarField thermalDamper
(
    IOobject
    (
        "thermalDamper",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        IOobject::NO_WRITE
    ),
    mesh,
    dimensionedScalar("thermalDamper",dimless,1.0),
    zeroGradientFvPatchScalarField::typeName
);
