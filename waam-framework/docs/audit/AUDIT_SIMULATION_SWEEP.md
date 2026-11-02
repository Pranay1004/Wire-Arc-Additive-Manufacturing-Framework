# WAAM Deep-Audit — waam_output Forensic Sweep (Phase E)

Host: pandeyji-macOS (darwin arm64)
Sweep date: 2026-10-24

## E1: Inventory manifest

- **Run directories scanned**: 56 entries in waam_output/
- **Actual simulation runs** (timestamped dirs with FreeFEM/ or sim.log): ~24
- **Meta/special dirs**: parametric_sweep_6cases (6 subcases), benchmark_*, enth*, ctl*, validation_*, mock_matrix, plots/, visual_outputs/, cache/

### E1.2 Sanity totals
| Metric | Count |
|--------|-------|
| waam_output/*/ dirs | 56 |
| runs with sim.log | 21 |
| runs with parameters.json | 58 |
| runs with run_summary.json | 7 |
| runs with plots/*.png | 0 |
| runs with visual_outputs/*.vtu | 0 (VTUs in subdirs) |
| total .vtu files | 12,489 |
| total layer_pass_times.txt | 85 |
| total toolpath.txt | 85 |

## E2: Per-run expectation model — PASS/FAIL

| Run ID | sim.log | run_summary.json | params.json | plots≥6 | VTU>0 | toolpath N≥1 | layer_pass count≥1 | rc | OVERALL |
|--------|---------|------------------|-------------|---------|-------|--------------|-------------------|-----|---------|
| 2026-10-12_02-41-56 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | -15 | FAIL |
| 2026-10-12_03-00-29 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | -15 | FAIL |
| 2026-10-13_03-41-41 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | -15 | FAIL |
| 2026-10-13_03-42-02 | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | 0 | PARTIAL |
| 2026-10-13_03-47-14 | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | 0 | PARTIAL |
| 2026-10-13_03-53-51 | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | 0 | PARTIAL |
| 2026-10-13_03-56-07 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 8 | FAIL |
| 2026-10-16_17-19-52 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | -15 | FAIL |
| 2026-10-16_17-20-25 | ✓ | ✓ | ✓ | ✗ | ✓* | ✓ | ✓ | 0 | PARTIAL* |
| 2026-10-16_18-41-08 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 1 | FAIL |
| 2026-10-16_22-30-19 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 1 | FAIL |
| 2026-10-16_22-34-11 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 1 | FAIL |
| 2026-10-16_23-01-24 | ✓ | ✓ | ✓ | ✗ | ✓* | ✓ | ✓ | 0 | PARTIAL* |
| 2026-10-17_02-31-37 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | — | FAIL |
| 2026-10-17_17-46-55 | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | — | FAIL |
| 2026-10-21_12-03-59 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 1 | FAIL |
| 2026-10-21_12-11-16 | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | — | FAIL |
| 2026-10-21_13-04-12 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 1 | FAIL |
| 2026-10-21_23-48-26 | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓(1) | — | ANOMALY |
| 2026-10-21_23-51-51 | ✓ | ✗ | ✓ | ✗ | ✓* | ✓ | ✓ | -15 | FAIL |
| 2026-10-22_02-47-41 | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | 6 | FAIL |
| 2026-10-22_09-37-47 | ✓ | ✓ | ✓ | ✗ | ✓* | ✓ | ✓ | 0 | PARTIAL* |
| 2026-10-23_17-48-49 | ✓ | ✗ | ✓ | ✗ | ✓* | ✓ | ✓ | 6 | FAIL |
| 2026-10-23_20-18-01 | ✓ | ✗ | ✓ | ✗ | ✓* | ✓ | ✓ | 1 | FAIL |
| 2026-10-23_20-26-26 | ✓ | ✗ | ✓ | ✗ | ✓* | ✓ | ✓ | 1 | FAIL |
| 2026-10-23_22-21-39 | ✓ | ✗ | ✓ | ✗ | ✓* | ✓ | ✓ | — | FAIL |

*VTU exists in FreeFEM/visual_outputs/ subdir, not run root.

**Key systemic failures:**
- **0/24 runs have plots/*.png** — plot generation pipeline completely broken
- **7/24 runs have run_summary.json** — summary writer only fires on rc=0 AND mechanics_converged?
- **No sim_openfoam.log in any run** — OpenFOAM path never exercised in history

## E3: Error regex library matches (Top-10)

| Pattern | Count | Example runs |
|---------|-------|--------------|
| `EXECUTION FINISHED - RETURN CODE: 0` | 12 | 2026-10-13_03-42-02, ... |
| `EXECUTION FINISHED - RETURN CODE: -15` | 5 | 2026-10-12_02-41-56, ... |
| `EXECUTION FINISHED - RETURN CODE: 1` | 5 | 2026-10-16_18-41-08, ... |
| `EXECUTION FINISHED - RETURN CODE: 6` | 2 | 2026-10-22_02-47-41, 2026-10-23_17-48-49 |
| `EXECUTION FINISHED - RETURN CODE: 8` | 1 | 2026-10-13_03-56-07 |
| `Exec error: Error opening file` | 5 | all rc=-15 runs |
| `syntax error` (FreeFEM compile) | 1 | 2026-10-16_18-41-08 |
| `error GROWS with finer dt` | 7 | rc=1,6 runs |
| `stalled at 0.39` | 7 | same as above |
| `MECHANICS_NOT_CONVERGED` | 3 | in run_summary.json |

**OBS-E01** — rc=-15 (SIGTERM) runs all show "Exec error: Error opening file" slicer failure + FreeFEM comment artifacts. Likely GUI Stop or OOM kill. **SEV S1**.
**OBS-E02** — rc=1/6 runs share "error GROWS with finer dt" + "stalled at 0.39" → nonlinear solver divergence (lagged physics). **SEV S2**.
**OBS-E03** — 2026-10-16_18-41-08 has actual FreeFEM syntax error (`+ tpFile +` token) → EDP codegen bug. **SEV S1**.
**OBS-E04** — No AUTO-HEAL or rc=258 found in any log → auto-heal path untested in history. **SEV S3**.
**OBS-E05** — 2026-10-21_23-48-26 has mesh/edp/toolpath/visual_outputs but **NO sim.log** → simulation never executed or log capture failed. **SEV S1 (DATA-QUALITY)**.

## E4: Timing analytics

### E4.1 Layer-pass stall ratios (threshold r>3 = SUSPECT-LAYER-STALL)
All runs have max/median ratio **1.00–1.45** — **no stall outliers detected**. Highest absolute times: 2026-10-21_23-51-51 (median 652s, max 815s, 20 layers) — consistent slowness, not stall.

### E4.3 Time-to-first-layer
Not computable — sim.log lacks timestamps for most runs.

## E5: Specific anomalies hunted

| Anomaly | Found? | Details |
|---------|--------|---------|
| .mesh copies without source STL | YES | Multiple imported_*.mesh in run dirs; source STL not tracked |
| toolpath z-gaps > hz | NOT CHECKED | Need z-column parse |
| layer_pass_times sum ≠ estimated_time_min | NOT CHECKED | Need toolpath summary parse |
| waam_domain.mesh node count ≠ run_summary.json.n_nodes | PARTIAL | Only 7 run_summary.json exist |
| VTU size == 0 | NOT CHECKED | 12,489 VTUs exist |
| parameters.json JSON invalid | NO | All valid |
| sim.log truncated at 8k lines | NO | Max 4,628 lines |

## E6: Five reference runs

| Role | Run ID | Rationale |
|------|--------|-----------|
| Healthy big | 2026-10-16_17-20-25 | rc=0, 313 VTU, run_summary.json, 13 layers, mechanics_converged |
| Auto-heal | (none) | No AUTO-HEAL/rc=258 in history |
| OpenFOAM | (none) | No sim_openfoam.log found |
| Smallest/floor | 2026-10-16_18-41-08 | rc=1, 208 lines, syntax error (EDP bug reproducer) |
| Anomalous | 2026-10-21_23-48-26 | Mesh/EDP/toolpath exist but NO sim.log, 1 layer only |
