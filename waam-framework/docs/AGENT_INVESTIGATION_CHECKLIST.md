# WAAM Workstation Deep-Audit Checklist — AI-Agent Edition

```
Document : docs/AGENT_INVESTIGATION_CHECKLIST.md
Version  : 1.0 (2026-10-24)
Owner    : WAAM Multi-Physics Framework (gui/, core/, mesh/, codegen/, postprocess/, waam_lab/)
Mission  : Autonomously investigate BOTTLENECKS, CRASHES, and CROSS-PLATFORM
           INCOMPATIBILITIES (Windows + Ubuntu + macOS) of the WAAM GUI/solver
           stack, using the run history already on disk in waam_output/ as
           evidence, and produce a machine-readable report.
```

---

## 0. HOW TO USE THIS CHECKLIST (READ FIRST)

### 0.1 Operating modes

| Mode | Flag | Meaning |
|------|------|---------|
| `AUDIT-ONLY` (default) | `--audit` | Gather evidence, run benches, parse sims. **Never modify** framework source, never delete anything. |
| `AUDIT+PROPOSE` | `--propose` | Everything above + write proposed patches to `docs/audit/patches/*.diff` (NOT applied). |
| `AUDIT+FIX` | `--fix` | Apply fixes one at a time, **only** after each passes the verification loop in Phase I. |

The executing agent MUST announce its mode at session start and log it in
`docs/audit/AUDIT_STATE.md`.

### 0.2 Hard guardrails (NON-NEGOTIABLE)

1. **`waam_output/` is READ-ONLY EVIDENCE.** It contains 79 timestamped run
   directories with simulation logs, meshes, plots, VTUs. You may read, parse,
   copy, and *create new* `waam_output/agent_<timestamp>*/` folders for test
   runs. You may NEVER delete, move, or modify the contents of existing run
   folders — they are the user's historical simulation record.
2. All new scripts go to `scripts/agent/`. All reports go to `docs/audit/`.
   Anything written outside these two trees is a process violation unless the
   checklist explicitly says otherwise.
3. Never grant yourself `sudo`/admin without recording why in the observations
   log. If a check requires admin (e.g. Windows Defender exclusion inspection
   via `Get-MpPreference`), attempt read-only first, and note the blocker.
4. Never kill or terminate a process unless it was started by *this session*
   (sims started for the benchmark). Killing the user's live GUI is forbidden;
   if one is running, note it and skip invasive probes or ask for permission.
5. Timebox: each phase has a budget. When a phase overruns, record status
   `PARTIAL` with the reason and move on. A partial complete audit beats an
   infinite hang (practice what you audit).
6. Every observation MUST land in the Observations Log (§0.4) with a command,
   an output excerpt, and an interpretation. "It looked slow" is not an
   observation; "2nd parse took 0.02 ms after cache hit (742x)" is.
7. When two platforms disagree (Windows vs Ubuntu), both observations go in
   the same table row so the divergence is explicit.
8. Do not "fix" by commenting out code. Every proposed fix must name the root
   cause mechanism, the exact file/line, and a test that would catch it again.

### 0.3 Session artifacts you must produce

Create this tree at session start:

```
docs/audit/
├── AUDIT_STATE.md          # progress tracker (Phase I checklist state)
├── AUDIT_ENVIRONMENT.md    # Phase A+B evidence dump
├── AUDIT_FINDINGS.md       # Phase C+D static & crash findings + severity
├── AUDIT_SIMULATION_SWEEP.md   # Phase E — waam_output forensic results
├── AUDIT_BENCHMARKS.md     # Phase F — bottleneck matrix results
└── AUDIT_REPORT.md         # final consolidated report (template in §10)
scripts/agent/              # every throwaway script created during the audit
```

### 0.4 Observations Log format

Every single numbered step below that says **[RECORD]** must append an entry
structured like this to the appropriate report file:

```
[OBS-<phase letter><running number>] <UTC timestamp> <hostname> <os>
STEP      : <checklist step id, e.g. B2.3>
COMMAND   : <exact command or script path>
EVIDENCE  : <key lines of stdout/stderr/file excerpt, max 30 lines>
RESULT    : PASS | FAIL | WARN | BLOCKED | SKIPPED
INTERPRET : <one honest sentence about what it means>
SEVERITY  : <S0..S4> (scale in §10.1)
```

Keyed observations (both platforms in one table):

```
| OBS | Metric | macOS | Windows | Ubuntu | Divergence? | Likely cause |
```

### 0.5 Platform legend used throughout

* `MAC`  = macOS (the workstation this doc is authored on).
* `WIN`  = Windows 10/11 (user machines where the app "barely works").
* `UBU`  = Ubuntu 22.04/24.04 (incl. WSL2 — detect and label WSL2 explicitly,
  several findings differ between WSL2 and native Ubuntu).

Commands are given per platform when they differ; otherwise one command is
portable. The agent runs what its current host supports and records the
others as `SKIPPED (not on this host)` with the exact skipped command, so a
later agent can continue on the other machines.

### 0.6 Known-good baseline from the prior fix session (2026-10-24)

The following were VERIFIED on the authoring workstation (use them as
regression baselines; a future audit should reproduce these numbers):

| Test | Expected result |
|------|-----------------|
| `parse_fea_mesh_or_none()` first call | full parse (ms-scale) |
| `parse_fea_mesh_or_none()` 2nd call | `<1 ms` (742x on sphere mesh) |
| `WAAMSlicerFrame.update_mesh()` 1st call | ~35 ms incl. draw |
| `WAAMSlicerFrame.update_mesh()` repeat calls | `<= 1 ms` (fast path + sig dedup) |
| `EmbeddedMeshViewport._schedule_render()` UI-thread cost | `<= 0.05 ms` |
| Viewport render pipeline | off-thread; identical scenes skipped; worker exits cleanly |
| `pytest tests/ -x -q` | **5 passed** |
| `ruff check gui/` | All checks passed |

If a baseline regresses, that is a finding (severity S1).

---

## 1. MISSION TAXONOMY — WHAT COUNTS AS WHAT

Classify every observation into exactly one of:

| Class | Definition | Examples seen in this project |
|-------|-----------|-------------------------------|
| `BOTTLENECK` | Code runs to completion but wastes wall/latency time on the UI thread or blocks interactivity | mesh reparse per keystroke (fixed), per-line `after()` log flood (fixed), matplotlib full redraws, VTK offscreen window re-init |
| `CRASH` | Process aborts, Python exception kills thread/window, or solver exits non-zero unexpectedly | UnicodeDecodeError on solver stdout (see C4.1), VTK/GL init failure headless, FreeFEM exit 258/139 |
| `HANG` | UI or terminal appears alive but never progresses | worker thread deadlocked reading a pipe that never closes; `proc.wait()` on a child that misses stdin EOF |
| `INCOMPAT` | Works on one OS, breaks/degrades on another | case-sensitive paths on Linux (`Main.stl` vs `main.stl`), `os.killpg` absent on Windows, `script -q /dev/null` absent on Windows, cp1252 vs UTF-8 stdout |
| `DATA-QUALITY` | Sim results wrong/incomplete (found via waam_output sweep) | empty plot folders, VTU never written, run_summary.json missing rc |

A single root cause may yield several observations; link them by cause ID
(e.g. `C-01`).

---

## 2. SCOPE MAP — WHAT THE STACK IS

The agent must understand this map before running anything. Verify each box
exists as stated (`- [ ]` verify with the given command), on every audited host.

- [ ] Framework root at `WAAM-Framework/` (this repo): GUI (Tkinter),
      FreeFEM++ EDP codegen, slicing/meshing, postprocess.
- [ ] Sibling lab at `../waam_lab/` (NOT in this repo): `waam_slicer/`
      (slicer GUI + FEA mesh parse + gcode). The GUI lazily imports
      `waam_slicer.gui.WAAMSlicerFrame` — if the sibling is missing the
      viewport silently degrades to `EmbeddedMeshViewport`.
      *check*: `ls ../waam_lab/waam_slicer/gui.py`
- [ ] Entry: `run.py` (GUI default; `--cli`, `--validate`, `--slice`, `--stl`,
      `--openfoam` modes). Confirm `python3 run.py --help` works on host.
- [ ] Solvers: FreeFEM++ (serial + optional mpi), OpenFOAM 2412
      (`beamWeldFoam`), both discovered by `core/platform_adapter.py`.
- [ ] Viz: ParaView (external), PyVista/VTK (embedded + GPU window),
      matplotlib (2D diagrams + slicer previews).
- [ ] Output convention: `waam_output/<YYYY-MM-DD_HH-MM-SS>/` per run with
      `FreeFEM/` subdir, `sim.log`, `parameters.json`, `toolpath.gcode`,
      `toolpath.txt`, `layer_pass_times.txt`, `run_summary.json`, `plots/`,
      `visual_outputs/*.vtu|*.pvd`, `waam_report.html`, and optionally
      `sim_openfoam.log`, `cfd_report.html`, `parameters.json`.
