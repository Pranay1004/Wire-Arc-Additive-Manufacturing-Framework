# WAAM Deep-Audit Report — 2026-10-24

## 1. Executive Summary

**Top 5 findings (mechanism + evidence OBS id):**

1. **WIN crash: UnicodeDecodeError** — 4× `Popen(text=True)` without `encoding='utf-8', errors='replace'`; FreeFEM prints UTF-8 (θ, °, µ, Erreur) → cp1252 decode crash kills log thread silently → GUI "freezes" during sim. **OBS-C01** (S1)
2. **WIN hang: orphan FreeFEM** — `os.killpg` guarded by `hasattr`; WIN falls to `proc.terminate()` only → child threads survive → next run `PermissionError: [WinError 32]` in `safe_copy_file`. **OBS-C02** (S1)
3. **All-OS UI freeze: 38 raw `after(0, app._log)`** — per-line Tk callbacks in worker threads flood main loop at 10k lines/s despite batching in 3 controllers. **OBS-C05** (S1)
4. **Data pipeline broken: 0/24 runs have plots** — `postprocess/plot_generator.py` produces no `plots/*.png`; `run_summary.json` only 7/24 (rc=0 + mechanics converged only). **OBS-E01,E02** (S1)
5. **Cross-platform path breakage: 12 cwd-relative `./waam_output`/`./stl`** — launching from `$HOME`/`C:\` writes outputs to wrong dir; STL refs `letter_Z_WAAM.stl`/`Main.stl` don't exist (actual: `z.stl`/`main.stl`). **OBS-C03,C04** (S2)

---

## 2. Host Matrix

| Metric | macOS (this host) | Windows | Ubuntu | WSL2 |
|--------|-------------------|---------|--------|------|
| Python | 3.14.5 CPython (brew) | ? | ? | ? |
| GUI first frame | <8s (validate OK) | ? | ? | ? |
| Cached parse (ms) | <0.2ms (475-1438×) | ? | ? | ? |
| First parse 2k nodes | 1-129ms | ? | ? | ? |
| 50k-node mesh gen | N/A (needs GUI) | ? | ? | ? |
| Spawn child overhead | 19ms mean / 20ms p95 | ? | ? | ? |
| Sim first-chunk visible | 1.025s (pipe_pulse) | ? | ? | ? |
| VTK offscreen FPS | EGL 1.19s/frame, OSMesa 0.76s | ? | ? | ? |
| Tk theme | aqua (via XQuartz) | ? | ? | ? |
| Bash version | 3.2.57 (ancient) | N/A | ? | ? |
| Disk latency (fsync) | 0.035ms/op | ? | ? | ? |

---

## 3. Findings (S0..S1 first)

### S1 — Critical (10 findings)

| ID | Class | Mechanism | Evidence | Affected OS | Fix Ticket |
|----|-------|-----------|----------|-------------|------------|
| OBS-C01 | CRASH | `Popen(text=True)` no encoding → WIN cp1252 decode crash | 4 files: `claude_dialog.py:67`, `simulation_controller.py:475`, `openfoam_controller.py:155,218` | WIN | P-01..04 |
| OBS-C02 | HANG | `os.killpg` POSIX-only → WIN orphans → `PermissionError` | `simulation_controller.py:632-633` | WIN | P-05 |
| OBS-C05 | BOTTLENECK | 38 raw `after(0, app._log)` in 3 files → Tk flood | `claude_dialog.py` (8), `mesh_controller.py` (10), `simulation_controller.py` (20+) | ALL | P-06..08 |
| OBS-E01 | DATA-QUALITY | 0/24 runs have `plots/*.png` | Phase E sweep | ALL | P-11 |
| OBS-E02 | DATA-QUALITY | Only 7/24 `run_summary.json` (rc=0+converged only) | Phase E sweep | ALL | P-12 |
| OBS-E05 | DATA-QUALITY | Run `2026-10-21_23-48-26` has mesh/EDP/VTU but NO sim.log | Phase E sweep | ALL | P-21 |
| — | CRASH | EDP syntax error `+ tpFile +` token | `2026-10-16_18-41-08` rc=1 | ALL | P-22 |
| — | BOTTLENECK | Slicer 12.4s + empty toolpath | `bench_slicer.py` | ALL | P-13 |
| — | BOTTLENECK | Solver divergence: 20 layers × 652s = 3.6h | `2026-10-21_23-51-51` | ALL | P-27 |
| — | CRASH | `errors="ignore"` loses UTF-8 data silently | `simulation_controller.py:334` vs others | ALL | P-29 |

### S2 — Major (10 findings)

| ID | Class | Mechanism | Evidence | Affected OS | Fix Ticket |
|----|-------|-----------|----------|-------------|------------|
| OBS-C03 | INCOMPAT | 12 cwd-relative `./waam_output`/`./stl` | 8 files, 12 sites | WIN/UBU | P-09 |
| OBS-C04 | INCOMPAT | STL refs `letter_Z_WAAM.stl`/`Main.stl` missing | `stl/` has `z.stl`/`main.stl` | UBU | P-10 |
| — | INCOMPAT | bash 3.2.57 on MAC breaks OpenFOAM bashrc | `bash --version` | MAC | P-20 |
| — | INCOMPAT | Inconsistent STL search paths | `mesh/slicer_api.py:1042`, `waam_3d_studio.py:177` | ALL | P-30 |

### S3 — Informational (6 findings)

- P-16: `ruff` missing from requirements.txt
- P-17: `igraph` optional import fails
- P-18: `build_unbuffered_command` API mismatch
- P-19: cube_80mm.stl 882ms first load outlier
- P-25: No OpenFOAM runs in 24-run history
- P-26: No AUTO-HEAL/rc=258 in history

---

## 4. Simulation Forensics Summary

**79 dirs scanned → 24 actual runs (54 entries inc. meta dirs)**

| Anomaly | Count | Example runs |
|---------|-------|--------------|
| rc=0 (success) | 12 | 2026-10-13_03-42-02, 2026-10-16_17-20-25, ... |
| rc=-15 (SIGTERM) | 5 | 2026-10-12_02-41-56, 2026-10-16_17-19-52, ... |
| rc=1 (syntax/divergence) | 5 | 2026-10-16_18-41-08, 2026-10-16_22-30-19, ... |
| rc=6 | 2 | 2026-10-22_02-47-41, 2026-10-23_17-48-49 |
| rc=8 | 1 | 2026-10-13_03-56-07 |

**Top-10 error regex:**
| Pattern | Count |
|---------|-------|
| EXECUTION FINISHED - RETURN CODE: 0 | 12 |
| EXECUTION FINISHED - RETURN CODE: -15 | 5 |
| EXECUTION FINISHED - RETURN CODE: 1 | 5 |
| EXECUTION FINISHED - RETURN CODE: 6 | 2 |
| EXECUTION FINISHED - RETURN CODE: 8 | 1 |
| Exec error: Error opening file | 5 (all rc=-15) |
| error GROWS with finer dt | 7 (rc=1/6) |
| stalled at 0.39 | 7 (same) |
| MECHANICS_NOT_CONVERGED | 3 (in run_summary.json) |

**Layer-stall table**: All runs max/median ratio 1.00–1.45 → **no stall outliers**. Highest absolute: `2026-10-21_23-51-51` (median 652s, 20 layers).

**5 Reference runs:**
1. Healthy big: `2026-10-16_17-20-25` (rc=0, 313 VTU, run_summary.json, 13 layers, converged)
2. Auto-heal: **none found** in history
3. OpenFOAM: **none found** in history
4. Smallest/floor: `2026-10-16_18-41-08` (rc=1, 208 lines, EDP syntax error)
5. Anomalous: `2026-10-21_23-48-26` (mesh/EDP/VTU exist, NO sim.log, 1 layer only)

---

## 5. Bottleneck Matrix

| Operation | MAC (this host) | Target | Status |
|-----------|----------------|--------|--------|
| Tk event block p95 | (script bug) | <16ms | ❓ |
| First viewport frame | (API drift) | <1.5s | ❓ |
| Cached parse (2k nodes) | 0.007-0.188ms | <5ms | ✅ |
| First parse (10k nodes) | 55-129ms | <100ms | ✅ (10k) / ⚠️ (20k) |
| 50k-node mesh gen | N/A (needs GUI) | <12s | ❓ |
| Spawn child overhead | 19ms mean / 20ms p95 | <80ms | ✅ |
| Sim first-chunk visible | 1.025s | <2s | ✅ |
| Slicer (cube_80mm) | 12.4s, empty toolpath | <3s, >0 pts | ❌ S1 |
| Log reload (max sim.log) | (needs real app) | ≤60ms | ❓ |

---

## 6. Incompatibility Ledger

| Issue | MAC | Windows | Ubuntu | WSL2 |
|-------|-----|---------|--------|------|
| `Popen(text=True)` no encoding | ✅ UTF-8 | ❌ cp1252 crash | ✅ UTF-8 | ✅ UTF-8 |
| `os.killpg` | ✅ OK | ❌ orphans | ✅ OK | ✅ OK |
| `./waam_output` cwd-relative | ⚠️ works if launched from repo | ❌ writes to `$HOME` | ❌ writes to `$PWD` | ❌ writes to `$PWD` |
| `letter_Z_WAAM.stl` ref | ✅ case-insensitive | ✅ case-insensitive | ❌ missing | ❌ missing |
| `Main.stl` ref | ✅ case-insensitive | ✅ case-insensitive | ❌ missing | ❌ missing |
| bash 3.2 bashrc sourcing | ⚠️ ancient | N/A | ✅ bash 5+ | ✅ bash 5+ |
| Tk theme | aqua (XQuartz) | native | X11/Wayland | WSLg/Wayland |
| VTK offscreen | EGL/OSMesa OK | ANGLE/AMD | xvfb/EGL/OSMesa | WSLg |

---

## 7. Proposed Fix Tickets (P-01..P-29)

See `AUDIT_FIX_TICKETS.md` for full detail. High-leverage order:

1. **P-01..04** (4× encoding fixes) — eliminates WIN crash class, 10 min
2. **P-05** (Windows kill tree) — eliminates WIN orphan class, 30 min
3. **P-06..08** (batch 38 raw `after()` calls) — eliminates UI freeze class, 1 hr
4. **P-09** (12 cwd-relative paths) — eliminates launch-dir bugs, 45 min
5. **P-10** (STL filenames) — eliminates UBU missing-file, 10 min
6. **P-11** (plots pipeline) — restores plot generation, 2-4 hrs
7. **P-12** (run_summary.json) — restores run metadata, 30 min
8. **P-13** (slicer 12s/empty) — restores slicing, 4-8 hrs
9. **P-22** (EDP syntax bug) — fixes validation, 1 hr
10. **P-24** (solver divergence) — physics fix, weeks

---

## 8. Verification Gate Results (Phase I)

| Check | Result | Notes |
|-------|--------|-------|
| I1: `pytest tests/ -x -q` | ✅ 5 passed | |
| I2: `ruff check gui/ core/ ../waam_lab/...` | ❌ FAIL | `ruff` not installed |
| I3: AST parse touched files | ✅ 7/7 OK | |
| I4: `regression_suite.py` | ❌ path fix needed | waam_slicer import |
| I5: GUI smoke baselines | ⚠️ PARTIAL | cache/slicer/schedule need path fix |
| I6: Cross-platform deltas | PENDING | other hosts not audited |
| I7: AUDIT_STATE.md updated | ✅ | |

---

## 9. Open Questions for the Human

1. **Windows/Ubuntu access**: This audit ran on macOS only. Phase B/D/F/G need execution on WIN and UBU (native + WSL2) to complete the host matrix. Can you run `scripts/agent/*.py` on those machines?
2. **Slicer priority**: `slice_mesh` returns empty toolpath in 12s — is slicing a current priority, or is the parametric mesh path the main workflow?
3. **OpenFOAM**: Zero runs in history. Is OpenFOAM deprecated, or should we add a CI test case?
4. **Auto-heal**: Never triggered in 24 runs. Should we create a test case that forces auto-heal (malformed params)?
4. **bash 3.2 on MAC**: OpenFOAM runner uses `bash -lc 'source ...'`. Homebrew bash 5+ available — should we require it?
5. **STL filenames**: Rename `z.stl`→`letter_Z_WAAM.stl` and `main.stl`→`Main.stl` (Option A), or update all code refs (Option B)?
6. **Commit timing**: Audit artifacts in `docs/audit/` and `scripts/agent/` are ready. Commit now or after fixes?

---

## 10. Appendix: Full CSV Listing

```
docs/audit/
├── runs_manifest.csv      # 54 entries
├── runs_summary.csv       # 54 entries
├── error_matches.csv      # 2,065 entries
├── slow_layers.csv        # 0 entries (no r>3)
├── vtk_capability.json    # 2 modes OK
scripts/agent/             # 13 scripts created
```
