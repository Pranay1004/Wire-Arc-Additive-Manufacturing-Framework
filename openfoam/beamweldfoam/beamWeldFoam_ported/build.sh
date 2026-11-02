#!/bin/sh
# beamWeldFoam ported to OpenFOAM 2412
# Build script

cd ${0%/*} || exit 1

. /opt/homebrew/bin/openfoam2412

wmake beamWeldFoam

echo ""
echo "============================================"
echo "  beamWeldFoam build complete"
echo "  Binary: \$FOAM_USER_APPBIN/beamWeldFoam"
echo "============================================"