- [ ] GUI event model: single Tk main thread; param edits fan out through
      `trace_add` -> `_on_any_param_change` -> `_schedule_full_refresh`
      (150 ms debounce) -> `update_mesh_calc` + `update_heat_calc`
      -> `vp.update_mesh(...)`. Anything exceeding ~16 ms on that thread is
      by definition a BOTTLENECK finding.

---

## 3. PHASE A — WORKSTATION & ENVIRONMENT INVENTORY  (budget: 45 min)

Purpose: platform facts that explain cross-platform divergences later.
Run ALL of A on every host the agent has access to (authoritative for MAC;
if the agent runs on multiple hosts, tag each observation with hostname).

### A1. Python & interpreter reality

- [ ] A1.1 **[RECORD]** Verbatim interpreter identity:
  ```bash
  # MAC/UBU
  which python3 && python3 -VV; python3 -c "import sys,sysconfig as s; print(s.get_paths()['include'])"
  # WIN
  py -VV & where python & python -c "import sys,sysconfig as s;print(s.get_paths()['include'])"
  ```
  Record: version, build, whether it is CPython, conda, WindowsApps stub
  (the WindowsApps stub is a known silent failure — 900KB alias returns
  nothing). If `python -VV` prints nothing on WIN → S0 finding.
- [ ] A1.2 **[RECORD]** Byte-order/encoding defaults — these cause UTF-8
  crashes in uncommon places:
  ```bash
  python3 -c "import sys,locale;print(sys.getdefaultencoding(), sys.getfilesystemencoding(), locale.getpreferredencoding(False), sys.stdout.encoding)"
  ```
  cp1252/cp932 on WIN vs UTF-8 on UBU is expected and must be quoted in the
  locations where solver stdout is decoded (see C4.1).
- [ ] A1.3 **[RECORD]** `python3 -X utf8 -c "import sys;print(sys.flags.utf8_mode)"`.

### A2. OS identity and quirks

- [ ] A2.1 **[RECORD]** OS build matrix:
  ```bash
  sw_vers; uname -m                      # MAC
  lsb_release -a; uname -a               # UBU
  systeminfo | findstr /B /C:"OS Name" /C:"OS Version"   # WIN (cmd)
  ```
  Detect WSL2: `uname -a | grep -i microsoft` → label `UBU-WSL2` (its GL/VTK
  path differs drastically from native `UBU-GL`).
- [ ] A2.2 **[RECORD]** Desktop env / display server (UBU):
  `echo $XDG_SESSION_TYPE $XDG_CURRENT_DESKTOP; xset q >/dev/null && echo x11-ok`
  Wayland changes VTK/Tk behaviors (see F5.4).
- [ ] A2.3 **[RECORD]** DPI scaling (WIN): `py -c "import ctypes;u=ctypes.windll.user32;u.SetProcessDPIAware();print(u.GetDpiForSystem())"`
  Tk scaling > 100% on Windows can make Tkinter slow with blitting artifacts;
  note it now, correlate in Phase F.

### A3. Compute inventory

- [ ] A3.1 **[RECORD]** CPU/cores:
  ```bash
  sysctl -n machdep.cpu.brand_string hw.ncpu    # MAC
  nproc; lscpu | sed -n '1,12p'                 # UBU
  powershell -c "Get-CimInstance Win32_Processor | Select Name,NumberOfCores,NumberOfLogicalProcessors"  # WIN
  ```
- [ ] A3.2 **[RECORD]** RAM:
  ```bash
  sysctl hw.memsize          # MAC
  free -h                    # UBU
  powershell -c "gcim Win32_ComputerSystem | select TotalPhysicalMemory"   # WIN
  ```
  The solver writes `sim.log` lines at up to 10k lines/s; low-RAM laptops +
  Tk Text 6000-line cap interplay matters. Record now.
- [ ] A3.3 **[RECORD]** GPU / GL stack:
  ```bash
  system_profiler SPDisplaysDataType | sed -n '1,25p'    # MAC (Metal)
  nvidia-smi 2>&1 | sed -n '1,12p'; glxinfo -B 2>&1 | sed -n '1,20p'    # UBU
  dxdiag /t %TEMP%\dxdiag.txt && findstr /i "card name:" %TEMP%\dxdiag.txt # WIN
  ```
  Headless/Remote-desktop VMs frequently have GL 1.1-only stacks → VTK
  offscreen falls back to llvmpipe (see F5.3). Quote the exact `OpenGL core
  profile version` string here.
- [ ] A3.4 **[RECORD]** Thermal/power profile (WIN laptops often throttle to
  0.4 GHz): `powershell -c "gwmi -q 'SELECT * FROM Win32_PerfFormattedData_Counters_ProcessorInformation' | select PercentProcessorPerformance"`.

### A4. Disk, sync, and interference suspects

`safe_copy_file()` retries on PermissionError — the codebase already
anticipates file-watcher interference (Defender/OneDrive/Syncthing/Dropbox).
Prove or refute it here:

- [ ] A4.1 **[RECORD]** Is `waam_output/` (or the whole repo) inside a synced
  folder (OneDrive/Dropbox/Syncthing/iCloud)? `waam_output` lives inside the
  repo; if the *parent* of the repo syncs, every solver telemetry write
  contends with the sync daemon.
  ```bash
  lsof +D waam_output | sed -n '1,25p'       # MAC/UBU  (open handles)
  powershell -c "Get-Process OneDrive,FileSyncHelper,Dropbox,syncthing -ErrorAction SilentlyContinue"
  ```
- [ ] A4.2 **[RECORD]** Defender real-time scan state (WIN):
  `powershell -c "Get-MpComputerStatus | select RealTimeProtectionEnabled"; Get-MpPreference | findstr Exclusion`
  Record the exclusion list.
- [ ] A4.3 **[RECORD]** File-create latency benchmark (this is the Windows
  "tortoise" feeling in GUI log paths):
  ```bash
  python3 scripts/agent/fs_latency.py   # see Appendix 3
  ```
  Thresholds: append-then-close of 1000 x 1KB lines:
  * NVMe native: < 0.5 s
  * Synced/antivirus-scanned dir: > 3 s → S0-adjacent finding (GUI reads
    these files for the Simulation Log tab).

### A5. Shell & toolchain

- [ ] **[RECORD]** Versions: `git --version`, `cmake --version` (optional),
  `bash --version` (WIN often lacks a real bash — OpenFOAM runner assumes
  `bash` exists, see C3.7).
- [ ] **[RECORD]** Terminal host (WIN): Windows Terminal vs conhost (Tk
  behavior and ANSI differ); `echo $env:WT_SESSION`.

---

## 4. PHASE B — DEPENDENCY & BACKEND DISCOVERY MATRIX  (budget: 90 min)

Purpose: consume what `run.py` relies on and prove each link resolves on the
audited host. Every `find_*()` in `core/platform_adapter.py` is a point of
incompatibility; test them through the adapter, not only the PATH.

### B1. Python dependency matrix

- [ ] B1.1 Generate the import/version matrix (script in Appendix 3):
  ```bash
  python3 scripts/agent/dep_matrix.py > docs/audit/AUDIT_ENV.lock
  cat docs/audit/AUDIT_ENV.lock
  ```
  It must probe (import + `__version__`) and mark each: REQUIRED by
  requirements.txt, REQUIRED by code (audit the actual imports!), or optional:
  numpy, scipy (material db interpolation), pandas (report), matplotlib,
  pillow, imageio, vtk, pyvista, trimesh, shapely (**module-level import in
  `waam_slicer/slicer_core.py` — slicer GUI cannot start without it**),
  meshio (fast mesh parse path; ABSENT on many systems → falls back to the
  pure-Python parser: quantified in F1), gmsh (STEP/IGES + mesher),
  PyMuPDF, networkx/igraph if anywhere, pytest, ruff.
- [ ] B1.2 **[RECORD]** Divergence from `requirements.txt` (any missing,
  older-than-pinned, or duplicate-version package = one observation each).
  On UBUNTU specifically check that `numpy` is NOT the system apt numpy
  shadowing pip (mismatched BLAS is a classic UBU slow-matplot issue).
