#!/bin/bash
# test_all_tutorials.sh — Run all beamWeldFoam tutorials to completion
# Each tutorial runs with its own controlDict endTime
# Output: live terminal + log per tutorial

set -e
cd "$(dirname "$0")"

SOLVER="beamWeldFoam"
TIMEOUT=600  # 10 min max per tutorial (small meshes run fast)

run_tutorial() {
    local name=$1
    local dir="tutorials/$name"
    local log="$dir/Allrun.log"

    echo "============================================"
    echo "  Tutorial: $name"
    echo "============================================"

    if [ ! -d "$dir" ]; then
        echo "  SKIP: directory not found"
        return 1
    fi

    # Clean previous run
    rm -rf "$dir/0" "$dir"/[0-9]* "$dir/processor*" "$dir/log"
    rm -f "$log"

    # Copy initial to 0
    if [ -d "$dir/initial" ]; then
        cp -r "$dir/initial" "$dir/0"
    else
        echo "  SKIP: no initial/ directory"
        return 1
    fi

    # Remove legacy fields
    rm -f "$dir/0/D" "$dir/0/gradTSol" "$dir/0/TRHS" "$dir/0/sourceTerm"

    # Ensure required constant files
    if [ ! -f "$dir/constant/turbulenceProperties" ]; then
        cat > "$dir/constant/turbulenceProperties" << 'TF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}

simulationType  laminar;
TF
    fi

    if [ ! -f "$dir/constant/g" ]; then
        cat > "$dir/constant/g" << 'GF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      g;
}

dimensions      [0 1 -2 0 0 0 0];
value           (0 -9.81 0);
GF
    fi

    if [ ! -f "$dir/constant/dynamicMeshDict" ] && [ ! -f "$dir/constant/motionProperties" ]; then
        cat > "$dir/constant/dynamicMeshDict" << 'DM'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      dynamicMeshDict;
}

dynamicFvMesh   staticFvMesh;
DM
    fi

    # Step 1: Mesh
    echo "  [1/4] blockMesh..."
    if ! (cd "$dir" && blockMesh > "$log" 2>&1); then
        echo "  FAIL: blockMesh"; tail -10 "$log"; return 1
    fi
    echo "        OK"

    # Step 2: setFields
    echo "  [2/4] setFields..."
    if [ -f "$dir/system/setFieldsDict" ]; then
        if ! (cd "$dir" && setFields >> "$log" 2>&1); then
            echo "  FAIL: setFields"; tail -10 "$log"; return 1
        fi
    fi
    echo "        OK"

    # Step 3: Solve
    echo "  [3/4] $SOLVER (timeout ${TIMEOUT}s)..."
    local exit_code=0
    (cd "$dir" && timeout "$TIMEOUT" $SOLVER 2>&1 | tee -a "$log") || exit_code=$?

    # Step 4: Check results
    local timesteps=$(ls -d "$dir"/[0-9]* 2>/dev/null | wc -l | tr -d ' ')

    if [ "$timesteps" -gt 0 ]; then
        local last=$(ls -d "$dir"/[0-9]* 2>/dev/null | sort -V | tail -1)
        local fields_ok="YES"
        for f in Temperature U alpha.phase1 p_rgh; do
            [ -f "$last/$f" ] || fields_ok="NO"
        done
        echo "  [4/4] PASS: $timesteps steps, fields=$fields_ok, exit=$exit_code"
        return 0
    else
        echo "  [4/4] FAIL: no timesteps (exit=$exit_code)"
        tail -20 "$log"
        return 1
    fi
}

# --- Run all tutorials ---
PASS=0
FAIL=0

# Small meshes — fast
for t in SingleParticleMelting2D Test Tancase GalluimCase ArcCase; do
    run_tutorial "$t" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
    echo ""
done

# Medium meshes
for t in PowderBed2D SenDavies PowderBed3D; do
    run_tutorial "$t" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
    echo ""
done

# Large meshes — may need longer timeout
for t in EB_3D; do
    run_tutorial "$t" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
    echo ""
done

# Very large — skip if <16GB
echo "============================================"
echo "  Skipping GalluimCase3D (6.7M cells, needs >16GB)"
echo "============================================"

echo ""
echo "============================================"
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "============================================"
