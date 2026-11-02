#!/usr/bin/env python3
"""scripts/agent/bench_slicer.py — F1.3 slicer bench."""
import sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".." / "waam_lab"))
from waam_slicer.slicer_core import slice_mesh
import trimesh

stl = Path(__file__).resolve().parents[2] / "stl" / "cube_80mm.stl"
mesh = trimesh.load(str(stl))
times = []
for i in range(3):
    t0 = time.perf_counter()
    tp = slice_mesh(mesh, layer_height=0.003)
    t1 = time.perf_counter() - t0
    times.append(t1)
    n = len(tp.get('toolpath', [])) if isinstance(tp, dict) else 0
    print(f"  run {i+1}: {t1:.3f}s points={n}")
if len(times) > 1:
    print(f"  mean={statistics.mean(times):.3f}s std={statistics.stdev(times):.3f}s")
else:
    print(f"  {times[0]:.3f}s")
print("RESULT bench_slicer complete")
