# WAAM Deep-Audit — Environment (Phase A+B evidence)

Host: pandeyji-macOS (darwin arm64) - macOS 26.6.2 (Build 25G83)
Session start: 2026-10-24T12:19:46Z

## A1. Python & interpreter

- A1.1: python3 -> /Users/pandeyji/py314env/bin/python3 ; Python 3.14.5 (CPython,
  homebrew python@3.14, arm64 build [Clang 21.0.0]). NOT WindowsApps stub. CPython OK.
- A1.2: enc: utf-8 utf-8 UTF-8 utf-8 (all utf-8 on MAC - no cp1252 issue here).
- A1.3: utf8_mode: 0 (not forced).

## A2. OS identity and quirks

- A2.1: sw_vers -> macOS 26.6.2 (arm64). uname -m -> arm64. NOT WSL2.
- A2.2: DISPLAY=/var/run/com.apple.launchd.DAdE0c1kJa/org.xquartz:0 -> XQuartz X server.
- A2.3: N/A on MAC (no SetProcessDPIAware analog; macOS native Tk expected).

## A3. Compute inventory

- A3.1: hw.ncpu = 10 (sysctl -n machdep.cpu.brand_string hw.ncpu -> 10).
- A3.2: hw.memsize = 17179869184 bytes (~16 GiB).
- A3.3: Apple M4, GPU Vendor Apple (0x106b), Metal Support Metal 4, 10 cores, builtin
  LCD 2880x1864 Retina. No nvidia-smi / no discrete GPU. glxinfo at /opt/X11/bin/glxinfo.

## A4. Disk, sync, interference suspects

- A4.1: iCloud Drive agents RUNNING (bird, CloudDocs, iCloudHelper, iCloudNotification,
  iCloudDriveService) -> repo path may be iCloud-synced -> record for FS-latency finding.

## A5. Shell & toolchain

- A5.1: git 2.50.1, bash 3.2.57 (macOS ancient bash - relevant for OpenFOAM bashrc path).

## B — quick partial results

- B1.x: pending

## B — quick results (MAC)

- B5.1: tkinter OK — tk 9.0.3, ttk theme "aqua" (native via XQuartz).
- B5.2: matplotlib backend = macosx (native, not Agg).
- B6.1: vtk import 1.29s / 1.99s (within 0.6-3.5s expected range).

## C — Static hazard sweep (read-only greps)

### C2.3 text=True without encoding= (4 hits — WIN UnicodeDecodeError risk)
| File | Line | Context |
|------|------|---------|
| gui/dialogs/claude_dialog.py | 67 | Popen(..., text=True) |
| gui/controllers/simulation_controller.py | 475 | Popen(..., text=True) |
| gui/controllers/openfoam_controller.py | 155 | Popen(..., text=True) |
| gui/controllers/openfoam_controller.py | 218 | Popen(..., capture_output=True, text=True, ...) |

**OBS-C01** — All four lack `encoding='utf-8', errors='replace'`. FreeFEM prints UTF-8 (θ, °, µ, Erreur). On WIN cp1252 default -> UnicodeDecodeError kills logging thread silently (GUI appears frozen). SEVERITY S1 (CRASH on WIN). Fix: add encoding to all four Popen calls.

### C3.1 killpg / POSIX process kill (2 hits — WIN orphan FreeFEM)
| File | Line | Context |
|------|------|---------|
| gui/controllers/simulation_controller.py | 632-633 | if hasattr(os, "killpg"): os.killpg(os.getpgid(proc.pid), 9) |

**OBS-C02** — Guarded by hasattr; on WIN killpg absent -> falls through to proc.terminate() only. FreeFEM child threads survive -> next run PermissionError (safe_copy_file retry loop visible symptom). SEVERITY S1 (HANG/CRASH on WIN). Fix: implement Windows-safe kill tree (CREATE_NEW_PROCESS_GROUP + terminate() + wait(timeout) + taskkill /T /F fallback).

### C1.2 cwd-relative paths ./waam_output ./stl (12 hits — launch-dir dependent)
| File | Line | Pattern |
|------|------|---------|
| gui/app.py | 3089, 3195 | "./waam_output" |
| gui/controllers/mesh_controller.py | 625 | "./waam_output" |
| gui/widgets/waam_3d_studio.py | 177, 245 | "./stl", "./waam_output" |
| gui/widgets/mesh_viewer_3d.py | 473 | "./waam_output" |
| mesh/intelligent_mesher.py | 229 | "./waam_output" |
| mesh/slicer_api.py | 1042 | "./stl" |
| ../waam_lab/waam_slicer/gui.py | 234, 253, 254, 2078 | "./stl", "./waam_output" |

**OBS-C03** — Launching `python run.py` from $HOME or C:\ on WIN writes sim outputs to wrong dir. SEVERITY S2 (INCOMPAT). Fix: resolve relative to repo root (Path(__file__).resolve().parents[N] / "waam_output") or require absolute.

### C1.1 STL refs case/existence mismatch (13 hits)
- Code references: `letter_Z_WAAM.stl`, `cube_80mm.stl`, `Main.stl` (comment)
- Actual files in stl/: `cube_80mm.stl`, `main.stl`, `z.stl`, ...
- `letter_Z_WAAM.stl` does NOT exist (closest: `z.stl`). `Main.stl` does NOT exist (closest: `main.stl`).

**OBS-C04** — On case-sensitive FS (UBU), `letter_Z_WAAM.stl` fails silently; GUI default sample broken. SEVERITY S2 (INCOMPAT). Fix: align code refs to actual filenames or ship the referenced file.

### C4.1 file opens — all explicit utf-8 (18 hits) ✅ GOOD
All `open()` calls in gui/ and waam_slicer/ use `encoding="utf-8"` (some with `errors="ignore"` or `"replace"`). No default-encoding reads.

### C5.1 per-line after(0, app._log/...) floods (52 hits — BOTTLENECK)
| File | Count | Notable lines |
|------|-------|---------------|
| gui/dialogs/claude_dialog.py | 8 | 94, 101, 127, 131, 134-137 |
| gui/controllers/mesh_controller.py | 10 | 209, 211, 634, 637, 647-650, 656, 659-660 |
| gui/controllers/simulation_controller.py | 20+ | 513, 515, 544, 552, 556, 558, 560, 563, 583, 587, 590, 591 |

**OBS-C05** — Many `after(0, app._log, ...)` calls in loops/per-line. Prior fix added batching (`poll_stream` 25ms/350-line cap, `openfoam_controller._flush` 0.25s/400-line, `claude_dialog` 80-line/0.25s) but raw per-line `after` calls remain in these three files. On high-volume streams (simulation, meshing, OpenFOAM) this floods Tk event loop -> GUI freeze. SEVERITY S1 (BOTTLENECK on all OSes). Fix: route ALL log/status through batched queues; remove raw per-line `after(0, app._log)` in worker callbacks.

### waam_output initial scan (Phase E)
- 80 log files total
- 27 contain error patterns (Erreur/Fatal/OutOfMem/SIGSEGV/EXECUTION FINISHED)
- Largest sim.log: 4,628 lines (2026-10-23_22-21-39)
- 79 run dirs confirmed
