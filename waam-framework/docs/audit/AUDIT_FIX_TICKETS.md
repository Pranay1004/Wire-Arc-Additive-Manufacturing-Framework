# WAAM Deep-Audit — Expanded Fix Tickets (Phase H)

Each ticket follows: P-<nn> | sev | class | src anchor | mechanism | one-line fix | verify-by | risk | effort

---

## P-01 | S1 | CRASH | gui/dialogs/claude_dialog.py:67 | `Popen(text=True)` without encoding → WIN cp1252 decodes UTF-8 solver output (θ, °, µ, Erreur) as mojibake → UnicodeDecodeError kills logging thread silently → GUI appears frozen
**Fix**: `Popen(..., text=True, encoding='utf-8', errors='replace')`
**Verify**: `python scripts/agent/stdout_utf8_probe.py` on WIN; run sim with UTF-8 output, confirm no decode crash
**Risk**: Low — adds explicit encoding; `errors='replace'` guarantees no crash
**Effort**: S (1 line × 4 files)

---

## P-02 | S1 | CRASH | gui/controllers/simulation_controller.py:475 | Same as P-01 — simulation log capture
**Fix**: `Popen(..., text=True, encoding='utf-8', errors='replace')`
**Verify**: Same as P-01
**Risk**: Low
**Effort**: S

---

## P-03 | S1 | CRASH | gui/controllers/openfoam_controller.py:155 | Same as P-01 — OpenFOAM log capture
**Fix**: `Popen(..., text=True, encoding='utf-8', errors='replace')`
**Verify**: Run OpenFOAM case on WIN; confirm log streaming works
**Risk**: Low
**Effort**: S

---

## P-04 | S1 | CRASH | gui/controllers/openfoam_controller.py:218 | Same as P-01 — OpenFOAM runner with capture_output
**Fix**: `Popen(..., capture_output=True, text=True, encoding='utf-8', errors='replace', ...)`
**Verify**: Same as P-03
**Risk**: Low
**Effort**: S

---

## P-05 | S1 | HANG | gui/controllers/simulation_controller.py:632-633 | `os.killpg` guarded by `hasattr`; on WIN falls to `proc.terminate()` only → FreeFEM child threads survive → next run `PermissionError: [WinError 32]` in `safe_copy_file` retry loop
**Fix**: Implement Windows-safe kill tree:
```python
if sys.platform == "win32":
    import subprocess
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
else:
    if hasattr(os, "killpg"):
        os.killpg(os.getpgid(proc.pid), 9)
```
**Verify**: On WIN: start sim → Stop → `tasklist | findstr FreeFem` → confirm no orphans → rerun sim → no PermissionError
**Risk**: Medium — `taskkill` requires admin? (usually not for own processes); test on WIN
**Effort**: M (new helper in `core/platform_adapter.py`)

---

## P-06 | S1 | BOTTLENECK | gui/dialogs/claude_dialog.py:94-137 (8 sites) | Per-line `after(0, app._log, ...)` in worker thread → floods Tk main thread at solver throughput (10k lines/s) → GUI freeze
**Fix**: Route ALL through existing `_flush_lines`/`_flush_time_ui` batch queue (already present in file). Remove raw `after(0, app._log)` calls.
**Verify**: Run `python scripts/agent/tk_flood_test.py` → confirm 12k lines/s handled without p95 > 16ms
**Risk**: Low — uses existing batching infrastructure
**Effort**: S (replace 8 calls)

---

## P-07 | S1 | BOTTLENECK | gui/controllers/mesh_controller.py:634-660 (10 sites) | Per-line `after(0, app._log, ...)` in CAD/mesh workers → same flood
**Fix**: Use `simulation_controller.poll_stream` pattern: `queue.Queue` + 25ms timer, 350-line batch cap, `_log_batch` groups tags, buffer trim at 6000 lines
**Verify**: Same as P-06
**Risk**: Low
**Effort**: S-M (add queue + timer to mesh_controller)

