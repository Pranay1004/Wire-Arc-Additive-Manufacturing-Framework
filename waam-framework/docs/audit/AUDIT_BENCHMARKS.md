# WAAM Deep-Audit — Benchmark Matrix (Phase F)

Host: pandeyji-macOS (darwin arm64, macOS 26.6.2, Apple M4, 16GB)
Date: 2026-10-24

## F1: Teach-Machine Benches

### F1.1 Mesh Parse (parse_fea_mesh_or_none)
| Mesh | Nodes | First (ms) | Cached (ms) | Speedup |
|------|-------|-----------|-------------|---------|
| imported_cube_80mm.mesh | 9,976 | 55.7 | 0.039 | 1,438× |
| imported_sphere_R40mm.mesh | 4,793 | 24.1 | 0.020 | 1,179× |
| imported_random.mesh | 2,274 | 12.6 | 0.015 | 850× |
| imported_letter_Z_WAAM.mesh | 3,885 | 18.8 | 0.016 | 1,191× |
| imported_sphere_radius_10mm_1k_triangles.mesh | 201 | 1.0 | 0.007 | 143× |
| imported_letter_Z_WAAM.mesh (2) | 13,993 | 71.8 | 0.053 | 1,349× |
| imported_random.mesh (2) | 23,573 | 129.2 | 0.188 | 687× |
| imported_z.mesh | 8,939 | 47.1 | 0.037 | 1,288× |
| imported_sphere_R40mm.mesh (2) | 19,652 | 108.9 | 0.104 | 1,042× |
| imported_cube_80mm.mesh (2) | 11,185 | 60.7 | 0.128 | 475× |

**Baseline check**: ✅ Cached <5ms (target), First 2k nodes <100ms (target), Speedup >100× (target)

### F1.2 CAD Load (load_any_cad_geometry)
| STL | First (ms) | Cached (ms) |
|-----|-----------|-------------|
| cube_80mm.stl | 882.0 | 0.015 |
| sphere_radius_10mm_1k_triangles.stl | 1.3 | 0.013 |
| random_build_y.stl | 1.6 | 0.014 |
| z.stl | 0.4 | 0.012 |
| random_build_x.stl | 1.4 | 0.012 |

**Note**: cube_80mm.stl is outlier (882ms first load) — investigate trimesh path.

### F1.3 Slicer (slice_mesh)
| Run | Time (s) | Toolpath Points |
|-----|---------|-----------------|
| 1 | 12.406 | 0 |
| 2 | 12.276 | 0 |
| 3 | 12.455 | 0 |
| **Mean** | **12.379** | **0** |

**⚠️ FINDING**: Returns empty toolpath, 12s runtime — slicing pipeline needs investigation (S1 BOTTLENECK).

### F1.4 Mesh Gen (generate_waam_mesh) — FAILED
Function requires app context; cannot bench headless. Needs GUI integration test.

### F1.5 EDP Build (EDPBuilder.save)
| Metric | Value |
|--------|-------|
| p50 | 99.4ms |
| p95 | 107.2ms |
| Target | <200ms p95 |

✅ **PASS**

### F1.6 Viewport Worker (_build_offscreen_frame) — FAILED
API changed; needs update to use `update_mesh` + `_schedule_render` path.

## F2: Profiling — PENDING

## F3: Matplotlib Costs — PENDING

## F4: Tk Event-Loop Latency

### F4.1 tk_latency.py — SCRIPT BUG (missing import)
Fix and re-run.

### F4.2 Log Reload — BLOCKED
`log_reload()` needs full app context; cannot bench headless easily.

## F5: VTK Rendering Mode Study (B6.1)

| Mode | First Frame (s) | Status |
|------|----------------|--------|
| EGL offscreen (VTK_DEFAULT_OPENGL_WINDOW=offscreen) | 1.19 | ✅ OK |
| OSMesa software (LIBGL_ALWAYS_SOFTWARE=1) | 0.76 | ✅ OK |
| xvfb (Linux) | N/A (MAC) | — |
| pyvista.start_xvfb() | N/A (MAC) | — |

**Note**: MAC uses native Cocoa/Metal; XQuartz present but not needed for offscreen.

## F6: Windows I/O Aggravators — N/A (MAC host)

### F6.1 fs_latency
| Metric | Value | Threshold |
|--------|-------|-----------|
| per_op | 0.035ms | <1ms ✅ |

### F6.2 Spawn Overhead
| Metric | Value | Threshold |
|--------|-------|-----------|
| mean | 19.1ms | <80ms ✅ |
| p95 | 20.1ms | <80ms ✅ |

## F7: Deterministic Flicker Detectors — PENDING

## F8: Threshold Policy — All MAC baselines within targets except:
- ⚠️ Slicer 12s + empty toolpath (S1)
- ⚠️ tk_latency script needs fix
- ⚠️ Viewport bench needs API update

---

## B2.3 Pipe Pulse (unbuffered)
| Metric | Value | Threshold |
|--------|-------|-----------|
| First chunk latency | 1.025s | <2s ✅ |

## C4.1 Stdout UTF-8 Probe
| Mode | Result |
|------|--------|
| default (text=True) | ✅ OK |
| encoding=utf-8, errors=replace | ✅ OK |
| encoding=utf-8, errors=ignore | ✅ OK |

**Note**: On MAC all UTF-8; WIN would need explicit encoding.