- [ ] B1.3 **[RECORD]** Import the three heaviest modules cold and time them
  (this IS the perceived "slow startup"):
  ```bash
  python3 -X importtime -c "import pyvista"   2> t1.log; python3 -c "import os,time,sys;sys.path.insert(0,'.');t0=time.time();import pyvista;print('pyvista', time.time()-t0)"
  python3 -c "import time; t0=time.time(); import vtk; print('vtk %.2f s'%(time.time()-t0))"
  python3 -c "import time,sys; sys.path.insert(0,'.'); t0=time.time(); import gui.app; print('gui.app %.2f s'%(time.time()-t0))"
  ```
  Reference numbers to record per host: vtk 0.6-3.5 s, pyvista +0.3-1.5 s,
  gui.app 1-4 s (incl. matplotlib). If gui.app > 8 s on WIN → S1 BOTTLENECK.

### B2. FreeFEM++ discovery

- [ ] B2.1 **[RECORD]** Through the adapter (this is what the GUI actually
  trusts):
  ```bash
  python3 -c "import sys; sys.path.insert(0,'.'); from core.platform_adapter import find_freefem_serial, find_freefem_mpi, build_unbuffered_command as b; print('serial:', find_freefem_serial()); print('mpi:', find_freefem_mpi()); print('unbuf:', b(['FreeFem++','x.edp']))"
  ```
  WIN note: verify it finds `FreeFem++-win64.exe` under
  `C:\FreeFem\ff55x64?\FreeFem++.exe` or `Program Files`; UBU: `ff-mpirun`
  apt missing while `FreeFem++` present is fine.
- [ ] B2.2 **[RECORD]** Version banner:
  ```bash
  "FreeFem++-serial" -v | head -3      # or full path from B2.1
  ff-mpirun --version 2>&1 | head -3
  ```
- [ ] B2.3 **[RECORD]** Unbuffered pipe pulse test (this validates the
  `build_unbuffered_command` contract on this platform — Windows console
  buffering can swallow streaming):
  ```bash
  python3 scripts/agent/pipe_pulse.py   # Appendix 3; asserts first chunk < 2 s
  ```
  FAIL on WIN = the GUI looks "dead" for a full run before any output — a
  top-5 user-complaint reproducer.

### B3. OpenFOAM 2412

- [ ] B3.1 **[RECORD]** Environment resolution:
  ```bash
  which beamWeldFoam 2>/dev/null; which blockMesh snappyHexMesh 2>/dev/null
  bash -lc 'source /usr/lib/openfoam/openfoam2412/etc/bashrc 2>/dev/null && which beamWeldFoam'   # UBU
  ls "$USERPROFILE/-APPDATA" 2>/dev/null; wsl -e bash -lc 'which beamWeldFoam'   # WIN-WSL2 pattern
  ```
  Note: `openfoam_controller.py` requires a **POSIX bash** (+ optional
  `script` utility). On native Windows this whole feature is structurally
  unavailable — the audit should record its availability state, not pretend.
- [ ] B3.2 **[RECORD]** Preferred runner realism (C3.7 hazard): does
  `script -q /dev/null bash Allrun` exist here? `command -v script`.
  On macOS `script` exists but has a different argv layout (`-q /dev/null
  <command>`) — verify `openfoam_controller.py`'s darwin usage matches local
  `man script` (S2 if wrong — potential immediate-spawn CRASH).

### B4. ParaView & Gmsh

- [ ] B4.1 **[RECORD]** ParaView discovery (both GUI open paths):
  ```bash
  python3 -c "import sys; sys.path.insert(0,'.'); from core.platform_adapter import find_paraview; print(find_paraview())"
  which paraview pvpython             # UBU
  ls /Applications | grep -i paraview   # MAC
  ```
- [ ] B4.2 **[RECORD]** Gmsh python binding + version + OCCT support:
  ```bash
  python3 -c "import gmsh; gmsh.initialize(); o=gmsh.option; print(gmsh.GMSH_API_VERSION); gmsh.write('/tmp/_g.msh2') if False else None; gmsh.finalize()"
  ```
  STEP import (no `gmsh` on host) silently degrades CAD features — record.

### B5. GUI toolkits

- [ ] B5.1 **[RECORD]** Tk binding + theme engines:
  ```bash
  python3 -c "import tkinter; r=tkinter.Tk(); r.withdraw(); print('tk', r.tk.call('info','patchlevel'), 'ttk', tkinter.ttk.Style(r).theme_use())"
  ```
  (If headless without X, record BLOCKED and use `xvfb-run` on UBU.)
- [ ] B5.2 **[RECORD]** matplotlib backend under headless:
  ```bash
  python3 -c "import matplotlib; print(matplotlib.get_backend())"
  MPLBACKEND=Agg python3 -c "import matplotlib; print('forced', matplotlib.get_backend())"
  ```
  Directory `core/` has no matplotlib `use()` guard before Tk import order
  in some runs — record whether importing `gui.app` headless (no DISPLAY)
  crashes with `TclError: no display` (that is an honest UBU-CLI
  INCOMPAT finding worth its own ticket).

### B6. VTK/PyVista offscreen capability matrix (critical for UBU)

- [ ] B6.1 **[RECORD]** Offscreen render capability:
  ```bash
  python3 scripts/agent/vtk_capability.py   # Appendix 3
  ```
  The script must try, in order, and record which works:
  (a) normal off-screen with X (`xvfb-run -a` on UBU),
  (b) `VTK_DEFAULT_OPENGL_WINDOW=offscreen` EGL path,
  (c) OSMesa software (`LIBGL_ALWAYS_SOFTWARE=1`),
  (d) `pyvista.start_xvfb()` availability.
  For each mode capture: success/failure, first-frame wall time on the
  standard `pv.Box()` scene, and observed FPS for 30 orbit frames.
- [ ] B6.2 **[RECORD]** GPU window (`launch_pyvista_gpu_window`) child
  spawn: measure `python -c <runner>` time-to-window (time until the child
  opens an X/WIN window; use `xvfb-run` snapshot on UBU, mark WIN/BAT
  behavior of detached console windows: `pythonw` vs `python`):

---

## 5. PHASE C — STATIC PLATFORM-HAZARD SWEEP (codebase audit)

Purpose: cross-platform landmines visible by grep. Grep patterns are given —
the agent must run them, then triage each hit. Expected-file counts guide you;
finding ZERO hits where the count says N means your grep env is wrong, rotate
pattern, do not close the item.

Working dir: framework root (`WAAM-Framework/`) plus `../waam_lab/waam_slicer/`.
Exclude: `waam_output/`, `__pycache__`, `*.pyc`, `generated_edps/`,
`original_git_file/`, `case1/`.

### C1. Path, case, and filesystem hazards (INCOMPAT Class)

- [ ] C1.1 Case-sensitivity. Linux mounts are case-sensitive; macOS/Windows
  default case-preserve. Hunt string literals that reference files whose
  on-disk case differs (compare against actual `ls` output):
  ```bash
  grep -rn -i "letter_Z_WAAM\|cube_80mm\|Main\.stl\|main\.stl" gui/ mesh/ run.py ../waam_lab/waam_slicer/ --include=*.py
  ls stl/
  git ls-files stl/ | cat
  ```
  Concrete suspect (verify): the repo carries `stl/Main.stl` (git `M`) while
  `waam_slicer/gui.py` probes `WAAM-Framework/stl/letter_Z_WAAM.stl` and
  `stl/cube_80mm.stl` for the default sample. If a path with the wrong CASE
  is referenced anywhere for the first frame of the GUI, Ubuntu/WSL2 shows a
  missing-file path while mac shows the file. **[RECORD]**
- [ ] C1.2 cwd-relative paths (`./waam_output`, `./stl`, `../...`):
  ```bash
  grep -rn "\./waam_output\|\"\./stl\"\|'\./stl'" gui/ mesh/ ../waam_lab/waam_slicer/ --include=*.py | grep -v test
  ```
  Every such hit must be tagged `depends-on-launch-dir` — launching
  `python C:\...\run.py` from `%USERPROFILE%` on Windows silently writes
  sim outputs to `%USERPROFILE%\waam_output`. Record at least 5 examples and
  verify one interactively (`cd %TEMP%` → GUI defaults intact?). **[RECORD]**
- [ ] C1.3 Temp-dir assumptions (`/tmp`, `$TMPDIR`, `tempfile.gettempdir()`):
  ```bash
  grep -rn "gettempdir\|NamedTemporaryFile\|/tmp/" gui/ mesh/ ../waam_lab/waam_slicer/*.py
  ```
  `mesh_viewer_3d._sweep_stale_pyvista_params` makes cross-process tempfile
  cleanup — confirm the WIN temp layout works (no ACLs issue) and the
  delete=False + parent-side `atexit` scheme does not double-delete when
  both processes die simultaneously.
- [ ] C1.4 Path separators baked as `/` in string ops or regexes:
  ```bash
  grep -rn "replace('\\\\','/')\|rstrip('/')\|endswith('/')\|'/' + \|sep='/'" gui/ core/ mesh/ ../waam_lab/waam_slicer/ --include=*.py
  ```
  Most are intentional (FreeFEM arg convention) — triage only the ones that
  touch filesystem ops.
