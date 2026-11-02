#!/usr/bin/env python3
"""scripts/agent/bench_parse_mesh.py — F1.1 mesh parse bench."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".." / "waam_lab"))
from waam_slicer.slicer_core import parse_fea_mesh_or_none

ROOT = Path(__file__).resolve().parents[2] / "waam_output"
meshes = list(ROOT.rglob("imported_*.mesh"))[:10]

print("bench_parse_mesh: first vs cached")
for m in meshes:
    t0 = time.perf_counter()
    mesh1 = parse_fea_mesh_or_none(str(m))
    t1 = time.perf_counter() - t0
    t0 = time.perf_counter()
    mesh2 = parse_fea_mesh_or_none(str(m))
    t2 = time.perf_counter() - t0
    nodes = mesh1.get('n_nodes', 0) if mesh1 else 0
    if t2 > 0:
        print(f"  {m.name}: nodes={nodes} first={t1*1000:.1f}ms cached={t2*1000:.3f}ms speedup={t1/t2:.0f}x")
    else:
        print(f"  {m.name}: nodes={nodes} first={t1*1000:.1f}ms cached=0ms")
print("RESULT bench_parse_mesh complete")