---

## P-08 | S1 | BOTTLENECK | gui/controllers/simulation_controller.py:513-591 (20+ sites) | Per-line `after(0, app._log, ...)` in auto-heal/diag/postprocess paths → same flood
**Fix**: Same as P-07 — consolidate through `poll_stream` batch queue
**Verify**: Same as P-06
**Risk**: Low
**Effort**: S-M

---

## P-09 | S2 | INCOMPAT | gui/app.py:3089,3195; gui/controllers/mesh_controller.py:625; gui/widgets/waam_3d_studio.py:177,245; gui/widgets/mesh_viewer_3d.py:473; mesh/intelligent_mesher.py:229; mesh/slicer_api.py:1042; ../waam_lab/waam_slicer/gui.py:234,253,254,2078 | 12 cwd-relative `./waam_output` / `./stl` → launching from `$HOME` or `C:\` writes outputs to wrong dir
**Fix**: Resolve relative to repo root: `Path(__file__).resolve().parents[N] / "waam_output"` or require absolute `output_dir` in parameters
**Verify**: `cd /tmp && python /path/to/run.py --cli` → outputs in repo `waam_output/`, not `/tmp/waam_output/`
**Risk**: Low — path resolution change only
**Effort**: M (12 sites across 8 files)

---

## P-10 | S2 | INCOMPAT | gui/tabs/mesh_cad_tab.py:84; mesh/stl_pipeline.py:1046; ../waam_lab/waam_slicer/gui.py:170,171,401,402; ../waam_lab/waam_slicer/slicer_core.py:302-303 | Code references `letter_Z_WAAM.stl` and `Main.stl` — neither exists in `stl/` (actual: `z.stl`, `main.stl`)
**Fix**: Option A: Rename `z.stl` → `letter_Z_WAAM.stl`, `main.stl` → `Main.stl` (git mv). Option B: Update all refs to actual filenames. Prefer A for user expectations.
**Verify**: On UBU: `python run.py` → GUI shows default sample → no "file not found"
**Risk**: Low — file rename or string change
**Effort**: S

---

## P-11 | S1 | DATA-QUALITY | waam_output/ (24 runs) | **0/24 runs have plots/*.png** — plot generation pipeline completely broken
**Fix**: Investigate `postprocess/plot_generator.py` — likely matplotlib backend or import issue. Add explicit `matplotlib.use('Agg')` before imports if headless.
**Verify**: `python run.py --cli` → run dir has `plots/*.png` (≥6)
**Risk**: Medium — may involve matplotlib/dependency issues
**Effort**: M-L

---

## P-12 | S1 | DATA-QUALITY | waam_output/ (24 runs) | **Only 7/24 runs have run_summary.json** — summary writer only fires on rc=0 AND mechanics_converged? Many runs rc≠0 or mechanics fail
**Fix**: Ensure `run_summary.json` written for ALL runs (including failures) with `status`, `return_code`, `error` fields. Decouple from mechanics convergence.
**Verify**: All 24 run dirs have `run_summary.json` with schema
**Risk**: Low
**Effort**: S-M

---

## P-13 | S1 | BOTTLENECK | waam_slicer/slicer_core.py slice_mesh | **12.4s runtime, returns empty toolpath** — slicing pipeline broken/slow
**Fix**: Debug `slice_mesh` — check trimesh/shapely imports, layer generation logic. Profile with `cProfile`.
**Verify**: `slice_mesh(cube_80mm.stl, layer_height=0.003)` → returns toolpath with points >0 in <3s
**Risk**: High — core slicing feature
**Effort**: L

---

## P-14 | S2 | INCOMPAT | waam_lab/waam_slicer/gui.py:2078 | `cwd_out = os.path.abspath("./waam_output")` — same cwd-relative issue as P-09
**Fix**: Same as P-09
**Verify**: Same as P-09
**Risk**: Low
**Effort**: S