- [ ] C1.5 `os.path` vs `Path` mixing on Windows long paths (>260 chars).
  Windows long-path support off by default; run dirs like
  `waam_output/2026-10-13_03-41-41/FreeFEM/visual_outputs/…` get deep. Bench
  a 300-char path create/write/read on WIN. **[RECORD]**

### C2. Subprocess lifecycle hazards (HANG/CRASH Class)

- [ ] C2.1 Orphan/kill machinery per OS:
  ```bash
  grep -rn "killpg\|start_new_session\|CREATE_NO_WINDOW\|creationflags\|preexec_fn" gui/ core/ --include=*.py
  ```
  Known: `stop_simulation()` uses `os.killpg` (POSIX-only). On WIN the
  fallback is `proc.terminate()` only → FreeFEM child threads survive;
  next run collides on the same mesh file (`safe_copy_file` PermissionError
  retry loop is the visible symptom). Reproduce: start sim, stop at step 3,
  `tasklist | findstr FreeFem`. **[RECORD]**
- [ ] C2.2 Pipes not closed/timed-out (`proc.wait()` after `readline` loop
  with stdin modes) — grep `\.wait(timeout` absence:
  ```bash
  grep -rn "proc.wait()\|\.wait()" gui/ --include=*.py
  ```
- [ ] C2.3 `text=True` without `encoding=` in Popen (decode crash on WIN):
  ```bash
  grep -rn "text=True" gui/ codegen/ --include=*.py
  ```
  For each hit, check whether the source may emit non-cp1252 bytes
  (FreeFEM prints `µ`, `°`, `Erreur`; UTF-8 art). Any hit without
  `encoding='utf-8', errors='replace'` = sS1 potential UnicodeDecodeError
  that kills the logging thread silently (the GUI "freezes" on error).
  **[RECORD]** — verify with the controlled probe F-G2 feed:
  `python scripts/agent/stdout_utf8_probe.py` (Appendix 3).
- [ ] C2.4 `bufsize=1` semantics NOTE: with `text=True` this is line-buffered;
  trailing `errors` behavior is not — only on Python 3.8+ validated on stain.
  Record the host Python version against each spawn (ties to A1).
- [ ] C2.5 Shell=True inventory (injection + WIN cmd.exe quirks):
  `grep -rn shell=True gui/ core/ ../waam_lab/waam_slicer/ --include=*.py`
  Record CPU of each and whether argv quoting handles spaces (`Program Files`).
- [ ] C2.6 `-c` runner scripts (`subprocess.Popen([sys.executable, "-c", script])`)
  in `mesh_viewer_3d.py` and `waam_3d_studio.py` — do they survive (a) paths
  with spaces, (b) a `py.exe` launcher (not `python.exe`) enterprise WIN box,
  (c) UBU `python3` pinned version mismatch? **[RECORD]**

### C3. Platform-conditional APIs (INCOMPAT Class)

For each: grep, then verify the alternative exists for the losing OS.

- [ ] C3.1 `os.killpg/os.getpgid` — WIN AttributeError path (already latent
  in `stop_simulation`; make sure exception path is exercised on WIN).
- [ ] C3.2 `open -a` (darwin-only) fallbacks vs `xdg-open` (UBU-only) vs
  `subprocess.Popen([pv_bin,...])` — inventory + result on all THREE:
  ```bash
  grep -rn '"open"\|open -a\|xdg-open\|explorer' gui/ --include=*.py
  ```
- [ ] C3.3 darwin-fixed ParaView path list (`/Applications/ParaView-5.13.3.app...`) —
  dead weights on WIN/UBU get skipped silently; document the resolution
  order by running the finder function on each host.
- [ ] C3.4 `HOST_ARCH` / `platform.machine()` branches:
  `grep -rn "HOST_ARCH\|uname\|machine()" core/ run.py --include=*.py`
- [ ] C3.5 File dialog defaults — `initialdir = Path.home() / "Desktop"`:
  Windows user without Desktop (OneDrive Roaming), Ubuntu server: confirm
  fallback (does `filedialog` crash if dir missing?). **[RECORD]**
- [ ] C3.6 `os.environ` thread manipulation before spawn
  (`OMP_NUM_THREADS` etc.): on UBU check `psutil` vs `os.cpu_count()` count
  mismatch in containers/WSL2 (`nproc` honors `taskset`, `os.cpu_count()` does
  not in older Python) → oversubscription. **[RECORD]** (`os.cpu_count()` counts
  host CPUs — in WSL2/containers this can be 2-4x oversubscribed).
- [ ] C3.7 Optional deps behind module-level imports on threading paths:
  `shapely` level import in `waam_slicer/slicer_core.py`, `melodia`-like —
  run the slicer-tool path dependency map:
  ```bash
  python3 - <<'PY'
  import sys; sys.path.insert(0, "../waam_lab")
  import importlib
  for mod in ["waam_slicer.slicer_core", "waam_slicer.gcode_gen", "waam_slicer.toolpath", "waam_slicer.gui"]:
      try: importlib.import_module(mod) and print(mod, "OK")
      except Exception as e: print(mod, "IMPORT-FAIL", e)
  PY
  ```
  An import failure of these makes the ENTIRE viewport tab bounce to the
  fallback silently (`viewport_tab.py` catches and swaps) — probably logging
  only once. **[RECORD]** with the startup log if any.

### C4. Encoding & locale hazards (CRASH Class)

- [ ] C4.1 【the big one】 stdout decode mismatches (see C2.3 triple-check):
  ```bash
  grep -rn "encoding" gui/ ../waam_lab/waam_slicer/*.py --include=*.py | grep -v "#"
  ```
  Then verify ACTUAL behavior on the current host with a child that prints
  UTF-8 with `PYTHONIOENCODING` unset:
  ```bash
  python3 - <<'PY'
  import subprocess, sys, unittest.mock
  code = "import sys; sys.stdout.write('θ=0.6° Ça marche\\n')"
  try:
      out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
      print("OK ", out.stdout, out.stderr[-200:])
  except Exception as e:
      print("DECODE-FAIL", e)
  PY
  ```
- [ ] C4.2 File reads defaults (`open(path)` without encoding) ALL —
  `grep -rn "open(" gui/ mesh/ ../waam_lab/waam_slicer --include=*.py | grep -v encoding | grep -v "b\"\\|b'"`.
  cp1252-default on WIN + logs written as UTF-8 elsewhere = mojibake in
  reports. Inventory and grade.

### C5. GUI-event hazards (BOTTLENECK/HANG Class) — regression watch

These were partially fixed on 2026-10-24; the audit re-verifies and hunts for
remaining instances:

- [ ] C5.1 Per-event callback floods: search every thread that forwards child
  pipes:
  ```bash
  grep -rn "after(0, app._log\|after(0, app\.status\|after(0, lambda" gui/ --include=*.py
  ```
  Classification rule: inside a `for line in <pipe>` or iter loop → BOTTLENECK
  (fix pattern: `queue.Queue` + poll timer, like `simulation_controller`).
  Accepted pattern check: `simulation_controller.poll_stream` uses 25 ms tick,
  batch cap 350 lines, `_log_batch` groups tags, buffer trims > 6000 lines.
  Confirm all four invariants still true. **[RECORD]**
- [ ] C5.2 Main-thread heavy lifting beyond event budget — grep the known
  offender classes and record which remain synchronous:
  * `canvasO.draw()` / `canvasO.draw_idle()` calls in `waam_slicer/gui.py`
    (mpl full redraw cost measured in F3).
  * `diag_canvas.draw_idle()` in `_draw_2d_diagram` — verify the signature
    dedup is active or not after the fix, and measure (F3).
  * `parse_fea_mesh*` called outside cache-wrapped entry points.
- [ ] C5.3 Trace-driven recalulation storms:
  ```bash
  grep -rn "trace_add" gui/ --include=*.py
  ```
  For each writer callback, trace what else mutates those vars — detect
  cancellation loops (A→B→A writes anchored by `_syncing_*` guards). Use a
  live probe: attach a counter + 10 ms sampling, wiggle a slider, count
  callbacks/sec. Flooding > 50/s with blank result = BOTTLENECK. **[RECORD]**
- [ ] C5.4 Un-bounded loops with per-iteration Tk creation (viewports,
  gcode viewer, layer list): search `for ... range(` near `create_` or
  `insert(` Tk calls in `gui/` + `waam_slicer/gui.py`.

### C6. waam_lab specifics (the sibling most audits miss)

