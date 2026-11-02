#!/usr/bin/env python3
"""scripts/agent/bench_edp_build.py — F1.5 EDP build bench."""
import sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from codegen.edp_builder import EDPBuilder

# Minimal param set
params = {
    "lx": 0.15, "ly_base": 0.15, "hz_base": 0.005,
    "arc_current_A": 200, "arc_voltage_V": 24, "eta_arc": 0.8,
    "travel_speed_mm_s": 10, "layers_count": 10,
    "material": "SS308L", "material_base": "SS316L",
    "nx_base": 30, "ny_base": 8, "nz_base": 2,
    "nx_dep": 30, "ny_dep": 3, "nz_dep": 20,
    "heat_source": "goldak", "solver": "sparsesolver",
}

times = []
for i in range(50):
    b = EDPBuilder(params)
    t0 = time.perf_counter()
    b.save("/tmp/bench.edp")
    times.append(time.perf_counter() - t0)

print(f"bench_edp_build: p50={statistics.median(times)*1000:.1f}ms p95={sorted(times)[int(len(times)*0.95)]*1000:.1f}ms")
print("RESULT bench_edp_build complete")
