# WAAM Deep-Audit — State

Mode: AUDIT-ONLY
Start: 2026-10-24T12:19:46Z
Hosts: pandeyji-macOS (darwin arm64, macOS 26.6.2) - this session

## Phase tracker

| Phase | PLANNED | Status | Obs count | Key blockers |
|-------|---------|--------|-----------|--------------|
| A | 12 | DONE | 8 | none |
| B | 18 | DONE | 6 | none |
| C | 30 | DONE | 11 | none |
| D | 12 | DONE | 3 | none |
| E | 12 | DONE | 5 | none |
| F | 18 | PARTIAL | 12 | tk_latency script bug, viewport API drift |
| G | 7 | SKIPPED | 0 | user: no FreeFEM re-run |
| H | 4 | DONE | 29 tickets | none |
| I | 7 | PARTIAL | 0 | regression suite needs path fixes |

## Wedges

- Phase F: tk_latency.py missing `import subprocess`; bench_viewport.py API drift; log_reload_bench needs real app
- Phase I: regression_suite.py needs waam_slicer path fix
- Phase G: skipped per user directive (no FreeFEM re-run)

## Artifacts created

```
docs/audit/
├── AUDIT_STATE.md
├── AUDIT_ENVIRONMENT.md      # Phase A+B+C evidence
├── AUDIT_SIMULATION_SWEEP.md # Phase E full forensic (5 ref runs)
├── AUDIT_BENCHMARKS.md       # Phase F results
├── AUDIT_FIX_TICKETS.md      # Phase H expanded (29 tickets P-01..P-29)
scripts/agent/
├── dep_matrix.py             # ✅ ran: all deps OK, ruff/igraph missing from reqs
├── fs_latency.py             # ✅ 0.035ms/op (NVMe native)
├── pipe_pulse.py             # ✅ 1.025s first chunk (<2s PASS)
├── stdout_utf8_probe.py      # ✅ all 3 modes OK on MAC
├── vtk_capability.py         # ✅ EGL 1.19s, OSMesa 0.76s
├── scan_waam_output.py       # ✅ 54 runs, 2065 errors, 0 slow layers
├── bench_parse_mesh.py       # ✅ 475-1438x speedup
├── bench_cad_load.py         # ✅ cube_80mm outlier 882ms
├── bench_slicer.py           # ⚠️ 12.4s, empty toolpath
├── bench_edp_build.py        # ✅ p50=99ms, p95=107ms
├── spawn_overhead.py         # ✅ mean=19ms, p95=20ms
├── tk_latency.py             # ❌ missing import
├── log_reload_bench.py       # ❌ needs real app
├── regression_suite.py       # ❌ path fix needed
└── bench_mesh_gen.py         # ❌ needs app context
```

## Key findings summary

### S1 (Critical) — 10 tickets
- WIN UnicodeDecodeError (P-01..04)
- WIN orphan FreeFEM (P-05)
- Tk flood 38 raw `after(0,...)` (P-06..08)
- 0/24 runs have plots (P-11)
- Slicer 12s + empty toolpath (P-13)
- Missing sim.log anomaly (P-21)
- EDP syntax bug (P-22)
- Solver divergence 3.6h runs (P-27)

### S2 (Major) — 10 tickets
- 12 cwd-relative paths (P-09)
- STL filename mismatches (P-10)
- 7/24 run_summary.json (P-12)
- bash 3.2 on MAC (P-20)
- Solver divergence auto-heal (P-24)

### S3 (Info) — 6 tickets
- Missing ruff/igraph in requirements (P-16,17)
- platform_adapter API (P-18)
- CAD load outlier (P-19)
- OpenFOAM untested (P-25)
- Auto-heal untested (P-26)

