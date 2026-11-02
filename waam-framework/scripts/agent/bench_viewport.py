#!/usr/bin/env python3
"""scripts/agent/bench_viewport.py — F1.6 viewport worker bench."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Test _build_offscreen_frame directly
from gui.widgets.mesh_viewer_3d import EmbeddedMeshViewport, _faces_lod
import tkinter as tk

root = tk.Tk()
root.withdraw()

vp = EmbeddedMeshViewport(root)
vp.pack()

# Load a test mesh
stl = Path(__file__).resolve().parents[2] / "stl" / "cube_80mm.stl"
vp.load_stl_file(str(stl))
root.update()

# Bench cold frame
t0 = time.perf_counter()
frame = vp._build_offscreen_frame({})
t1 = time.perf_counter() - t0
print(f"  cold frame: {t1*1000:.1f}ms")

# Bench warm (same sig -> should skip)
t0 = time.perf_counter()
frame = vp._build_offscreen_frame({})
t1 = time.perf_counter() - t0
print(f"  warm repeat (sig skip): {t1*1000:.3f}ms (None={frame is None})")

# Bench 8 distinct azimuths
params_list = [{"camera_azimuth": a*45} for a in range(8)]
times = []
for p in params_list:
    t0 = time.perf_counter()
    vp._build_offscreen_frame(p)
    times.append(time.perf_counter() - t0)
print(f"  8 azimuths: mean={statistics.mean(times)*1000:.1f}ms p95={sorted(times)[int(len(times)*0.95)]*1000:.1f}ms")

vp.destroy()
root.destroy()
print("RESULT bench_viewport complete")
