"""
ParaView Automation Launcher for uva_pranay OpenFOAM Case
"""

import os
import sys
import subprocess
from pathlib import Path

case_dir = Path(__file__).resolve().parent
foam_file = case_dir / "uva_pranay.foam"

if not foam_file.exists():
    foam_file.touch()

paraview_paths = [
    "/Users/pandeyji/bin/paraview",
    "/Applications/ParaView-5.13.3.app/Contents/MacOS/paraview",
    "/Applications/ParaView-5.12.0.app/Contents/MacOS/paraview",
    "paraview",
]

pv_bin = None
for p in paraview_paths:
    if os.path.isfile(p) and os.access(p, os.X_OK):
        pv_bin = p
        break

if not pv_bin:
    print(f"[NOTE] ParaView binary not found in standard paths. You can open '{foam_file}' directly in ParaView GUI.")
    sys.exit(0)

print(f"Launching ParaView with: {foam_file}")
subprocess.Popen([pv_bin, str(foam_file)])
