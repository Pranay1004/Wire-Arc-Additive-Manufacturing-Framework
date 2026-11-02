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
    Ray-tracing coordinate setup for beamWeldFoam.
    Finds unique x, y, z coordinates from the mesh cell centers.
    These are used by DivergingOscillatingGaussian.H for the ray-tracing
    algorithm that deposits heat along vertical rays.

    The ray-tracing algorithm:
        1. For each (x, z) ray, find all y-coordinates
        2. Starting from the top (smallest y), find the first cell
           where alpha1 > cutoff (the "surface" cell)
        3. Deposit heat at the surface cell according to the Goldak model

    This approach allows the heat source to follow the deforming surface
    as the metal melts and solidifies.

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

// ========================================================================
// COORDINATE EXTRACTION
// ========================================================================

// ---- Counters for unique coordinates ----
int num_unique_x_coords=0;
int num_unique_z_coords=0;
int num_unique_y_coords=0;

// ---- Tolerance for coordinate comparison ----
// Two coordinates are considered "unique" if they differ by more than this
double coord_tolerence=1e-7;

// ========================================================================
// FIND UNIQUE X-COORDINATES
// ========================================================================

// ---- Extract unique x-coordinates ----
// For a fixed (y, z) slice, collect all distinct x-values
// These define the ray positions in the x-direction
std::vector<double> xlist;
int onetime_1=0;
double x_val=0.0;
double y_val=0.0;
double z_val=0.0;
Info<<"Searching for unique x-coordinates"<<endl;
forAll( mesh.C(), celli)
{
	vector XYZ = mesh.C()[celli];
	// Use the first cell's y,z as reference for the slice
	if(onetime_1==0)
	{
		y_val=XYZ.y();
		z_val=XYZ.z();
		onetime_1++;
	}
	// Only consider cells in the same (y, z) slice
	if(std::abs(XYZ.y()-y_val)<coord_tolerence&&std::abs(XYZ.z()-z_val)<coord_tolerence)
	{
		Info<<XYZ.x()<<"\t"<<XYZ.y()<<"\t"<<XYZ.z()<<endl;
		// Add to list if not already present
		if(std::find(xlist.begin(),xlist.end(),XYZ.x())==xlist.end())
		{
			xlist.push_back(XYZ.x());
			num_unique_x_coords+=1;
		}
	}
}

// ========================================================================
// FIND UNIQUE Z-COORDINATES
// ========================================================================

// ---- Extract unique z-coordinates ----
// For a fixed (x, y) slice, collect all distinct z-values
// These define the ray positions in the z-direction (travel direction)
std::vector<double> zlist;
onetime_1=0;
x_val=0.0;
y_val=0.0;
z_val=0.0;
Info<<"Searching for unique z-coordinates"<<endl;
forAll( mesh.C(), celli)
{
	vector XYZ = mesh.C()[celli];
	if(onetime_1==0)
	{
		y_val=XYZ.y();
		x_val=XYZ.x();
		onetime_1++;
	}

	if(std::abs(XYZ.y()-y_val)<coord_tolerence&&std::abs(XYZ.x()-x_val)<coord_tolerence)
	{
		Info<<XYZ.x()<<"\t"<<XYZ.y()<<"\t"<<XYZ.z()<<endl;
		if(std::find(zlist.begin(),zlist.end(),XYZ.z())==zlist.end())
		{
			zlist.push_back(XYZ.z());
			num_unique_z_coords+=1;
		}
	}
}

// ========================================================================
// FIND UNIQUE Y-COORDINATES
// ========================================================================

// ---- Extract unique y-coordinates ----
// For a fixed (x, z) ray, collect all distinct y-values
// These define the depth positions along each ray
std::vector<double> ylist;
onetime_1=0;
x_val=0.0;
y_val=0.0;
z_val=0.0;
Info<<"Searching for unique y-coordinates"<<endl;

forAll( mesh.C(), celli)
{
	vector XYZ = mesh.C()[celli];
	if(onetime_1==0)
	{
		z_val=XYZ.z();
		x_val=XYZ.x();
		onetime_1++;
	}

	if(std::abs(XYZ.z()-z_val)<coord_tolerence&&std::abs(XYZ.x()-x_val)<coord_tolerence)
	{
		Info<<XYZ.x()<<"\t"<<XYZ.y()<<"\t"<<XYZ.z()<<endl;
		if(std::find(ylist.begin(),ylist.end(),XYZ.y())==ylist.end())
		{
			ylist.push_back(XYZ.y());
			num_unique_y_coords+=1;
		}
	}
}

// ========================================================================
// FIND LOWEST Y-COORDINATES (SURFACE DETECTION)
// ========================================================================

// ---- Find the two smallest y-coordinates ----
// These define the top two cell layers in the mesh
// Used for surface detection and heat deposition
double lowest=1.0e6;
double lowest2=1.0e6;

for(int i=0;i<num_unique_y_coords;i++)
{
	if(lowest>ylist[i])
	{
		lowest=ylist[i];
	}
}

for(int i=0;i<num_unique_y_coords;i++)
{
	if(lowest2>ylist[i]&&ylist[i]!=lowest)
	{
		lowest2=ylist[i];
	}
}

// ---- Print summary ----
Info<<"x: "<<num_unique_x_coords<<" z: "<<num_unique_z_coords<<"y: "<<num_unique_y_coords<<endl;
Info<<"lowest y co-ordinate: "<<lowest<<endl;
Info<<"2nd lowest y co-ordinate: "<<lowest2<<endl;