- [ ] C6.1 Sibling resolution path (`../../waam_lab` relative to file or cwd?)
  ```bash
  grep -rn "waam_lab" WAAM-Framework/gui WAAM-Framework/run.py | head -20
  ```
  Verify the import resolves when launched from (a) repo root, (b) `$HOME`,
  (c) `C:\` on WIN, (d) `/` on UBU. The `-c` child runners are re-tested here.
- [ ] C6.2 `load_any_cad_geometry` FEA branch (framework side) — does it
  bypass or use the new cache? (It must call `parse_fea_mesh_or_none` which
  is cached in `slicer_core.py`.)
- [ ] C6.3 `WAAMSlicerFrame.update_mesh()` fast paths (added 2026-10-24):
  verify by reading that (a) `load_fea_mesh` only re-parses when stat differs
  and (b) `_redraw_fea_mesh_inner` has signature dedup. Then live-test with
  F3.3 bench. **[RECORD]**

### C7. Write a hazard inventory table

Consolidate C1-C6 into `AUDIT_FINDINGS.md` as:

```
| Hazard ID | File:Line | Snippet | Class | OSes hit | Trigger | Proposed fix (1-line) | Test to prove |
```

---

## 6. PHASE D — RUNTIME CRASH FORENSICS  (budget: 2 h)

Purpose: actually reproduce, capture, and dissect crashes on this host
(repeat this phase on WIN and UBU with the same scripts).

### D1. Crash capture harness

- [ ] D1.1 Launch the GUI under evidence capture:
  ```bash
  python3 -X faulthandler -c "
  import faulthandler, sys, run
  faulthandler.enable(open('docs/audit/faulthandler.log','w'))
  sys.argv=['run.py']
  run.main() if hasattr(run,'main') else exec(open('run.py').read())
  " 2> docs/audit/gui_stderr.log &
  ```
  (Adapt: whatever launches the GUI in run.py.) stderr must go to a real
  file, not a swallowed terminal.
- [ ] D1.2 Enable periodic thread dumps while open (proves thread liveness
  when a hang is reported later):
  ```bash
  python3 -c "
  import faulthandler, threading, time, os
  f=open('docs/audit/threadpump.log','a')
  # agent: piggyback faulthandler.dump_traceback_later(30, repeat=True, file=f)
  "
  ```
- [ ] D1.3 Crash artifacts per OS — enumerate AFTER any crash occurs:
  * MAC: `ls -t ~/Library/Logs/DiagnosticReports/ | head` (python3_*.ips)
  * WIN: Event Viewer → Windows Logs → Application, filter event id 1000
    (faulting module) + `%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive`
  * UBU: `journalctl -e --since "1 hour ago" | grep -i -A8 segfault`,
    `ls /var/crash`, `dmesg | tail -40` (OOM kills: `grep -i oom`)

### D2. GUI launch matrix (each = separate observation)

| # | Scenario | Command (per OS) | Expected |
|---|----------|------------------|----------|
| D2.1 | cold start default | `python3 run.py` | GUI < 8 s |
| D2.2 | cold start headless UBU | `xvfb-run -a python3 run.py` | starts |
| D2.3 | validation suite | `python3 run.py --validate` | rc 0 |
| D2.4 | CLI sim | `python3 run.py --cli` | completes/write run dir |
| D2.5 | GPU window spawn (after D2.1) | click "Open PyVista 3D Window" | window < 10 s |
| D2.6 | rapid param typing into fields | 30 edits in 15 s | no visible freeze (loop-latency probe F7.2) |
| D2.7 | 5k+ node mesh ingest via CAD select | load `stl/Main.stl`, generate mesh at 5k budget | responsive |
| D2.8 | 50k node budget mesh gen | same with 50k | UI stays live (mesh gen now threaded) |

For each row where the host cannot run the command, record `SKIPPED (not
this host)` and the equivalent cmd for continuation elsewhere.

### D3. Known crash-signature triage table

While collecting D1-D2 evidence, match stderr against these — each match is a
finding with root cause traced to code:

| Signature | Meaning | Anchor |
|-----------|---------|--------|
| `UnicodeDecodeError: 'charmap' codec` | WIN cp1252 decoding of UTF-8 solver stdout | C2.3/C4.1 |
| `AttributeError: module 'os' has no attribute 'killpg'` | stopping sims on WIN | C3.1 |
| `TclError: no display name and no $DISPLAY` | UBU CLI/SSH headless launch; mpl/Tk order | B5.2 |
| `ImportError: libGL.so.1` / X init failures | UBU VTK without GL packages | B6 |
| `PermissionError [WinError 32]` in safe_copy | watcher locks (A4) + orphan solver | C2.1 |
| `ModuleNotFoundError: No module named 'gui'` | `-c` runner cwd/file injected sys.path (waam_lab C6.1) | |
| `ModuleNotFoundError: shapely` | slicer sibling optional deps | C3.7 |
| `json.decoder.JSONDecodeError` reading parameters.json partial write during crash | D2.4 | |
| FreeFEM `Erreur/Fatal error` banners (French; not an exception text to match only on "error") | solver bad-script | F-G2 |
| `_tkinter.TclError: image "pyimage1" already exists` | duplicate Tk roots during theme/viewport reload race | C7 |

### D4. Reproducers to execute on this host (choose based on host)

- [ ] D4.1 UTF-8 stdout death: run the pipe probe with a child emitting
  `Tmax=1250 °C` then feeding it through `for line in proc.stdout` **without**
  encoding fix on WIN (or `LC_ALL=C` on UBU to force ASCII errors) — record
  traceback and whether the GUI's log thread dies silently (all `after`
  pending callbacks stop). **[RECORD]** (This is a direct BOTTLENECK→"GUI
  frozen during sim" converter, worth reproducing on each OS.)
- [ ] D4.2 Orphan-child repro on WIN (if a WIN agent runs this):
  start sim → Stop Simulation → `tasklist /FI "IMAGENAME eq FreeFem*"`,
  then immediately rerun. Expect `WinError 32`/`;5` collision. **[RECORD]**
- [ ] D4.3 OOM/swap sweep: run a 200k-node engine target on a sweep thread
  while watching `free -h` / Win memory; record RSS peaks. Crash if
  malloc < 8 GB. Atmospheric but still record.

### D5. Live GUI instrumentation while exploring

- [ ] D5.1 Tkinter event-loop latency probe (peak main-thread block) while
  executing D2.6-D2.8:
  ```bash
  python3 scripts/agent/tk_latency.py   # Appendix 3; injects into live loop? No: popen as child with probe
  ```
  Baseline target: `p99 <= 16 ms`; the previous fix session recorded
  `_schedule_render()` at `0.026 ms` — any regression > 1 ms = finding.
- [ ] D5.2 py-spy sampling of a 60-second GUI activity burst:
  ```bash
  pip install py-spy 2>/dev/null; py-spy record -p <pid> -d 60 -o docs/audit/gui_flame.svg --format speedscope
  top-n by selftime → cloud: always cite the top-10 selftime lines in AUDIT_BENCHMARKS.md.
  ```

---

## 7. PHASE E — waam_output FORENSIC SWEEP (feed the sim results)

Purpose: the user explicitly asked: "feed in our sim results there are many
in waam_output itself." The run history is evidence of real-world
bottlenecks/crashes; parse ALL of it.

Budget: 2.5 h (79 run dirs at root).

### E1. Full inventory manifest (automated, one pass)

- [ ] E1.1 Build the manifest:
  ```bash
  python3 scripts/agent/scan_waam_output.py   # Appendix 3
  ```
  Outputs (into `docs/audit/`):
  * `runs_manifest.csv` — one row per file under every run dir with
    run_id, relpath, bytes, mtime
  * `runs_summary.csv` — one row per run dir:
    `run_id | started_at(derived) | dirs | n_files | bytes_total |
    has_sim.log | sim.log_lines | sim.log_rc_line |
    has_parameters.json | has_run_summary.json | rc | stream_exit |
    has_plots | plots_count | has_visual_outputs | vtu_count | vtu_bytes_max |
    has_openfoam_log | openfoam_exit_time | str(Courant#>1 count) |
    wall时长 (from layer_pass_times.txt sum) | has_report.html`
  * `error_matches.csv` — every line matching the §E3 library + run_id + line_no
  * `slow_layers.csv` — per-run per-layer pass time with z-score vs run median
- [ ] E1.2 Sanity-check totals: `wc -l docs/audit/*.csv` + run count vs
  `ls waam_output | wc -l` (baseline 79). **[RECORD]**

### E2. Per-run expectation model (what a COMPLETE run looks like)

For every run, PASS/FAIL each expectation (script handles automatically;
agent spot-checks 3 runs by hand):
1. `FreeFEM/sim.log` present AND contains a final
   `EXECUTION FINISHED - RETURN CODE: <n>` line.
2. `rc == 0` (or rc∈{258,269,...}→ known auto-heal territory, log
   `core/solver_diagnostics.py` category).
3. `run_summary.json` exists with `mesh.n_nodes`/`mesh.n_tets` consistent
   with `sim.log`'s mesh count lines (they must match; mismatch = the
   solver/healrace overwrote — an S2 DATA-QUALITY).
4. `plots/` non-empty: expect ≥ 6 `.png` (per `postprocess/plot_generator.py`).
5. `visual_outputs/` contains at least one `waam_*.vtu` > 0 bytes and
   `waam.pvd`; record size of largest.
6. `toolpath.txt` point count = header `N` on first line & layer count ≥ 1.
7. `layer_pass_times.txt`: count of non-header == `toolpath` layer count;
   each > 0.
8. If `sim_openfoam.log` exists (same dir): ends with `ENDDICT` / no
   hanging last line; count `Courant Number` and time rounds.

### E3. Error & anomaly regex library (apply to every log)

Build the library as a Python list used by scan_waam_output.py:

```
FreeFEM   : ^Erreur, Fatal (error|Error|error:), (OutOfMem|out of memory),
            negative matrix dimension, SIGSEGV, exit code
Meshing   : Mesh Load Error, (meshio|gmsh) (error|warning), degenerate
            edge/face, non-manifold, aspect [Rr]atio
OpenFOAM  : FATAL, divergence detected, floating point exception
Courant   : Courant Number.*mean:([0-9.]+) value:([0-9.]+)  (& flag >1)
Thermal   : Tmax=([0-9.]+)   (track max; a > 6000 spike = unphysical)
Layer     : --- Layer (\d+)/(\d+)   (progress anomalies: resets, skips)
Exit      : EXECUTION FINISHED - RETURN CODE: (\d+)
AutoHeal  : AUTO-HEAL, SOLVER ERROR DIAGNOSIS (category splits)
Python    : Traceback (most recent call last), UnicodeDecodeError,
            TclError, PermissionError, WinError
```

Every hit pushes into `error_matches.csv`; agents then cluster by regex and
emit the Top-10 table in the report with counts and example run IDs.

### E4. Timing analytics (latency forensics from real runs)

- [ ] E4.1 Layer-pass time distribution per run → the solver's pacing
  evidence:
  * Compute median pass time μ and max/μ ratio r per run.
  * r > 3 → flag `SUSPECT-LAYER-STALL` (interpass dwell bug, mesh-io stall,
    or thermal sweep paging on WIN/UBU).
- [ ] E4.2 Wall-time cross-machine divergence: for runs whose
  `parameters.json` are parameter-equal (tolerances §Script-described near
  E4.5 across machines), tabulate medians by host? CANNOT KNOW the host
  from the run dir — infer from path style subtleties (e.g. `C:\` copies
  show `.lnk`/backslash export artifacts) or from `run_summary.json` if
  the summary records platform. Record whatever distinguishing fields exist
  (search `sim.log` header timestamp fields). **[RECORD]**
- [ ] E4.3 Time-to-first-layer estimation vs Solver:
  `sim.log` timestamps (if any) minus `run_dir` mtime → solver startup
  latency; > 5 s on WIN = buffering/AV finding.
- [ ] E4.4 Verification of the throttle-region performance claims (from the
  fix session): locate the post-fix runs (mtime == today) and confirm
  no `UnicodeDecodeError`/layout regressions in their logs.
- [ ] E4.5 Parameter clustering: emit `params_clusters.csv` mapping every
  run into a tuple of (heat_source, n_layers, mesh budget, material) so
  E4.2 comparisons test parameter-equal cases only. **[RECORD]**

### E5. waam_output anomalies to hunt specifically (based on code knowledge)

| Anomaly | How to detect | Why it matters |
|---------|---------------|----------------|
| `.mesh` copies inside run dirs WITHOUT their source STL | `parameters.json.stl` matches local `stl/` files? | cross-machine open breaks when STL is not synced |
| toolpath.txt z-gaps > hz | parse z column | slicer API mismatch |
| layer_pass_times sum ≠ `estimated_time_min` in toolpath summary | compare | kinematics mismatch (S2) |
| `waam_domain.mesh` (structured) node count ≠ `run_summary.json.n_nodes` | parse both | heal pipeline double-write (S2) |
| VTU size == 0 | `find` | postprocess crashed after 90% |
| `parameters.json` JSON invalid | try json.loads | crash mid-write |
| sim.log HTML log truncated at exactly N=8k | line count | pipe read-bindow |

### E6. Map and keep 5 reference runs

Select by criteria and copy NOTHING (evidence stays in place); just list
their `run_id` in AUDIT_REPORT.md §"Reference runs":
* one healthy big run (nodes ≥ 5k, rc 0, plots ≥ 6)
* one auto-heal run (EXIT 258 / [AUTO-HEAL] present)
* one openfoam run (if any)
* one smallest run (regression floor)
* one anomalous run (stalled layer or rc 0 with missing VTU)

---

## 8. PHASE F — PERFORMANCE BENCH & BOTTLENECK MATRIX  (budget: 3 h)

Every bench script goes to `scripts/agent/`, writes CSV rows appended to
`docs/audit/AUDIT_BENCHMARKS.csv` with columns:
`bench_id, host, os, cpu, command_hash, metric, value, unit, note`.

### F1. Teach-machine benches (thread/fork off the GUI)

- [ ] F1.1 Mesh parse `bench_parse_mesh.py`:
  measure `parse_fea_mesh_or_none` FIRST call vs CACHED call on every
  `waam_output*/imported_*.mesh` (baseline session recorded 13.2 ms / 0.02 ms;
  worst file expected ~3 s first, < 1 ms cached). Record nodes+tets counts.
- [ ] F1.2 Direct loader bench `bench_cad_load.py`: time
  `load_any_cad_geometry` (first vs cached) on `stl/Main.stl`,
  `stl/cube_80mm.stl`, `stl/7mmx80` preview `.stl`, plus a STEP if present.
  Also bench `trimesh.load(force='mesh')` alone to separate OS loader cost.
- [ ] F1.3 Slicer bench `bench_slicer.py`: `slice_geometry_to_toolpath` on
  `cube_80mm.stl` (pattern contour, 3 perimeters) ×3, report mean±std, max
  lay, points; on WIN compare against Defender ON (A4.2 value) — this has
  historically been the "slicing is slow" complaint.
- [ ] F1.4 Mesh gen bench `bench_mesh_gen.py`: `generate_waam_mesh` for
  (nx,ny,nz) targets ≈ 5k and 50k nodes; measure wall time + RSS (threads
  must run OFF the Tk thread; if anyone reports "mesh gen freezes UI," re-run
  through GUI path F4.3 to see whether the thread chin dropped).
- [ ] F1.5 EDP build bench: `EDPBuilder(params).save()` on a fully collected
  param set ×50 loops (p50/p95).
- [ ] F1.6 Viewport render bench `bench_viewport.py` (headless-safe
  `xvfb-run` on UBU): with `EmbeddedMeshViewport`'s **worker** function
  measured directly via `_build_offscreen_frame(params)` — we already know
  the UI stays responsive; this measures the worker pipeline itself:
  * cold plotter construct + screenshot on a 5k-node box mesh
  * warm repeat (same sig → skip verify) must return None
  * eight distinct camera azimuth renders: per-frame p50/p95 wall
  * with `stl_file` vs `.mesh` CAD (different data path)
- [ ] F1.7 GPU-window spawn bench: total time from click-equivalent
  (parent `launch_pyvista_gpu_window`) to child first frame; decompose:
  npz save, subprocess boot, pyvista import in child, first show. WIN note:
  each spawn pays Defender scan (~0.5-2 s) — record against A4.2.

### F2. Profiling sweep (mini-flames under controlled loads)

- [ ] F2.1 cProfile the 6 bench scripts above in one shot:
  ```bash
  python3 -m cProfile -o docs/agent_prof.out scripts/agent/bench_viewport.py
  python3 - <<'PY'
  import pstats; p=pstats.Stats("docs/agent_prof.out"); p.sort_stats("cumulative").print_stats(25)
  PY
  ```
  Keep top-10 cumulative tables in AUDIT_BENCHMARKS.md.
- [ ] F2.2 py-spy of the GUI during scripted interaction (D5.2).

### F3. Matplotlib costs (UBU/WIN giant = classic)

- [ ] F3.1 Draw cost table: measure `canvasO.draw()` on the FEA preview for
  styles: Nodes+Cells / Shaded / Wireframe / Cross-Section on the 2k, 5k,
  12k node meshes (from waam_output real files). Expect solid-shading with
  >5k polys > 120 ms on UBU (llvmpipe) — a BOTTLENECK for interaction.
- [ ] F3.2 `draw_idle` dedup wiring verification: fetch
  `_redraw_fea_mesh_inner`'s signature and count `axO.clear()` calls for 10
  parameter refreshes; must be <=1 clear per visual change. **[RECORD]**
- [ ] F3.3 Slicer GUI full `update_mesh()` repeat-call latency (must be ≤ 5 ms
  on second call thanks to fast paths). **[RECORD]**

### F4. Tk event-loop latency matrix (the "does the UI thread ever block" test)

- [ ] F4.1 `scripts/agent/tk_latency.py` while exercising: CAD select, 25
  param edits, viewport orbit drag for 5 s, GPU window open, sim start/stop,
  log tab reload of the biggest `sim.log` (18 万char+). Capture
  block-p50/p95/p99 per scenario. Threshold: p95 < 16 ms; else finding.
- [ ] F4.2 Log-tab reload: `log_reload(app)` timing on the maximum-size
  `sim.log` found in waam_output (expect bulk grouped insert ≤ 60 ms; the
  pre-fix per-line version took ~10 s on 100k-line logs — if > 200 ms the
  batching broke). **[RECORD]**
- [ ] F4.3 Stream tick drain: synthetic 12k lines/s feed for 3 s (script
  from Appendix 3) into `_log_batch`; measure per-tick and the Tk drop
  (assert processing batch ≥ 350 lines and buffer capping kicked at 6000).

### F5. VTK rendering mode study (UBU headless/win-RDP)

- [ ] F5.1 Repeat B6.1 bpy but record ALSO: fps for 30 rendered 90° orbit
  frames for both off-screen AND interactive-window modes.
- [ ] F5.2 Election: which display/OSes REQUIRED OSMesa/EGL pip builds; if
  `pyvista.start_xvfb()` works with no system gain, recording that lets the
  framework's docs add a platform note.
- [ ] F5.3 Software GL: `LIBGL_ALWAYS_SOFTWARE=1` frame time (llvmpipe vs
  NVIDIA/AMD) — post as the reference floor.
- [ ] F5.4 WSL2/WSLg specifics: `wslg` exposes Wayland; Tk backends might
  downgrade; record both engines.

### F6. Windows I/O aggravators

- [ ] F6.1 Small-file IO (see A4.3) — if > 1 ms/file on WIN, surface the
  actual recommendation: run-dir exclusions.
- [ ] F6.2 Subprocess spawn (`Popen('python -c pass')`) cost ×20 — WIN
  typical 30-150 ms; record.

### F7. Deterministic flicker detectors

- [ ] F7.1 Log viewer: insert 100k lines via `_log_batch` path, measure
  MB of Text widget usage; trim invariant (must cap ≈ 6000 lines).
  **[RECORD]**
- [ ] F7.2 Idle loop: after reaching steady state, run 10 s with zero
  interaction while sampling `after` dispatch delay. There should be near
  zero background callbacks (default_theme redraw-once). Any tick loop
  discovered (there ARE known: `_poll_stream` style timers left running) →
  record loop + frequency.

### F8. Proposed threshold policy (write into report, agent proposes, user accepts)

| Metric | Threshold (good) | Investigate at | Anchor |
|--------|------------------|----------------|--------|
| Tk event block p95 | < 16 ms | > 30 ms | F4.1 |
| First viewport frame | < 1.5 s | > 4 s | F1.6 |
| Cached parse | < 5 ms | > 50 ms | F1.1 |
| First parse (2k nodes) | < 100 ms | > 3 s | F1.1 |
| 50k-node mesh gen | < 12 s | > 60 s | F1.4 |
| Spawn child overhead | < 80 ms | > 1 s | F6.2 |
| sim first-chunk visible | < 2 s | > 10 s | B2.3 |

---

## 9. PHASE G — SOLVER/BACKEND CRASH & INCOMPAT TESTS  (budget: 2 h)

These are the end-to-end reality checks; `waam_output/agent_<ts>/` new
folders may be created by the agent run.

- [ ] G1.1 Run full CLI pipeline: `python3 run.py --cli` — collect:
  rc, wall time, first-chunk latency, exit `sim.log` summary lines. **[RECORD]**
- [ ] G1.2 `--validate` physics suite (tests exist under `tests/`):
  `python3 run.py --validate` (must rc 0).
- [ ] G1.3 The small mesh with the largest node budget available on disk:
  re-run the sphere case via `run.py --stl stl/...(choose)` — compare node
  count, rc results vs the historical run imported in E6. Divergence ⇒
  solver nondeterminism OR post-fix regression — report as DATA-QUALITY.
- [ ] G1.4 Exit-code matrix (on this host): run each of
  * normal run (expect 0)
  * malformed params (`h_bead = -1`) injection via CLI params — expect
    diagnostic engine category; confirm `FreeFEMDiagnosticsEngine` catches
    and `AUTO-HEAL` behaves; record actual rc + banner.
- [ ] G1.5 OpenFOAM flow (UBU/WSL2 only otherwise SKIP): run the sample
  beamWeldFoam case through GUI-equivalent controller — capture
  `sim_openfoam.log` tails: `Time =` rate, ENDDICT present, measure
  `Courant>1` count. **[RECORD]**
- [ ] G1.6 ParaView launches for VTU/PVD produced above — confirm process
  up (headless mode: use `--offscreen` pvpython pargs? record).
- [ ] G1.7 The heal loop: force a run whose exit is auto-healable (derived
  from historical runs in E6); verify the auto-retry inflight once; exact
  `after(200, run_simulation(is_auto_retry=True))` second-pass args recorded.

---

## 10. REPORT ASSEMBLY

### 10.1 Severity scale for every OBS

| Sev | Meaning |
|-----|---------|
| S0 | Data loss, corrupted results, or blocks the app from functioning at all |
| S1 | Major BOTTLENECK/CRASH with common use; usability disaster |
| S2 | Divergent/inconsistent behavior, degraded workflow |
| S3 | Cosmetic/latent; no user impact in current flows |
| S4 | Informational |

### 10.2 `AUDIT_REPORT.md` skeleton (write fully, delete the blanks)

```markdown
# WAAM Deep-Audit Report — <date>
## 1. Executive Summary
   *(top 5 findings, each two lines: mechanism + evidence OBS id)*
## 2. Host Matrix
   | | macOS | Windows | Ubuntu | WSL2 |
   |---|---|---|---|---|
   | Python | | | | |
   | GUI first frame | | | | |
   | cached parse (ms) | | | | |
   | ... (from AUDIT_BENCHMARKS.csv pivots) |
## 3. Findings (S0..S1 first)
   For each: OBS ids - Mechanism - Evidence - Affected OSes - Fix Proposal -
   Regression Test
## 4. Simulation Forensics Summary
   79 runs swept: findings table: anomaly -> count -> example run_ids
   Top-10 error regex counts; layer-stall table; reference runs (5).
## 5. Bottleneck Matrix — what is slow and HOW slow (per-OS)
## 6. Incompatibility Ledger (WIN vs UBU vs MAC) — one row each
## 7. Proposed Fix Tickets (P-01..P-nn with severity, effort S/M/L)
## 8. Verification Gate results (Phase I)
## 9. Open Questions for the Human
## 10. Appendix: full CSV listing, gzip of logs under docs/audit/artifacts/
```

### 10.3 Proposed-fix ticket format (force this discipline)

```
P-<nn> | sev | class | src anchor (file:line) | mechanism (cause chain)
one-line fix
verify-by: <exact bench/pytest command>
risk: <what could break>
effort: S/M/L
```

---

## 11. PHASE I — VERIFICATION GATE (after any applied fix)

Run ALL below; each must be PASS (reusable by any future session):

- [ ] I1 `pytest tests/ -x -q` → 5 passed (do not touch tests to make them
      pass; a failing physics test after a fix is a blocker, not a target).
- [ ] I2 `ruff check gui/ core/ ../waam_lab/waam_slicer/slicer_core.py`
      → All checks passed (project selects E9/F63/F7 only).
- [ ] I3 AST parse of all touched files.
- [ ] I4 `scripts/agent/regression_suite.py` (script exists in Appendix 3)
      executes and asserts the §0.6 baseline table + F8 thresholds
      (INI captures baseline regression).
- [ ] I5 GUI smoke (`/tmp/waam_smoke*.py` equivalents from the fix session,
      kept under `scripts/agent/`) — frame pipeline + fast-path numbers.
- [ ] I6 Cross-platform deltas: if allowed hosts, run the I3-I5 on second
      OS; otherwise mark `PENDING (other host agents`).
- [ ] I7 Update AUDIT_STATE.md checkbox for this checklist's phase rows.

---

## 12. APPENDIX 1 — KNOWN AGENT ANCHORS (current code state as authored date)

These were verified during the 2026-10-24 fix session; the auditor
re-verifies each rather than assuming:

| Anchor | File | Condition |
|--------|------|-----------|
| Async viewport | `gui/widgets/mesh_viewer_3d.py` `_schedule_render`, `_render_loop`, `_apply_frame`, `_build_offscreen_frame` | UI thread pure snapshot; frames posted via `after` |
| Geometry cache | `mesh_viewer_3d.py:_CAD_CACHE` + `_faces_lod` | key (abspath, mtime_ns, size, sub_hz, layer_h) |
| LOD caps | `VIEWPORT_MAX_WIREFRAME_FACES=30000`, `VIEWPORT_MAX_FACES_LOD=60000` | wireframe disabled above 30k |
| Mesh parse cache | `../waam_lab/waam_slicer/slicer_core.py: parse_fea_mesh_cached` (FR entry: `parse_fea_mesh_or_none`) | lock + 4-slot LRU + copy isolation |
| Slicer fast paths | `waam_slicer/gui.py:load_fea_mesh, update_mesh, _redraw_fea_mesh_inner` | stat-match skip + signature dedup |
| Batched sims stream | `gui/controllers/simulation_controller.py: poll_stream` | 25 ms, 350-line cap |
| Batched foam stream | `gui/controllers/openfoam_controller.py: _flush` | 0.25 s flush, 400-line cap |
| Batched claude stream | `gui/dialogs/claude_dialog.py` `_flush_lines/_flush_time_ui` | 80-line or 0.25 s |
| Threaded mesh gen | `gui/controllers/mesh_controller.py:generate_waam_mesh` | worker thread + `after()` marshaling |
| Bulk log reload | `gui/tabs/sim_log_tab.py:log_reload` | contiguous tag groups |
| 25 ms debounce | `gui/app.py:_schedule_full_refresh` | whole downstream chain |
| Per-line residual hazards | `stop_simulation` (`os.killpg`), `Popen` sans `encoding=`, `./waam_output` cwd-relative writes, `script -q` bash dependency | candidates, NOT yet fixed |

Remainder hazards to check FIRST on WIN/UBU (from the same session):
1. `Popen(text=True)` without `encoding='utf-8', errors='replace'` — unzip
   on WIN→ UnicodeDecodeError kills the logging worker silently (S1).
2. `os.killpg` on WIN stop paths — orphan FreeFEM after Stop (S1).
3. Optional deps: `shapely`, `meshio`, `networkx` module imports → slicer
   feature silently swaps to fallback (S2).
4. Case-sensitivity of `stl/` filenames vs referenced literals (UBU) (S2).
5. `./waam_output` cwd-relative writes when launching from elsewhere (S2).

---

## 13. APPENDIX 2 — OS DIFFERENCE CHEAT-SHEET (`WIN` vs `UBU` vs `MAC` quirks that actually matter here)

| Domain | macOS | Ubuntu | Windows | Impact on this app |
|--------|-------|--------|---------|--------------------|
| FS case | case-insens (APFS) | case-SENS (ext4) | case-insens (NTFS) | stl filename mismatches silently pass on mac/w |
| stdout decode | utf-8 | utf-8 (ASCII if LANG=C) | cp1252 default | solver `°`,`µ`,`Erreur` corruption/crash |
| pipe buffering | fine | fine | console QUOTED unless unbuffered helper | FreeFEM output appears "dead" |
| pkg GL | Metal via MoltenGL (VTK ok) | X11/EGL; needs `libgl1`, `libx11-6`, `xvfb` for headless; llvmpipe slow | ANGLE/AMD; RDP can cap features | viewport FPS, GPU window |
| process mgmt | killpg OK | killpg OK | NO killpg; use `taskkill /T /F` or `CREATE_NEW_PROCESS_GROUP` + `terminate()+wait(+kill)` | stop-sim orphans |
| bash | yes | yes | absent (or WSL) | OpenFOAM runner not native on WIN |
| `script` util | present (BSD argv differs) | present | absent | C3.7 runner branch |
| Desktop dir | exists | exists (i3?) | often Roamed | file dialog initialdir |
| Sleeping AV | none | none | Defender real-time | small-file IO + spawn tax |
| tempdiring | `$TMPDIR` | `/tmp` (sticky bit) | `%TEMP%` | pyvista param files |

---

## 14. APPENDIX 3 — AGENT TOOLKIT SCRIPTS (create these in `scripts/agent/`, all are *new* files, ~10-50 lines each; SPEC given, agent implements unless already present)

1. `dep_matrix.py` — imports + versions, REQUIRED/OPTIONAL table, exit 0.
2. `fs_latency.py` — 1000×1 KB append+fsync to temp dir; ms/line; AV-detector.
3. `pipe_pulse.py` — fork child that sleeps 1 s then prints 200 lines;
   measure first chunk latency through `Popen(text=True)` + default
   `build_unbuffered_command()` (use `stdlib` unbuffered flag `-u`); assert < 2 s.
4. `stdout_utf8_probe.py` — child prints `θ ° µ Erreur` lines; reads
   `for line in proc.stdout` twice: (a) default encoding, (b) with
   `encoding='utf-8', errors='replace'`; print which survives. Record mode.
5. `vtk_capability.py` — tries offscreen modes (a)-(d) B6.1; prints
   mode, ok/fail, first-frame ms, orbit-fps; writes capability JSON.
6. `tk_latency.py` — run.py subprocess + ctypes-injected after-drift probe;
   scenarios flag param; writes p50/p95/p99 rows.
   Simpler alternative accepted: drive `EmbeddedMeshViewport` +
   `update_mesh` timing only.
7. `scan_waam_output.py` — §E1, full manifest + summaries + regex matches.
8. `bench_parse_mesh.py`, `bench_cad_load.py`, `bench_slicer.py`,
   `bench_mesh_gen.py`, `bench_edp_build.py`, `bench_viewport.py` — F1 suite.
9. `tk_flood_test.py` — synthetic 12k lines/s into `_log_batch` timer (F4.3).
10. `log_reload_bench.py` — largest sim.log reload timing (F4.2).
11. `regression_suite.py` — Phase I assertions (0.6 baseline + F8).
12. `spawn_overhead.py` — Popen cost ×20 (F6.2).

Every script must (a) be runnable on all three OSes or record host-gated
skip, (b) print a single machine-parseable line at the end:
`RESULT <bench_id> <metric>=<value>`.

---

## 15. APPENDIX 4 — RUNBOOK DECISION TREE (symptom → phase)

```
Symptom observed                       → Next action
---------------------------------------+-------------------------------------
"Frozen window" (UI unresponsive)      | F4.1 tk_latency during repro step
"Slow everything, sluggish all OSes"   | F1.x bench scripts, drop-in F8 table
"Sim started, nothing prints"          | B2.3 pipe_pulse + C2.3 encoding probe
" crashes on Linux only"               | B5/B6 headless, C5 Tcl
"Crashes/degrades on Windows only"     | C2.x subprocess + C4 encoding tables
"Results of sims wrong/incomplete"     | Phase E sweep, E5 anomaly hunt
"Simulation complete but no plots"     | E2 expectations + plot rc mining
"OpenFOAM run leaves dead child"       | C2.1 + G1.5 record
"Works on my machine" disputes         | F8 thresholds table + host matrix
"Auto-heal loop runs forever"          | G1.7 + solver_diagnostics cats
```

---

## 16. APPENDIX 5 — AUDIT_STATE.MD TEMPLATE (progress tracker)

Copy at session start; update after every phase; commit at end (if mode
allows) EXCEPT wedge: user decides commit timing.

```markdown
# WAAM Deep-Audit — State
Mode: AUDIT-ONLY
Start: <UTC ts>  Hosts: <list>
| Phase | PLANNED | Status | Obs count | Key blockers |
|-------|---------|--------|-----------|--------------|
| A     |  12     |        |           |              |
| B     |  18     |        |           |              |
| C     |  30     |        |           |              |
| D     |  12     |        |           |              |
| E     |  12     |        |           |              |
| F     |  18     |        |           |              |
| G     |  7      |        |           |              |
| H     |  4      |        |           |              |
| I     |  7      |        |           |              |
Wedges: <list>
```

---

## 17. SESSION END CHECKLIST

- [ ] All OBS entries written (spot-check 5 random steps: do they have EVIDENCE?)
- [ ] AUDIT_REPORT.md has: exec summary, host matrix, S0-S1 findings with
      anchors, waam_output sweep summary, pending user questions.
- [ ] No file outside `docs/audit/`, `scripts/agent/`,
      `waam_output/agent_*/` was created or modified in AUDIT-ONLY.
- [ ] `waam_output` byte-identical to session start (verify via
      `du -sb`-equivalent + file count).
- [ ] Diff summary (if any fix mode): list of files changed + tests that
      gated each change.
- [ ] Hand-off note: next steps for the human (highest-leverage single fix).

> End of checklist. The agent's north star: **every claim has evidence, every
> fix has a test, nothing in waam_output gets hurt.**