---

## P-15 | S2 | INCOMPAT | mesh/slicer_api.py:1042 | `for folder in [p.parent, p.parent.parent, Path("./stl"), ...]` — cwd-relative stl search
**Fix**: Same as P-09
**Verify**: Same as P-09
**Risk**: Low
**Effort**: S

---

## P-16 | S3 | COSMETIC | requirements.txt | `ruff` missing from requirements.txt (ruff not installed) but required by CI/lint
**Fix**: Add `ruff` to requirements.txt
**Verify**: `pip install -r requirements.txt && ruff check gui/`
**Risk**: None
**Effort**: S

---

## P-17 | S3 | COSMETIC | requirements.txt | `igraph` optional import fails — not in requirements, used in code?
**Fix**: Add `igraph` to optional requirements or remove import if unused
**Verify**: `python -c "import igraph"` or confirm unused
**Risk**: Low
**Effort**: S

---

## P-18 | S1 | CRASH | core/platform_adapter.py (inferred) | `build_unbuffered_command` used by `pipe_pulse` but returns list-of-list? Script error suggests API mismatch
**Fix**: Audit `build_unbuffered_command` return type; ensure it returns flat `list[str]` for `Popen`
**Verify**: `python scripts/agent/pipe_pulse.py` → no TypeError
**Risk**: Low
**Effort**: S

---

## P-19 | S1 | BOTTLENECK | gui/widgets/mesh_viewer_3d.py | cube_80mm.stl first load 882ms vs others 0.4-1.6ms — trimesh path outlier
**Fix**: Profile `load_any_cad_geometry` for cube_80mm; check if trimesh hitting slow path
**Verify**: `python scripts/agent/bench_cad_load.py` → all first loads <200ms
**Risk**: Low
**Effort**: M

---

## P-20 | S2 | INCOMPAT | bash 3.2.57 on MAC | Ancient bash (2007) — OpenFOAM bashrc sourcing may fail; `bash -lc 'source ...'` behavior differs from bash 4+/5+
**Fix**: Document minimum bash version; test OpenFOAM runner on MAC with bash 3.2; consider requiring bash 4+ via homebrew
**Verify**: `bash --version` on all hosts; OpenFOAM runner works
**Risk**: Medium — affects OpenFOAM only
**Effort**: M

---

## P-21 | S1 | DATA-QUALITY | waam_output/2026-10-21_23-48-26 | Mesh/EDP/toolpath/VTU exist but **NO sim.log** — simulation never executed or log capture failed
**Fix**: Add pre-run validation: check solver binary exists, write sim.log header before spawn, verify log file created after
**Verify**: Re-run that case → sim.log present with `EXECUTION FINISHED` line
**Risk**: Medium
**Effort**: M

---

## P-22 | S1 | CRASH | waam_output/2026-10-16_18-41-08 | FreeFEM syntax error: `+ tpFile +` token in generated EDP → codegen bug
**Fix**: Audit `codegen/edp_builder.py` toolpath file injection; ensure proper escaping/quoting
**Verify**: `python run.py --validate` → 340/340 pass (currently 338/340)
**Risk**: Medium
**Effort**: M

---

## P-23 | S2 | BOTTLENECK | rc=-15 runs (5) | "Exec error: Error opening file" slicer failure → SIGTERM → auto-heal? rc=-15 = SIGTERM (kill)
**Fix**: Trace why slicer dies — likely file permission or missing input. Add slicer stdout/stderr capture to sim.log
**Verify**: No rc=-15 in new runs
**Risk**: Medium
**Effort**: M

---

## P-24 | S2 | CRASH | rc=1/6 runs (7) | "error GROWS with finer dt" + "stalled at 0.39" → nonlinear solver divergence (lagged physics)
**Fix**: Review `core/solver_diagnostics.py` categories; ensure auto-heal triggers for this pattern (mech_max_newton_iter, fixture_stiffness_ratio_z/xy)
**Verify**: Auto-heal runs and recovers; run_summary.json shows healed status
**Risk**: High — solver physics
**Effort**: L

