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
    Goldak-style diverging oscillating Gaussian heat source model for
    beamWeldFoam.

    Implements the double-ellipsoidal heat source model originally proposed
    by Goldak et al. (1984) for arc/laser/electron beam welding simulation.

    The heat source is a diverging Gaussian that:
        - Travels along the z-axis at velocity HS_velocity
        - Has a Gaussian distribution in x and z directions
        - Diverges (widens) with depth (y-direction)
        - Can oscillate sinusoidally in the x-direction
        - Has optional power ramp (Q_ramp_rate) and time shift (tshift)
        - Has optional focus shift (foc_shift_vel)

    Parameters (from system/fvSolution, MELTING dict):
        HS_a              [m]        Beam radius at focus
        HS_Q              [W]        Total beam power
        HS_bg             [m]        Background Gaussian offset (x-direction)
        HS_velocity       [m/s]      Beam travel speed (z-direction)
        HS_lg             [m]        Large Gaussian offset (z-direction)
        HS_deposition_cutoff [-]     Alpha cutoff for deposition (0-1)
        Oscillation_Amplitude [m]    Beam oscillation amplitude
        Oscillation_Frequency [Hz]   Beam oscillation frequency
        Y_R               [-]        Y/R ratio for beam divergence
        focY              [m]        Y focus position
        foc_shift_vel     [m/s]      Focus shift velocity

    Original authors:
        Thomas F. Flint, University of Manchester
        Gowthaman Parivendhan, University College Dublin
        Alojz Ivankovic, University College Dublin
        Michael C. Smith, University of Manchester
        Philip Cardiff, University College Dublin

    OpenFOAM 2412 port by:
        Pranay K. Pandey, Indian Institute of Space Science & Technology, Trivandrum
        github.com/Pranay1004
        Q_ramp_rate       [W/s]      Power ramp rate
        tshift            [s]        Time shift for power ramp

    Algorithm:
        1. For each ray (x,z), find the first cell where alpha1 > cutoff
        2. Compute the Goldak heat source at that cell
        3. sourceTerm = Q / (yDim * pi * a_eff^2) * exp(-2*(x^2+z^2)/a_eff^2)
        4. a_eff = a * sqrt(1 + ((y-foc)/Y_R)^2) (diverging beam)

\*---------------------------------------------------------------------------*/

