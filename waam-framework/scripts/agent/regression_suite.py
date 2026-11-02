#!/usr/bin/env python3
"""scripts/agent/regression_suite.py — Phase I assertions (0.6 baseline + F8)."""
import sys, time, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

print("=== Phase I Regression Suite ===")

# I1: pytest
print("\nI1: pytest tests/ -x -q")
r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-x", "-q"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
print(f"  rc={r.returncode} {'PASS' if r.returncode==0 else 'FAIL'}")
print(r.stdout[-500:])

# I2: ruff
print("\nI2: ruff check gui/ core/ ../waam_lab/waam_slicer/slicer_core.py")
r = subprocess.run([sys.executable, "-m", "ruff", "check", "gui/", "core/", "../waam_lab/waam_slicer/slicer_core.py"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
print(f"  rc={r.returncode} {'PASS' if r.returncode==0 else 'FAIL'}")
if r.returncode != 0:
    print(r.stdout[-500:])

# I3: AST parse
print("\nI3: AST parse of touched files")
import ast
touched = [
    "gui/widgets/mesh_viewer_3d.py",
    "../waam_lab/waam_slicer/slicer_core.py",
    "../waam_lab/waam_slicer/gui.py",
    "gui/controllers/mesh_controller.py",
    "gui/controllers/openfoam_controller.py",
    "gui/dialogs/claude_dialog.py",
    "gui/tabs/sim_log_tab.py",
]
for f in touched:
    p = Path(__file__).resolve().parents[2] / f
    if p.exists():
        try:
            ast.parse(p.read_text())
            print(f"  {f}: OK")
        except SyntaxError as e:
            print(f"  {f}: SYNTAX ERROR {e}")
    else:
        print(f"  {f}: NOT FOUND")

# I5: GUI smoke tests (baseline table from 0.6)
print("\nI5: GUI smoke baselines")

# Cache speedup
from waam_slicer.slicer_core import parse_fea_mesh_or_none
mesh = Path(__file__).resolve().parents[2] / "waam_output" / "2026-10-13_03-47-14" / "imported_sphere_radius_10mm_1k_triangles.mesh"
if mesh.exists():
    t0 = time.perf_counter(); parse_fea_mesh_or_none(str(mesh)); t1 = time.perf_counter()-t0
    t0 = time.perf_counter(); parse_fea_mesh_or_none(str(mesh)); t2 = time.perf_counter()-t0
    print(f"  parse_fea_mesh: first={t1*1000:.1f}ms cached={t2*1000:.3f}ms speedup={t1/t2:.0f}x (expect >100x)")

# Slicer fast path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".." / "waam_lab"))
from waam_slicer.gui import WAAMSlicerFrame
import tkinter as tk
root = tk.Tk(); root.withdraw()
slicer = WAAMSlicerFrame(root)
stl = Path(__file__).resolve().parents[2] / "stl" / "cube_80mm.stl"
t0 = time.perf_counter(); slicer.load_fea_mesh(str(stl)); t1 = time.perf_counter()-t0
t0 = time.perf_counter(); slicer.load_fea_mesh(str(stl)); t2 = time.perf_counter()-t0
print(f"  load_fea_mesh: first={t1*1000:.1f}ms repeat={t2*1000:.1f}ms (expect repeat ~0ms)")

# Viewport schedule cost
from gui.widgets.mesh_viewer_3d import EmbeddedMeshViewport
vp = EmbeddedMeshViewport(root)
vp.load_stl_file(str(stl))
root.update()
t0 = time.perf_counter(); vp._schedule_render(); t1 = time.perf_counter()-t0
print(f"  _schedule_render: {t1*1000:.3f}ms (expect <=0.05ms)")

vp.destroy()
root.destroy()

print("\n=== Phase I complete ===")