---

## P-25 | S3 | INFO | waam_output/ (24 runs) | **No OpenFOAM runs in history** — `sim_openfoam.log` never generated
**Fix**: Document OpenFOAM as untested path; add CI test if possible
**Verify**: Manual OpenFOAM run produces sim_openfoam.log
**Risk**: Low
**Effort**: M

---

## P-26 | S3 | INFO | waam_output/ | **No AUTO-HEAL or rc=258 in history** — auto-heal path untested
**Fix**: Create test case that triggers auto-heal; verify end-to-end
**Verify**: Run with malformed params → auto-heal triggers → second run rc=0
**Risk**: Low
**Effort**: M

---

## P-27 | S1 | BOTTLENECK | rc=1/6 runs layer times | Median 33-652s per layer — extremely slow; 2026-10-21_23-51-51: 20 layers × 652s median = 3.6h
**Fix**: Profile FreeFEM solver; check mesh density (nz_dep=50+), adaptive_dt off, mech_max_newton_iter=150
**Verify**: Equivalent case completes in <30min
**Risk**: High — solver performance
**Effort**: L

---

## P-28 | S2 | INCOMPAT | gui/widgets/mesh_viewer_3d.py | Tk theme "aqua" via XQuartz on MAC — XQuartz adds latency vs native Cocoa Tk
**Fix**: Ensure Tk uses native Cocoa (`tkinter` default on MAC) not XQuartz; check `DISPLAY` unset
**Verify**: `python -c "import tkinter; r=tk.Tk(); print(r.tk.call('info','patchlevel'))"` → 8.6+ native
**Risk**: Low
**Effort**: S

---

## P-29 | S1 | CRASH | gui/controllers/simulation_controller.py:334 | `open(script_path, "r", encoding="utf-8", errors="replace")` — good; but other opens in codebase use `errors="ignore"` (data loss)
**Fix**: Standardize on `errors="replace"` for all UTF-8 reads; `errors="ignore"` loses data silently
**Verify**: grep for `errors="ignore"` → replace
**Risk**: Low
**Effort**: S

---

## P-30 | S2 | INCOMPAT | mesh/slicer_api.py:1042; gui/widgets/waam_3d_studio.py:177 | STL search paths include `Path("./stl")` and `Path(__file__).resolve().parent.parent.parent / "stl"` — inconsistent resolution
**Fix**: Centralize STL root resolution in `core/platform_adapter.py` or `core/paths.py`
**Verify**: STL loads from any launch dir
**Risk**: Low
**Effort**: M

---

## Summary by Severity
| Sev | Count | Tickets |
|-----|-------|---------|
| S1 | 10 | P-01..08, 11, 13, 21, 22, 27, 29 |
| S2 | 10 | P-09, 10, 12, 14, 15, 20, 23, 24, 28, 30 |
| S3 | 6 | P-16, 17, 18, 25, 26 |

---

## Suggested Fix Order (high leverage first)
1. **P-01..04** (4× encoding fixes) — eliminates WIN crash class, 10 min
2. **P-05** (Windows kill tree) — eliminates WIN orphan class, 30 min
3. **P-06..08** (batching 38 raw after() calls) — eliminates UI freeze class, 1 hr
4. **P-09** (12 cwd-relative paths) — eliminates launch-dir bugs, 45 min
5. **P-10** (STL filenames) — eliminates UBU missing-file, 10 min
6. **P-11** (plots pipeline) — restores plot generation, 2-4 hrs
7. **P-12** (run_summary.json) — restores run metadata, 30 min
8. **P-13** (slicer 12s/empty) — restores slicing, 4-8 hrs
9. **P-22** (EDP syntax bug) — fixes validation, 1 hr
10. **P-24** (solver divergence) — physics fix, weeks
