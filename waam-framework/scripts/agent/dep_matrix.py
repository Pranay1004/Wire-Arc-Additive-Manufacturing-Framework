#!/usr/bin/env python3
"""scripts/agent/dep_matrix.py — import/version matrix for audit."""
import sys, importlib, pkgutil, subprocess, json, os
from pathlib import Path

REQ_FILE = Path(__file__).resolve().parents[2] / "requirements.txt"
def parse_reqs(p):
    reqs = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].strip().lower()
                reqs[name] = line
    return reqs

REQUIRED_BY_REQ = parse_reqs(REQ_FILE)

# Modules to probe: (import_name, display_name, required_by)
MODULES = [
    ("numpy", "numpy", True),
    ("scipy", "scipy", True),
    ("pandas", "pandas", True),
    ("matplotlib", "matplotlib", True),
    ("PIL", "pillow", True),
    ("imageio", "imageio", True),
    ("vtk", "vtk", True),
    ("pyvista", "pyvista", True),
    ("trimesh", "trimesh", True),
    ("shapely", "shapely", True),  # module-level import in waam_slicer/slicer_core.py
    ("meshio", "meshio", False),
    ("gmsh", "gmsh", False),
    ("fitz", "PyMuPDF", False),
    ("networkx", "networkx", False),
    ("igraph", "igraph", False),
    ("pytest", "pytest", False),
    ("ruff", "ruff", False),
]

def get_version(mod):
    try:
        m = importlib.import_module(mod)
        return getattr(m, "__version__", "unknown")
    except Exception as e:
        return f"IMPORT_ERROR: {e}"

print("Module,Import_Name,Version,Required_By_Req,Required_By_Code,Status")
for imp, disp, req in MODULES:
    ver = get_version(imp)
    in_req = disp.lower() in REQUIRED_BY_REQ
    status = "OK" if not ver.startswith("IMPORT_ERROR") else "MISSING"
    if in_req and status == "MISSING":
        status = "MISSING_FROM_REQS"
    print(f"{disp},{imp},{ver},{in_req},True,{status}")

# Also check for numpy BLAS
try:
    import numpy as np
    print(f"\n# numpy config:")
    print(f"# blas_opt_info: {np.__config__.get_info('blas_opt_info')}")
except Exception:
    pass

print("RESULT dep_matrix complete")
