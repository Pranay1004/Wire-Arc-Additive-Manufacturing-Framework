#!/usr/bin/env python3
"""scripts/agent/vtk_capability.py — offscreen render capability matrix (B6.1)."""
import os, sys, subprocess, time, json

def try_mode(name, env, script):
    env = {**os.environ, **env}
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, env=env, timeout=30)
        elapsed = time.perf_counter() - t0
        ok = proc.returncode == 0
        print(f"{name}: {'OK' if ok else 'FAIL'} ({elapsed:.2f}s)")
        if not ok:
            print(f"  stderr: {proc.stderr[:200]}")
        return {"mode": name, "ok": ok, "first_frame_s": elapsed if ok else None}
    except subprocess.TimeoutExpired:
        print(f"{name}: TIMEOUT")
        return {"mode": name, "ok": False, "first_frame_s": None}
    except Exception as e:
        print(f"{name}: ERROR {e}")
        return {"mode": name, "ok": False, "first_frame_s": None}

# Standard test scene
scene = """
import pyvista as pv
import time
p = pv.Plotter(off_screen=True)
p.add_mesh(pv.Box(), style='wireframe')
p.show(auto_close=False)
t0 = time.perf_counter()
for _ in range(30):
    p.camera.azimuth += 3
    p.render()
fps = 30 / (time.perf_counter() - t0)
print(f"FPS={fps:.1f}")
"""

results = []
# (a) normal off-screen with X (xvfb-run on Linux)
if sys.platform != "darwin":
    results.append(try_mode("xvfb", {"DISPLAY": ":99"}, scene))
# (b) VTK_DEFAULT_OPENGL_WINDOW=offscreen EGL
results.append(try_mode("egl_offscreen", {"VTK_DEFAULT_OPENGL_WINDOW": "offscreen"}, scene))
# (c) OSMesa software
results.append(try_mode("osmesa", {"LIBGL_ALWAYS_SOFTWARE": "1"}, scene))
# (d) pyvista.start_xvfb()
if sys.platform != "darwin":
    scene_xvfb = "import pyvista as pv; pv.start_xvfb(); " + scene
    results.append(try_mode("pyvista_xvfb", {}, scene_xvfb))

# Save capability JSON
with open("docs/audit/vtk_capability.json", "w") as f:
    json.dump(results, f, indent=2)

print("RESULT vtk_capability complete")
