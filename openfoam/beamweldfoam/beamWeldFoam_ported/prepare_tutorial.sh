#!/bin/bash
# Prepare a tutorial for testing: clean, set up, generate mesh, set fields
# Usage: ./prepare_tutorial.sh <tutorial_name>

TUTORIAL_DIR="/Users/pandeyji/Desktop/WAAM/beamWeldFoam_ported/tutorials/$1"

if [ ! -d "$TUTORIAL_DIR" ]; then
    echo "FAIL: Tutorial $1 not found"
    exit 1
fi

cd "$TUTORIAL_DIR"

# Clean previous run
rm -rf 0 [0-9]* log processor*

# Copy initial to 0
cp -r initial 0

# Remove legacy fields that beamWeldFoam doesn't read
rm -f 0/D 0/gradTSol 0/TRHS 0/sourceTerm

# Update controlDict
sed -i "" "s/application .*/application     beamWeldFoam;/" system/controlDict
sed -i "" "s/endTime .*/endTime         1e-06;/" system/controlDict
sed -i "" "s/writeInterval .*/writeInterval   1e-07;/" system/controlDict
sed -i "" "s/writeCompression .*/writeCompression uncompressed;/" system/controlDict

# Add turbulenceProperties if missing
if [ ! -f constant/turbulenceProperties ]; then
    cat > constant/turbulenceProperties << 'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}

simulationType  laminar;
EOF
fi

# Add g if missing
if [ ! -f constant/g ]; then
    cat > constant/g << 'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      g;
}

dimensions      [0 1 -2 0 0 0 0];
value           (0 -9.81 0);
EOF
fi

# Add dynamicMeshDict if missing
if [ ! -f constant/dynamicMeshDict ] && [ ! -f constant/motionProperties ]; then
    cat > constant/dynamicMeshDict << 'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      dynamicMeshDict;
}

dynamicFvMesh   staticFvMesh;
EOF
fi

# Generate mesh
echo "Generating mesh..."
blockMesh -dict system/blockMeshDict > log 2>&1
if [ $? -ne 0 ]; then
    echo "FAIL: blockMesh failed"
    tail -10 log
    exit 1
fi

# Set fields if setFieldsDict exists
if [ -f system/setFieldsDict ]; then
    echo "Setting fields..."
    setFields >> log 2>&1
    if [ $? -ne 0 ]; then
        echo "FAIL: setFields failed"
        tail -10 log
        exit 1
    fi
fi

echo "READY: $1"