{
    // ========================================================================
    // HEAT SOURCE PARAMETERS
    // ========================================================================

    // ---- Mathematical constant ----
    const dimensionedScalar pi = constant::mathematical::pi;

    // ---- Beam parameters (with dimensions) ----
    // a_cond = beam radius at focus [m]
    // b_g = background Gaussian offset in x [m]
    // v_arc = beam travel speed in z [m/s]
    // Q_cond = total beam power [W]
    // lg = large Gaussian offset in z [m]
    dimensionedScalar a_cond("a_cond",dimensionSet(0, 1, 0, 0, 0),HS_a);
    dimensionedScalar b_g("b_g",dimensionSet(0, 1, 0, 0, 0),HS_bg);
    dimensionedScalar v_arc("v_arc",dimensionSet(0, 1, -1, 0, 0),HS_velocity);
    dimensionedScalar Q_cond("Q_cond",dimensionSet(1, 2, -3, 0, 0),HS_Q);
    dimensionedScalar lg("lg",dimensionSet(0, 1, 0, 0, 0),HS_lg);

    // ---- Current simulation time ----
    dimensionedScalar time("time",dimensionSet(0, 0, 1, 0, 0),runTime.time().value());

    // ---- Oscillation parameters ----
    // Osc_Amp = oscillation amplitude in x [m]
    // Osc_freq = oscillation frequency [Hz]
    dimensionedScalar Osc_Amp("Osc_Amp",dimensionSet(0, 1, 0, 0, 0),Oscillation_Amplitude);
    dimensionedScalar Osc_freq("Osc_freq",dimensionSet(0, 0, -1, 0, 0),Oscillation_Frequency);

    // ========================================================================
    // READ ADDITIONAL PARAMETERS FROM MELTING DICT
    // ========================================================================

    // ---- Reset source term to zero ----
    sourceTerm*=0.0;

    // ---- Y/R ratio ----
    // Controls how fast the beam diverges with depth
    // Y_R -> 0: beam stays narrow (pencil beam)
    // Y_R -> inf: beam diverges quickly (wide conical beam)
    scalar Y_R(readScalar(meltingDict.lookup("Y_R")));

    // ---- Y focus position ----
    // focY = y-coordinate of the beam focus [m]
    scalar focY(readScalar(meltingDict.lookup("focY")));

    // ---- Focus shift velocity ----
    // foc_shift_vel = rate of focus change [m/s]
    // Positive = focus moves upward, negative = focus moves downward
    scalar foc_shift_vel(readScalar(meltingDict.lookup("foc_shift_vel")));

    // ---- Power ramp rate ----
    // Q_ramp_rate = rate of power decrease [W/s]
    // Power = max(Q - Q_ramp_rate*(t - tshift), 0)
    scalar Q_ramp_rate(readScalar(meltingDict.lookup("Q_ramp_rate")));

    // ---- Time shift ----
    // tshift = time at which power ramp starts [s]
    // Before tshift: full power, after tshift: power decreases
    scalar tshift(readScalar(meltingDict.lookup("tshift")));

    // ========================================================================
    // RAY-TRACING HEAT DEPOSITION
    // ========================================================================

    // ---- Ray counter ----
    int Rayn=0;

    // ---- Loop over all rays (x, y, z) ----
    // For each (x,z) ray, find the first cell where alpha1 > cutoff
    // This is the "surface" where the beam hits
    for(int z_ray=0;z_ray<num_unique_z_coords;z_ray++)
    {
        for(int x_ray=0;x_ray<num_unique_x_coords;x_ray++)
        {
            // ---- Find the surface cell (minimum y where alpha1 > cutoff) ----
            double miny=1.0e6;

            for(int y_ray=0;y_ray<num_unique_y_coords;y_ray++)
            {
            point pnow(xlist[x_ray], ylist[y_ray], zlist[z_ray]);
            label cellpoint = mesh.findCell(pnow);

                // ---- Check if this cell is below the surface ----
                // alpha1 > cutoff means the cell is filled with liquid/solid
                // The first such cell (from top) is the surface
                if(alpha1[cellpoint]>HS_deposition_cutoff)
                {
                // HS_deposition_cutoff:
                //   0.99 for conduction mode (beam hits surface)
                //   0.01 for keyhole mode (beam penetrates deep)
                miny=std::min(miny,ylist[y_ray]);
                }
            }

            // ---- Get the surface cell ----
            point phit(xlist[x_ray], miny, zlist[z_ray]);
            label cellpointhit = mesh.findCell(phit);

            // ---- Compute heat source at surface cell ----
            if(yDim[cellpointhit]>1e-12)
                {
                    // ---- Apply time shift for power ramp ----
                    if(time.value()>tshift)
                    {
                    // ---- Dynamic focus and power ----
                    double focnow=(focY-(foc_shift_vel*(time.value()-tshift)));
                    double Qnow=max((Q_cond.value()-(Q_ramp_rate*(time.value()-tshift))),0.0);

                    // ---- Goldak heat source formula ----
                    // sourceTerm = Q / (yDim * pi * a_eff^2) * exp(-2*(dx^2+dz^2)/a_eff^2)
                    // a_eff = a * sqrt(1 + ((y-foc)/Y_R)^2)  (diverging beam)
                    // dx = x - bg - Osc_Amp*cos(2*pi*freq*t)  (oscillation in x)
                    // dz = z - v*t - lg  (travel in z)
                    sourceTerm[cellpointhit]=(1.0/yDim[cellpointhit])*((2.0*Qnow)/
                        ((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focnow)/Y_R),2.0)))*(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focnow)/Y_R),2.0)))*pi.value()))
                        *Foam::exp(-2.0*(
                        Foam::pow(((xcoord[cellpointhit]-b_g.value()-(Osc_Amp.value()*Foam::cos(2.0*pi.value()*Osc_freq.value()*time.value())))/((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focnow)/Y_R),2.0))))),2.0)
                        +Foam::pow((zcoord[cellpointhit]-(v_arc.value()*time.value())-lg.value())/(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focnow)/Y_R),2.0))),2.0)));
                    }

                    else
                    {
                    // ---- Before tshift: use initial focus and full power ----
                    sourceTerm[cellpointhit]=(1.0/yDim[cellpointhit])*((2.0*Q_cond.value())/
                        ((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focY)/Y_R),2.0)))*(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focY)/Y_R),2.0)))*pi.value()))
                        *Foam::exp(-2.0*(
                        Foam::pow(((xcoord[cellpointhit]-b_g.value()-(Osc_Amp.value()*Foam::cos(2.0*pi.value()*Osc_freq.value()*time.value())))/((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focY)/Y_R),2.0))))),2.0)
                        +Foam::pow((zcoord[cellpointhit]-(v_arc.value()*time.value())-lg.value())/(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((miny-focY)/Y_R),2.0))),2.0)));
                    }
                }
                Rayn+=1;
            }//End loop over all rays x
        }//End loop over all rays z


        sourceTerm.correctBoundaryConditions();

    // ========================================================================
    // BEAM PROFILE (FOR ALL CELLS)
    // ========================================================================

    // ---- Compute BeamProfile for visualization ----
    // BeamProfile = normalized beam intensity at each cell center
    // This is for post-processing only (not used in the equations)
                forAll(mesh.C(),celli)
                {
                vector XYZ = mesh.C()[celli];

                       if(time.value()>tshift)
                        {
                        double focnow=(focY-(foc_shift_vel*(time.value()-tshift)));
                        double Qnow=max((Q_cond.value()-(Q_ramp_rate*(time.value()-tshift))),0.0);

                        BeamProfile[celli]=((2.0*Qnow)/
            ((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focnow)/Y_R),2.0)))*(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focnow)/Y_R),2.0)))*pi.value()))
            *Foam::exp(-2.0*(
            Foam::pow(((XYZ.x()-b_g.value()-(Osc_Amp.value()*Foam::cos(2.0*pi.value()*Osc_freq.value()*time.value())))/((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focnow)/Y_R),2.0))))),2.0)
            +Foam::pow((XYZ.z()-(v_arc.value()*time.value())-lg.value())/(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focnow)/Y_R),2.0))),2.0)));
                        }
                        else
                        {
        BeamProfile[celli]=((2.0*Q_cond.value())/
            ((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focY)/Y_R),2.0)))*(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focY)/Y_R),2.0)))*pi.value()))
            *Foam::exp(-2.0*(
            Foam::pow(((XYZ.x()-b_g.value()-(Osc_Amp.value()*Foam::cos(2.0*pi.value()*Osc_freq.value()*time.value())))/((a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focY)/Y_R),2.0))))),2.0)
            +Foam::pow((XYZ.z()-(v_arc.value()*time.value())-lg.value())/(a_cond.value()*Foam::sqrt(1.0+Foam::pow(((XYZ.y()-focY)/Y_R),2.0))),2.0)));
                        }
                    }
                }
