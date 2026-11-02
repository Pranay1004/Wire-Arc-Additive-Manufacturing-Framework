#!/usr/bin/env python3
"""scripts/agent/bench_cad_load.py — F1.2 CAD load bench."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gui.widgets.mesh_viewer_3d import load_any_cad_geometry, _load_any_cad_geometry_impl

stl_dir = Path(__file__).resolve().parents[2] / "stl"
files = list(stl_dir.glob("*.stl"))[:5]

print("bench_cad_load: first vs cached")
for f in files:
    # First call (bust cache)
    import gui.widgets.mesh_viewer_3d as mv
    mv._CAD_CACHE.clear()
    t0 = time.perf_counter()
    mesh1 = load_any_cad_geometry(str(f))
    t1 = time.perf_counter() - t0
    # Cached call
    t0 = time.perf_counter()
    mesh2 = load_any_cad_geometry(str(f))
    t2 = time.perf_counter() - t0
    n = len(mesh1.vertices) if hasattr(mesh1, 'vertices') else (mesh1.n_points if hasattr(mesh1, 'n_points') else 0)
    print(f"  {f.name}: n={n} first={t1*1000:.1f}ms cached={t2*1000:.3f}ms")
print("RESULT bench_cad_load complete")
