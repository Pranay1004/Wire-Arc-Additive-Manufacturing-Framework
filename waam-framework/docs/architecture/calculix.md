# WAAM-Framework → CalculiX: Complete Porting Methodology

**Repository:** `WAAM-Framework` (backend swap: FreeFEM++ → CalculiX)
**Target:** a zero-touch, fully automated, fully parametrized CalculiX pipeline with GUI, live output, postprocessing, plotting, directory/case generation, and hands-off result analysis — parity or better with every capability the FreeFEM backend delivers today.
**Status:** methodology (this document drives implementation; phase exit criteria are binding).
**End-goal note — the project aims for a digital twin.** This backend swap is not just solver plumbing: the stated destination of the WAAM program is a **digital twin of the build** (per-asset state, measured-world ingestion, measured-vs-predicted reconciliation, whitelisted closed-loop corrections — the ladder established for the framework: planning engine → digital shadow → twin). The port's shared fusion contract lives in **§23.K** of this document; the MOOSE plan references it as the owning contract. Everything below must leave that lane open.

---

## 0. Purpose, principles, and the definition of "done"

### 0.1 Why this document exists

The FreeFEM backend works and is validated (340-check physics suite, exact energy audit with 0.78 % residual on the 10-layer letter-Z regression). A port to CalculiX is a *backend swap inside a working pipeline*, not a green-field build. The single biggest historical failure mode of such ports — and of agentic ("AI does it in a few days") attempts — is **rewriting the physics but silently losing the guarantees**: the energy audit telescoping, the layer-bucketed toolpath matching, the M-matrix temperature floor, checkpoint guards, and the regression suite. This document exists to prevent that: every section specifies *what is preserved*, *what is replaced*, *what is verified*, and *what gate proves it*.

### 0.2 Non-negotiable invariants (the "definition of done" contract)

The port is done when ALL of the following hold — each is verifiable without human judgement (a script prints PASS/FAIL):

1. **One command, zero touch.** `python run.py --stl <geometry> --solver ccx` must complete slicing → meshing → deck generation → CalculiX solve → audit → postprocessing → `report.html` with no interactive input, and exit code 0 only if all QA gates (§18) pass.
2. **Same input contract.** The identical `parameters.json` / GUI configuration must drive both backends unchanged; only a `solver` field selects the backend (`"MUMPS"`→FreeFEM, `"CCX"`/`"CalculiX"`→CalculiX). Defaults and presets (`DEFAULT`, `uva_waam_ss308l_ss316`) remain valid names.
3. **Same artifact contract.** The output directory layout (§16) exposes the same consumables the FreeFEM backend produces: `solver_results.json` with the **same JSON schema** (same keys, §1.3), energy-audit ledger with the **same nine ledger terms** (§1.5), the same plot set (§1.7, all seven plots + thermocouple figures + hardness CSV), `report.html` at the same relative path, `toolpath.gcode`, `toolpath.txt`, `layer_pass_times.txt`.
4. **Same audit honesty.** The energy ledger must carry `intended_arc` and `injected_arc` *identical by construction*, a `boiling_cap_removed` term, a `quiet_node_discarded` term, and a final `numerical_residual` ≤ 1 **%** (FreeFEM baseline: 0.78 %). If CalculiX cannot provide a term, the term is reported as `null` **plus a WARN line in the report**, never silently dropped.
5. **Same numerics honesty.** The run directory records the actual time integration used, the actual convergence behavior (`.sta`/`.cvg` preserved), and any scheme substitution (e.g., cp(T)-spike melt modeling instead of a dedicated latent-heat term) is labeled in the report — following the framework's existing principle of *labeled approximations*, never hidden ones.
6. **Regression suite survives.** `tests/physics_suite.py` grows, not shrinks: every check that proved the FreeFEM path gets a CalculiX-oriented twin (§19); total pass count must monotonically increase through the port.
7. **GUI fully functional.** Every one of the 12 GUI tabs (§13) remains operational with `solver=CalculiX`; the auto-generated preview tab shows generated deck content live; simulation log streams live; parametric/DOE launches batch CalculiX cases unattended.
8. **Parametric completeness.** Every parameter the GUI exposes either (a) drives the deck/subroutine, (b) is documented as "FreeFEM-only (labeled, ignored under CalculiX)", or (c) is documented as "CalculiX handles natively — parameter retained for schema compatibility". No silent dead keys (a prior audit of this framework found and fixed exactly that class of bug — `mechanical_model`/`chi_*` being declared but unread — so it must not recur).
9. **Checkpoint semantics kept.** Mid-build resume after a crash must be possible at *at least* layer granularity (see §12.4 for the mechanism gated in Phase 0).
10. **Mesher reused as-is.** The Conformal tet meshing pipeline (`mesh/stl_pipeline.py`, incl. this session's classifySurfaces ladder fixes, algorithm ladder, 1800 s timeout, surfaced diagnostics) is common infrastructure — it is modified only to *add* an Abaqus-`.inp` export path, never degraded.
11. **Open twin lane.** The port ships the *hooks* of the digital-twin workstream, not the twin itself: every case directory carries the `sensors/` stanza contract (§23.K), `solver_results.json` reserves `measured_*` ledger columns (null/absent until sensors attach), and the report can render the measured-vs-predicted annex. Physics phases (P0–P8) place NO real-time or sensor requirements on the solver.

### 0.3 Guiding principles

- **Outer-driver control.** CalculiX (`ccx`) is a batch solver. The framework keeps all scheduling intelligence (which burn state is on, dt selection, dwell windows, activation bands, probes, audit) in the *Python driver + generated deck + Fortran subroutines*; ccx integrates the physics per stage. Never delegate a physics decision to ccx defaults that the FreeFEM path controls explicitly today.
- **Sequential coupling preserved.** Current architecture = staged thermal solve per step-group → mechanical stage (inherited stresses, fixture springs, plasticity) → springback. CalculiX offers `*COUPLED TEMPERATURE-DISPLACEMENT`, but adopting it changes the validated physics pipeline; Phase 0 gate measures it, and the *default* port stays sequential (§12.3).
- **Label-preserving.** The six boundary labels (1 = plate underside, 5 = top, 2/3/4/6 = flanks; `mesh/structured_conforming.py`) are the contract between mesher and physics. The port maps labels → elsets/surfacesets/nsets 1:1 in the deck (§8).
- **The audit is the product.** The framework's differentiator over hobby FEM stacks is the printed, telescoping energy ledger. Porting it is a first-class workstream (§11), not an afterthought.
- **Phase 0 decides.** Where CalculiX semantics are uncertain (restart support, latent-heat modeling, element-(re)activation semantics, material-property swap mechanics), this document prescribes a bounded Phase 0 probe *before* committing. No feature is designed against wishful ccx behavior.

### 0.4 How to read this document

- Sections 1–2 = ground truth inventory + what must survive. These are the "expectations". §1.9 is the shortfall/dead-end inventory of the current backend.
- Sections 3–5 = capability map, target architecture, toolchain.
- Sections 6–12 = the physics port, mechanism by mechanism, with phase gates.
- Sections 13–17 = live output, GUI, parametrization, automation, directories.
- Sections 18 = zero-touch result analysis and gates; Section 19 = tests and regression porting.
- Sections 20–23 = performance, risks (incl. execution bottlenecks §21.1), phased delivery, appendices (incl. the dead-end evidence log §23.J and the digital-twin sensor-fusion contract §23.K): migration tables, keyword skeletons, `dflux.f` skeleton, audit pseudocode, checklists, tolerances.

---

## 1. Ground truth: the current system, exactly as it stands

Everything in this section was verified in the repository during this session and forms the port's baseline expectations.

### 1.1 Module inventory

| Path | Lines | Role | Port disposition |
|---|---|---|---|
| `run.py` | 831 | CLI + orchestration: `run_full_pipeline` = slice → toolpath artifacts → mesh → EDP → FreeFEM solve → postprocess; preset application (`apply_preset_to_params`), case stamping into `waam_output/<timestamp>/FreeFEM/`, `run_command_with_tee` (live log), FreeFEM binary discovery (`find_freefem_serial/mpi`) | **Extend**: make backend polymorphic (§15); the run dir becomes `CalculiX/` when `solver=ccx` |
| `gui/app.py` | 7,830 | Tkinter app, 12 tabs (enumerated §14), DOE/parametric sweep launcher, live sim-log pane, OpenFOAM launch, 3D slicer/viewport twin, generated-script preview | **Small edits + backend selector** (§14) |
| `codegen/edp_builder.py` | 5,584 | Generates the complete standalone FreeFEM `.edp` from ~100 parameters + `toolpath.txt`; all physics lives here (thermal varfs, mechanics varfs, audit, probes, adaptive dt, checkpoints) | **Twin**: create `codegen/inp_builder.py` with mirrored architecture; edp_builder stays untouched as the reference backend |
| `mesh/slicer_api.py` | 1,058 | Part placement (center X=Y=75 on 150×150×5 plate, 0.4 mm fusion bite), slicing, perimeter+meander infill, arc/pState gating, z-hop; emits `toolpath.txt` / `layer_pass_times.txt` / `toolpath.gcode` | **Unchanged** (backend-independent) |
| `mesh/stl_pipeline.py` | 863 | trimesh → manifold boolean union (part ⊕ substrate, watertight, conformal) → gmsh classified tetrahedralization (Algorithm3D ladder 4→7→1 session-fixed, classifySurfaces ladder, two-region sizing, geometry relabeling into 6 labels, 1800 s worker timeout) → FreeFEM `.mesh` | **Add `write_abaqus_inp` export** (§8) |
| `mesh/structured_conforming.py` | 513 | Boundary-label conventions (labels 1..6 = B-side faces) | **Unchanged**; consumed by the sets exporter (§8) |
| `mesh/cad_importer.py`, `mesh/gcode_parser.py`, `mesh/intelligent_mesher.py`, `mesh/units.py` | 222 / 412 / 400 / 83 | CAD ingest helpers, G-code → toolpath, alternate mesher, unit conversions | **Unchanged** |
| `postprocess/plot_generator.py` | ~1,300 | The 7 publication plots + per-probe figures (enumerated §1.7) | **Adapted input layer only** (§17) |
| `postprocess/report_generator.py` | ~1,000 | Self-contained `report.html` with all tables/plots | **Unchanged** (same JSON schema → zero changes) |
| `postprocess/hex_mesh_converter.py` | — | Hex-mesh converter (already present!) | **LEGITIMATE future hook** for layer-aligned hex/prism lanes (§8.4) |
| `postprocess/output_manager.py` | ~120 | Reads `solver_results.json` (authoritative), writes artifacts | **Unchanged** |
| `core/` | — | Physics playground/reference modules: `heat_sources/` (goldak double-ellipsoid, conical frustum, gaussian surface/volumetric, uniform band, prescribed temperature), `microstructure/solidification_phases.edp`, `multimaterial/` (alloy_metallurgy.py + material_database.json), `acoustic/vibration_acoustic.edp`, `fluid/marangoni_meltpool.edp` + `openfoam_coupling.py`, `postprocess/output_manager.py` | Heat-source library doubles as the CalculiX `dflux.f` design source; microstructure/hardness cross-validation cases retained (§12.5) |
| `tests/physics_suite.py` | 1,478 | **340 checks**, pattern + numeric, incl. suite-§6 presets pattern checks | **Extended**, never reduced (§20) |
| `tests/validate_j2_mechanics.py`, `validate_cas_ded_dimeen26.py`, `test_wall_probes_ultrasonic.py` | 206 / 602 / 219 | Physics regression cases (J2, wall-probe/ultrasonic, specimen case) | Each grows a CalculiX twin (§19.3) |
| `parametric_sweep.py`, `generated_edps/`, `stl/`, `case1/`, `scripts/` | — | Sweeping, static presets (DEFAULT, uva preset), sample geometry, glue | Presets gain static `.inp` twins via the suite's §6 checker |
| `waam_output/2026-10-17_17-46-55/FreeFEM/` | — | The regression artifact: reference tree (§16) | Layout contract for `CalculiX/` |

### 1.2 The toolpath contract (backend-independent, must survive verbatim)

`toolpath.txt`: line 1 = `nPts`; then one point per line: `t x y z pState` — meters, seconds, and the weld state *of the move ending at that point* (`pState > 0` ⇒ arc on). `layer_pass_times.txt` gives per-layer weld windows. The solver rereads this inside the generated script via layer-bucketed windows matched on z (tolerance `0.45·h_bead`), computing weld/on windows per layer. The CalculiX deck generator and `dflux.f` must consume the **same two files with the same semantics** — this is the single most important cross-backend contract, and it is what made the FreeFEM path provably match the real G-code schedule (10/10 layers, zero clock drift).

### 1.3 Generated-solver output contract (`solver_results.json`)

Written by the generated solver script (currently the `.edp`; later the ccx audit module — §11.3) into the run dir; consumed verbatim by `postprocess/output_manager.py`, `report_generator.py`, and the GUI. Schema (verified this session from the regression artifact):

```
schema
mechanics_converged          (bool)
newton_iterations            (int)
newton_force_residual        (float)
newton_disp_residual         (float)
sim_time_s                   (float, wall time)
thermal_frames               (int)
nlayers                      (int)
peak_von_mises_MPa           (float)
max_uz_mm                    (float)
max_disp_mm                  (float)
max_peak_temp_C              (float)
energy_audit_J               { Nine terms — see §1.6 }
```

The CalculiX backend writes the **same keys**; extra ccx-specific diagnostics may be added under `ccx_meta`, but no existing key may change meaning.

### 1.4 FreeFEM physics capabilities that CalculiX must reproduce (or explicitly label)

| # | Capability | FreeFEM realization | Where |
|---|---|---|---|
| 1 | Transient heat with latent heat | Enthalpy form: unknown = volumetric enthalpy H above T_amb; mass term ρ(H−H₀)/dt exact at any dt; T recovered from H | `aThermal`/`lThermal` varfs |
| 2 | θ-scheme conduction | `thetaT` (1.0 = Backward Euler default) | varfs |
| 3 | Goldak double-ellipsoid arc | Volumetric source, defined by beam params + toolpath, gated by pState windows | inject block |
| 4 | Alt. heat sources | Gaussian surface/volumetric, conical frustum, uniform band, prescribed-T | `core/heat_sources/` |
| 5 | Quiet-element deposition | psiActive / borning / srcMask nodal fields; mass deliberately *unmasked* so the ledger telescopes | varfs |
| 6 | Convection + radiation BC | Robin `h·(T−T_amb)` + linearized σ ε (T⁴−T_amb⁴) on labels 1..6 | int2d terms |
| 7 | Boiling cap | T clamped at T_boil, removed energy isolated as `boiling_cap_removed` | audit |
| 8 | Fully lumped operator | Volume (`qfV1lump`) + boundary-face (`qf1pTlump`) quadrature → M-matrix, discrete maximum principle; measured: consistent mass dipped solver to −30,087 °C and re-injected 39 % of arc energy | varf quadrature |
| 9 | Adaptive dt | Fourier-number-limited dt from *worst actual local diffusivity* over active nodes; floor/ceiling; source-travel cap (torch advance ≤ src_width/N per step) | `stableThermalDt` |
| 10 | Property iterations | `thermal_correctors` loops k/Cp/hrad to convergence (tol 0.5 °C) | solver loop |
| 11 | Elasticity + thermal stress | Small-strain virtual work, T/state-dependent λ, μ, inherent (sd) stress load | `aMech`/`lMech` |
| 12 | J2 plasticity | Nodal return-map Picard (+ consistent-tangent Newton path), isotropic hardening h′=1.5 GPa, peeq_limit 0.25, trust-region dγ cap | mechanics stage |
| 13 | Gravity on active material | `int3d(rho·psi·(−vz))` — the melt-sag / blow-through / wall-collapse enabler | `{grav_term}` |
| 14 | Fixture + release | Robin springs on label 1 (underside): Kz/Kxy clamped; released state keeps 1e-9 regularization spring to keep the solve unique (measured: without it, 2.1e7 mm runaway on a *converged* solve); final springback stage | `aMech` clamp terms |
| 15 | microstructure + hardness | Solidification phases → Vickers hardness z-profile CSV | micro module |
| 16 | UVA (ultrasonic) | Yield-surface amplitude/frequency terms; streaming k-boost; acoustic heat; cavitation | uva block |
| 17 | Acoustic (vibration_acoustic) + Marangoni + OpenFOAM hook | Reference/`launchable-in-core` | `core/` |
| 18 | Probe infra | `probe_points`, `probe_paths` (polylines, `path_samples` arc-length stations), `probe_interval` → CSV with *true time* — the "Abaqus-equivalent history" feature | emitted solver |
| 19 | Checkpoint/resume | off/layer/step; `restart_every` 25; resume newest; guarded by `mechOrderCur` stamp | emitted solver |
| 20 | Multi-material | `material_base` / `material_dep` (SS316L plate / SS308L wire), T-dependent tables from `material_database.json` | materials |

### 1.5 The energy-audit ledger (the crown jewel — nine terms, exact names)

`energy_audit_J`:

| Term | Meaning (current backend) |
|---|---|
| `intended_arc` | Arc energy computed *a priori* from parameters (η·U·I·Σweld-window dt) |
| `injected_arc` | What the discretization actually deposited: `vSrcAudit = int3d(Th)(Tsource·srcMask·v)` assembled with the **same quadrature** as the solve, so sum(load vector) == deposited integral by partition of unity (measured: auditing the raw integral instead disagreed by 15 kJ on a 1-layer case) |
| `stored_enthalpy` | Volumetric enthalpy stored at end of stage, integrated from the T field through the same enthalpy curve |
| `boiling_cap_removed` | Energy clipped by the boiling-temperature cap |
| `surface_losses` | Robin convection + radiation passes through BC surfaces |
| `quiet_node_discarded` | Energy dropped by activation/quiet masking (a *known*, bounded artifact) |
| `tamb_floor_added` | the T ≥ T_amb floor rectifier accounting |
| `prescribed_imposed` | Imposed energy when prescribed-T lanes are active |
| `numerical_residual` | Closure: sum of all terms vs. intended; **0.78 %** on the regression run |

Regression-run headline numbers (this session, letter-Z 10 layers): `intended_arc == injected_arc == 714.5 kJ`, coverage 98.5 % of `Pweld × t_weld (188.9 s)`, peak T 2,862 °C, final warpage u_z = 0.017 mm, residual vm = 387 MPa, mechanics converged in 6 Newton iterations, sim wall time 2,461 s. These are the **cross-backend benchmark acceptance numbers** (§23.H).

### 1.6 Current run-directory contents (the layout contract, verified)

`waam_output/<timestamp>/FreeFEM/`:

```
solver_results.json       sim.log                    parameters.json
letter_Z_WAAM.mesh        waam_simulation.edp        toolpath.gcode
toolpath.txt              toolpath.layer_times.txt   layer_pass_times.txt
waam_data.csv             hardness_profile_z.csv     hardness_test_locations.csv
plots/ (7 pngs)           thermal_history_thermocouples_unlog.png
field_tpeak_white.png     field_warpage_white.png    visual_outputs/
report.html
```

§16 specifies the `CalculiX/` twin: same consumables, ccx-native artifacts added (`.inp`, `.sta`, `.frd`, `.dat`, `.cvg`, `src/*.f`, `manifest.json`).

### 1.7 The plot set (verified from `postprocess/plot_generator.py`)

| # | Function | Title | Content |
|---|---|---|---|
| 1 | `plot_01_thermal_history_and_peaks` | Transient Melt Pool Thermal Cycles Across Welding Passes | T(t) histories + pass peaks |
| 2 | `plot_02_cooling_rates_and_dt85` | Solidification Cooling Rate Profile Along Full Height Z + Δt8/5 | dual-axis |
| 3 | `plot_03_distortion_and_warpage` | Substrate Out-of-Plane Warpage U_z(X) + Layer-by-Layer Accumulation | dual-axis |
| 4 | `plot_04_residual_stress_mises` | Peak vm Across Layers + Longitudinal σ_xx(Z) | dual-axis |
| 5 | `plot_05_heat_input_and_dwell_energy` | Kinematics (WFS/TS/d) + Deposition & Cooldown Trajectory | dual-axis |
| 6 | `plot_06_baseplate_center_thermal_cycle` | Z-Axis Probes at Baseplate Center (+ one PNG per probe) | multi + individual |
| 7 | `plot_07_spatial_residual_stress_paths` | vm Along Diagonal Inspection Trajectory + σ along A–A / B–B Sections | dual-axis |
| + | field renders | `field_tpeak_white.png`, `field_warpage_white.png` | 3D field cuts |

Every plot must be reproducible from CalculiX outputs through an input-adapter only (§17) — the plotting code itself must not fork per backend.

### 1.8 GUI tab inventory (verified: 12 tabs)

Geometry · Process · Material · Mesh · Physics · Solver · Ultrasonic · OpenFOAM CFD · Parametric & DOE · 3D Slicer & Twin · Generated Script Preview · Simulation Log.

### 1.9 Missing features, shortfalls, and attempted-but-unfinished work (of the CURRENT backend)

This is the honest deficit inventory of the FreeFEM backend as shipped — every item is either something we tried and could not finish (evidence in §23.J), something deliberately labeled a compromise, or a feature that simply was not built yet. It is part of the port ground truth because each item dictates whether the ccx lane **inherits**, **fixes**, or **must newly build** it.

**A. Meshing / CAD**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| CAD self-repair (fix self-intersecting/notched caps) | **Missing** (detect/refuse only) | Hand-built L-cap passed `is_watertight` with *exact* correct volume yet killed every mesher (gmsh 0 tets, tetgen "self-intersections", manifold self-union ineffective) | Inherit; **must build** a cheap self-intersection screen + explicit repair advice (the message improvement shipped this session) |
| General input fault detection (beyond watertight) | Missing | watertightness/volume did not flag the bad caps | Inherit |
| Zero-thickness / tangency contact cases | Unsupported | no-fusion-bite tangency → `classifySurfaces` aborts ("Wrong topology of boundary mesh for parametrization") | Inherit |
| Solution-driven adaptive *mesh* refinement | **Missing** (adaptive dt only; uniform two-region budget) | two-region Box sizing, no error-indicator refinement | Inherit (ccx lane: same; not in MVP) |
| Hex/quad file-loaded meshes in FreeFEM | **Attempted–stalled** | `readmesh3` ignores `Hexaedra` (both medit spellings; measured: 0 elements). Native `cube()` supports P1/Q2 — math exists, loader doesn't | **ccx fixes this class** (C3D8/C3D6 native); hex lane still optional (§8.4) |
| TetGen alternative mesher lane | Attempted–stalled | python API returns 4-tuple vs 2 ("too many values to unpack") — never operational | Inherit |
| gmsh STL reader robustness | Partial | silent "Error loading" on some structurally valid small STLs (`square_rt.stl`), unresolved rabbit hole | Inherit (low priority) |

**B. Thermal numerics**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| Consistent-mass conservative thermal scheme | **Labeled compromise** | consistent masses measurably broke the discrete maximum principle: −30,087 °C dips and 39 % of arc energy re-injected by the floor rectifier; lumping was the rescue, and row sums/audit quadrature were kept identical | Inherit as documented substitution (§7.1); ccx runs its own scheme — gate A6 decides parity of *that* behavior |
| Radiation physics beyond linearized Robin | Missing | σ ε (T⁴−T_amb⁴) linearization per surface; no view factors, no chamber/shielding model, constant emissivity | Inherit |
| In-loop h-adaptivity between stages | Missing | mesh is fixed across all stages; only dt varies | Inherit |
| Intra-increment adaptive dt inside the solver loop | Partial | Fourier cap evaluated once per step over active nodes (O(N) pass) | Ported as driver pre-pass (must pass the dt-sequence golden test) |

**C. Mechanics**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| True isostatic (3-2-1) restraints | **Attempted–compromised** | released solve without measures went singular → 2.1e7 mm "warpage" on a converged run; shipped fix = 1e-9 regularization spring, labeled in code as "middle path" pending 3-2-1 | **ccx can fix** with real `*SPRING`/`*BOUNDARY` stages (§7.3) |
| Finite-strain (NLGEOM) validated physics | Partial | `nlgeom` hook exists; the validated chain is small-strain | ccx lane needs its own gate before claiming it |
| Volumetric-locking-free plasticity at P1 | **Labeled compromise** | C3D4-equivalent `[P1]³` constant-strain tets lock under J2 flow (nearly isochoric); P2+J2 left BETA (needs relax 0.5, dγ trust-region 0.005) | **ccx likely fixes** (native `*PLASTIC` + C3D10 non-BETA) — gate A8 decides |
| Fully-coupled thermo-mech solve | Missing (by design) | sequential coupling is the validated architecture | Deliberately retained (§0.3) |

**D. Materials / microstructure**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| Grain-scale microstructure (grain size, grain morphology, carbide/HAZ mapping) | **Missing** | only solidification-phase → Vickers hardness (z-profile CSV) approximation | Inherit; ccx twin is postprocessor-only (§7.4) |
| UVA (ultrasonic) validated physics | Partial / parked | `ultrasonic_frequency` was plumbed but `ultrasonic_amplitude` (the actual Blaha-effect driver) was dead until wired this session; still **not experimentally validated**; user directive: leave aside for now | FreeFEM-only label (§14.2) |
| Multi-material pools beyond SS308L-on-SS316L | Partial | `material_database.json` + alloy_metallurgy exist; only the preset is regression-covered | Inherit |
| Marangoni melt-pool CFD in the production chain | Missing (hooked only) | `core/fluid/marangoni_meltpool.edp` + `openfoam_coupling.py` are reference/launch modules, absent from the validated e2e chain | Out of MVP parity scope; documented in §7.4 |

**E. Toolpath / process**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| Power modulation (ramping, per-layer adaptive power), weave/sway arc patterns | Missing | Goldak is steady-window positional; 20.6 s of G0-lead-in handled as torch-off mass, never as power shaping | Both backends; same gap |
| Interpass temperature *enforcement* as a constraint | Missing | interpass is replayed from schedule (dwell), not used as an active solver constraint (wait-if-T-too-high logic) | Both backends; candidate post-parity feature |
| Support structures / overhang logic | Missing | no support generation or penalty in either slicer | Out of scope |
| Real-machine schedule feedback sync (measured vs commanded) | Missing | solver consumes the *commanded* schedule; no closed-loop correction from measured arc/sensors | Inherit |
| Multi-torch / multi-wire concurrent deposition | Missing | toolpath model assumes a single source | Out of scope |

**F. Compute**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| Parallel solves in production | Partial | FreeFEM-MPI discovery exists (`find_freefem_mpi`) but the validated chain is serial MUMPS; UMFPACK OOMs beyond ~100k DoF, MUMPS at 249k DoF/6.7 GB is the working ceiling | ccx: SPOOLES/PaStiX lane (§20); performance gate mandatory (R6) |
| Iterative solver path | Partial | CG present in schema; not the validated production default | Inherit |
| GPU acceleration | Missing | — | Out of scope |

**G. Validation / calibration**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| Automatic comparison against experimental thermocouple / distortion data | **Missing** (channels exist, comparison is manual) | the run produces thermocouple-channel CSVs and probe stations; no built-in experiment-import + overlay + calibration loop | Shared backlog for both backends |
| Uncertainty quantification (tolerance bands vs inputs) | Missing | deterministic single-solution only; sweeps approximate it | Out of MVP scope |
| Physical-coupon regression corpus (recorded measurements as fixtures) | Missing | physics_suite validates codegen + numerics, not measured material behavior | Shared backlog |

**H. Automation / UX**
| Feature | Status | Evidence / why | Port impact |
|---|---|---|---|
| Web/remote dashboard, multi-run live view | Missing | Tkinter desktop; the sim-log pane streams ONE run at a time (sweeps run off-GUI in threads) | Inherit; dashboards out of MVP scope |
| Dead-parameter class rule ("accepted but unread" keys) | **Fixed this session** (`mechanical_model/chi_*` found and fixed; rule now §14.2) | keep the audit current on every new key | Retained |

Everything above marked **Inherit** transfers to the ccx lane unchanged (same code, same limits, same labels); **must build** / **ccx fixes** items are where the port actually changes scope — the phase table (§22) already carries the mandatory ones (self-intersection screen in P0-adjacent work, isostatic mapping in P6, cross-solver J2 gate in P8).



---

## 2. Expectations: what each dimension must look like after the port

### 2.1 Solver expectations
A `ccx` run must give: temperature field history identical *in character* to the FreeFEM run (peak T within cross-backend tolerance, §23.H), mechanics complete with plasticity/fixture/springback, convergence logged, and all outputs delivered in formats the adapter can parse without manual fix-up.

### 2.2 Live-output expectations
The GUI/Simulation-Log pane streams ccx stdout *live* (it already tees for FreeFEM via `run_command_with_tee`); a progress model estimates completion from step indexing (ccx prints per-increment step progress; `.sta` grows); thermocouple/probe CSVs fill incrementally (via `*NODE PRINT` frequency) so the live mini-plot can update during the run exactly as today.

### 2.3 Automation expectations
Batch/sweep/DOE pipelines (`parametric_sweep.py`, GUI DOE tab) launch N back-to-back CalculiX cases with distinct parameter sets and case directories, collect each `solver_results.json` into a comparison table/canvas — no human in the loop, deterministic exit codes, resumable after a crash at case granularity (and within a case at layer granularity, §12.4).

### 2.4 Directory-generation expectations
Every case creates a self-contained directory tree per §16 with a `manifest.json`; "point latest" (`_point_latest`) keeps the GUI's "open last case" behavior; retention/cleanup rules preserve all reports and audits.

### 2.5 Result-analysis expectations
Report auto-analysis computes every gate, sets PASS/WARN/FAIL flags, renders them in `report.html`, and returns a nonzero exit code on FAIL — so "without me touching it" is enforced by contract, not by trust.

---

## 3. CalculiX capability map — what you get free, what you build, what you lose

Compatibility target: **ccx ≥ 2.20** built with user subroutines (SPOOLES default; PaStiX preferred if available) + `cgx` optional (not required — the framework's own GUI/postprocessing suffices).

| FreeFEM capability (§1.4 #) | CalculiX native | Verdict |
|---|---|---|
| 1 enthalpy latent heat | `*SPECIFIC HEAT` is cp(T)-table; first-class `*LATENT HEAT`-with-solidification semantics are NOT guaranteed (Abaqus has it; ccx must be verified in Phase 0 gate A4) | **Build**: cp(T)-spike enthalpy lane with `cp_spike_smooth_K` smoothing (reuses framework's existing smoothing phase-fraction math) |
| 2 Backward Euler | `*HEAT TRANSFER` implicit integration (default; transient, keyword per step) | **Native** |
| 3 Goldak moving arc | moving source requires `*DFLUX`+user `dflux.f` (space+time) or per-element `*DFLUX`+`*AMPLITUDE` decks (no-subroutine lane; discourse-verified; deck bloat ~10⁴–10⁵ lines) | **Build** `dflux.f` (§9); amplitude lane as fallback |
| 4 alt. heat sources | same mechanics as #3 | **Build** (parameterized, one subroutine with source-model switch) |
| 5 quiet-element activation | no native element birth; strategies: (a) quiet elements with property scaling via `weld_deposit.f`-style user subs (proven: OpenAM-SimCCX 2025, Materials 18:4990), (b) `*MODEL CHANGE` ADD/REMOVE semantics (verify in Phase 0 gate A2), (c) per-band elsets with per-stage material assignment | **Build** with a Phase-0-decided lane |
| 6 convection/radiation | `*FILM` (h, T_amb), `*RADIATE` (σ ε,), `*BOUNDARY` temp | **Native**; radiation nonlinearity via `*RADIATE` may differ from linearized-Robin form — parity gate A5 |
| 7 boiling cap | no native cap | **Build** as post-processing accounting + (if needed) subroutine-level cap; report `boiling_cap_removed` identically |
| 8 lumped M-matrix | ccx integrates its own consistent scheme | **Lose (accept)**: do NOT try to re-implement lumping inside ccx. Consequence documented + benchmarked (A6): watch for undershoot/energy rectification needs; if ccx shows the measured pathology (negative T / floor re-injection), mitigate via dt and meshes, and *report* the audit honestly |
| 9 adaptive dt | per-step `*HEAT TRANSFER` dt can be scripted per keyword block, but not intra-step adaptivity | **Build** outer-driver dt schedule (algorithm parity: same Fourier + source-travel caps, applied stage-wise) |
| 10 property iterations | ccx evaluates T-dependent tables natively each increment | **Native (better)** |
| 11 elasticity + thermal stress | `*STATIC` + `*EXPANSION` thermal + `*ELASTIC` | **Native** |
| 12 J2 plasticity | `*PLASTIC` (isotropic hardening table) — native constitutive integration (vs. the framework's nodal Picard) | **Native (different integration)** — cross-validate (A8); peeq_limit becomes QA check instead of solver clamp |
| 13 gravity | `*DLOAD` with GRAV (ρ·g) on active elsets only | **Native** |
| 14 fixture + release | `*SPRING`, `*BOUNDARY`, or penalty via contact; staged steps with restraint change | **Build** mapping (penalty-spring equivalent of clampK; release = step with springs removed + 1e-9 regularization spring preserved; rigid-body guard from framework lessons) |
| 15 microstructure/hardness | none | **Build** postprocessor from T-history (same phase logic) |
| 16 UVA | none | **Label**: FreeFEM-only initially (§14 completeness rule); port later as optional module |
| 17 acoustic/Marangoni/OpenFOAM | substrate-independent (CFD is OpenFOAM side) | **Unchanged**; FreeFEM reference decks remain |
| 18 probes | `*NODE PRINT`/`*EL PRINT` with `FREQUENCY=N` → `.dat`; `*NSET` for points; path probes pre-interpolated by deck generator (nsets at stations) | **Build adapter** (CSV with true time, same schema) |
| 19 checkpoints | no robust native semi-interactive restart (`*RESTART` semantics must be verified — gate A7); expect outer-layer chaining of per-stage jobs with state handoff | **Build** layer-granularity strategy (§12.4) |
| 20 multi-material | `*MATERIAL` per elset | **Native** (generate from `material_database.json`) |
| Direct solver | FreeFEM MUMPS | ccx: SPOOLES (default), PASTIX (if built) — **performance parity gate §20** |
| Output | `.edp`-side JSON | `.dat/.frd/.sta/.cvg` → parse → same JSON (§11.3) |
| Hex/quad meshes | ccx native C3D8/C3D6/C3D20, and FreeFEM `cube()` P1/Q2 probe showed hex support on the math side; the medit reader issue is only a *file-format* bridge | **Future lane**: `postprocess/hex_mesh_converter.py` + gmsh prism extrusion (§8.4) — NOT required for parity MVP |

**Subroutines required (target lane):** `dflux.f` (Goldak/alt sources, moving) + `cflux.f` if nodal flux formulation is chosen + `weld_deposit.f`-style property activation (as in OpenAM-SimCCX) + optionally `resultstherm.f`/`e_c3d_th.f` hooks for activation feedback. **No-subroutine fallback lane** (§9.4) if the toolchain blocks: amplitude-deck discretization + per-band materials.

---

## 4. Target architecture

```
                       ┌──────────────────────────── run.py (orchestrator) ────────────────────────────┐
                       │  slice (mesh/slicer_api.py)         [UNCHANGED]                              │
                       │  → toolpath.txt, toolpath.gcode, layer_pass_times.txt                        │
                       │  mesh  (mesh/stl_pipeline.py)       [UNCHANGED + .inp export]                │
                       │  → waam_calculix.inp-mesh, sets.json, labels, .mesh (ff twin)                │
                       │  build  (codegen/inp_builder.py)    [NEW twin of edp_builder.py]             │
                       │  → job.inp (stages), src/dflux.f(+aux subs), dt schedule, probes               │
                       │  solve  (ccx_runner)                [NEW; mirrors FreeFEM runner]            │
                       │  → tee live log, .sta watcher → progress, kill-switch, exit contract           │
                       │  audit  (codegen/ccx_audit.py)      [NEW nine-term ledger from .dat/.frd]     │
                       │  → solver_results.json (schema-identical)                                     │
                       │  post   (postprocess/*, GUI already) [UNCHANGED via adapter (§17)]            │
                       └───────────────────────────────────────────────────────────────────────────────┘
```

New/changed modules (complete list — anything not listed stays as-is):

| Module | New/Modified | Responsibility |
|---|---|---|
| `codegen/inp_builder.py` | NEW | Build the Abaqus/ccx deck library + subroutines from parameters + toolpath (mirror of edp_builder architecture incl. f-string discipline, warnings channel, build validation) |
| `mesh/stl_pipeline.py` + `mesh/structured_conforming.py` | MODIFIED (additive) | `write_abaqus_inp(node, facesets→elsets/surfssets)` while keeping medit `.mesh` output (FreeFEM twin keeps working) |
| `codegen/ccx_audit.py` | NEW | Compute the nine-term ledger from ccx outputs (§11), write identical `solver_results.json` |
| `core/ccx/dflux_template.f` | NEW | Goldak/alt. sources; compiled from source dir; consumes toolpath via data file |
| `core/ccx/deposit_template.f` | NEW | Quiet-element property activation (if gate A2 picks the property-scaling lane) |
| `core/ccx/ccx_runner.py` | NEW | Process control: tee, `.sta` tail, progress estimation, caffeine hold, kill/resume |
| `core/ccx/ccx_parse.py` | NEW | `.dat` (prints), `.frd` (field frames), `.sta`/`.cvg` (convergence) readers; `.frd`→VTK bridge |
| `core/ccx/sets_exporter.py` | NEW | Labels/tri → elsets, nsets (probes + thermocouple stations + fixture), film/radiate surfaces (§8) |
| `run.py` | MODIFIED | Backend plumbing (find_ccx, case dir `CalculiX/`), `--solver` flag, contract identical |
| `gui/app.py` | MODIFIED | Backend selector + generated-deck-preview + ccx progress mapping (§14) |
| `postprocess/plot_generator.py` | MODIFIED (input adapter) | Backend-normalized frame source (§17) |
| `tests/physics_suite.py` | EXTENDED | ccx twins of every applicable check (§19) |
| `generated_decks/` | NEW | Static preset decks (DEFAULT.inp, uva_waam_ss308l_ss316.inp) — suite pattern-checks them like §6 does for edps |

Design rules carried from edp_builder (non-negotiable, learned the hard way):

- f-string discipline: FreeFEM braces hurt; here the rule becomes: **`{*}` conflicts between Python f-string and Fortran** — any literal `{…}` in Fortran code goes through the same escape discipline; the suite will keep a "compile the template's own help-path" check (§19.2).
- Every generated artifact carries a machine-readable header block (schema, parameter hash, backend version stamp) — the `mechOrderCur`-style guard will become `deckSchemaStamp` checked on resume/audit load (§12.4).
- All stage reservations print tagged progress lines (FreeFEM path prints `[G-CODE] …`, `[ARC AUDIT] …`): the ccx deck must print equivalents; `guaranteed` parsing depends on them.

---

## 5. Toolchain & builds

### 5.1 macOS (primary, current machine)
Target: ccx compiled from source with gfortran + user subroutines.

1. `brew reinstall gfortran` (or via `brew install gcc`).
2. Fetch ccx source set (src + lib) — recommendation: pick a **source revision with confirmed user-subroutine doc** and pin it in `core/ccx/BUILD_NOTES.md`; the exact tarball hash becomes a suite constant so CI and local builds never drift.
3. Build order per upstream README: compile the Fortran solver with `SPOOLES.OUT`, ARPACK, and `yaml`/f2c; ensure `-fallow-argument-mismatch` (gfortran ≥ 10 for legacy code) and user-subroutine defines are on.
4. Gates before any physics work (script `core/ccx/tools/build_gate.sh` — fails loudly):
   - `ccx -v` returns the pinned version.
   - Toy deck with `dflux.f` runs and the subroutine writes its trace line (proves user-routine linkage on this machine).
   - toy deck with `*FILM`+`*RADIATE`+`*PLASTIC`+`*EXPANSION` runs clean (sanity of the whole keyword surface needed for the port).
   - runtime memory < 7 GB for a 250k-DoF static step (README-parity baseline for the mechanical stage).
5. Binary location: `core/ccx/bin/ccx_<ver>-ser` (serial), discovered by `run.py::find_ccx()` mirroring `find_freefem_serial()`; also recorded in `manifest.json`.

### 5.2 Parallel solvers
Strategy: SPOOLES first (default); PaStiX build attempt documented as optional. Expectation to verify (gate §20): ccx vs FreeFEM-MUMPS wall-time on the letter-Z benchmark within an agreed factor (see Risk R8); if not, mitigate with element budget and C3D4-cost mapping before considering PaSTiX.

### 5.3 CI (GitHub Actions)
- Linux job builds ccx + runs `run.py --stl <sample> --solver ccx --headless` on a minimal case; a second FreeFEM job runs the twin; suite runs as today.
- Fails on any QA gate regression, keeping the promise of zero-touch validated delivery.

### 5.4 Community reference bases to leverage (do not reinvent)
- OpenAM-SimCCX (2025, Materials 18:4990): four-subroutine coupled AM workflow (`weld_deposit.f`, `dflux.f`, `e_c3d_th.f`, `resultstherm.f`) — the quiet-element activation lane is proven; borrow its activation-factor formulation directly.
- CalculiX discourse `dflux` welding threads (moving-source patterns, per-element amplitude workaround) — the no-subroutine lane is proven.
- `ccx2paraview` (free FRD→VTU converter) for the `.frd` bridge if a custom reader is postponed (§17.1).

---

## 6. Phase 0 — feasibility spike (before ANY port code)

Goal: convert every §3 "verify" into a measured yes/no with numbers. Bounded at 6 agentic days; **any failed gate re-scopes the design, not the deadline** (all fallbacks below are designed to exist either way).

Each gate = a small deck+script producing a printed "RESULT …" line (pattern as used in this session's igmsh variant runner).

| Gate | Question | Setup | PASS criterion |
|---|---|---|---|
| A1 | Does a ccx build with `dflux.f` run on this Mac? | §5.1 | BUILD-GATE pass |
| A2 | Element activation semantics that actually work: (a) `*MODEL CHANGE` ADD/REMOVE incl. strain-free add; (b) quiet-element property scaling via subgroup materials; (c) deposit-subroutine scaling | small 2-layer slab; measure residual stress fingerprints of each lane | expect lane set = {property scaling (a quiet band unactivated → k,ρ ∝ 10⁻⁶), *MODEL CHANGE if applicable}; ledger's `quiet_node_discarded` stays computable |
| A3 | Moving Goldak via `dflux.f`: does the footprint march along the toolpath at the right speed? | 1-layer slab; step-through of windows vs. toolpath.txt | source-window replay matches toolpath clocks (per-step window open/close within half a dt), thermal footprint speed = toolpath |
| A4 | Melt handling: does a cp(T)-spike reproduce the latent-heat plateau? | slice with T_liq plateau + known latent heat: audit closed-form vs ccx | stored-enthalpy integral within 2 % of analytic |
| A5 | Film+radiation vs the framework's linearized Robin: BC parity | plate cooling; compare vs FreeFEM 1-step baseline | T(t) within tolerance at t/T-cool mid points |
| A6 | Consistent-mass pathology check | activate a hot band on a quiet border over one big dt; check for negative T / energy re-injection | if pathology appears, dt policy pre-caps it; ledger still closes with the same floor accounting (report `tamb_floor_added`) |
| A7 | Restart mechanics: per-stage chaining with temperature handoff (initial T from prior run's output) or multi-`*STEP` continuity | 2-stage slab | stage 2 end state == monolithic run within tolerance OR checkpoint granularity regraded to "layer-rerun" (§12.4) |
| A8 | J2 plasticity fingerprint parity | 1D-ish bar with load curve vs analytic; then a mini weld-induced stress | vm/peeq within agreed σ; convergence behaves (no pathological oscillation), set `*STATIC` inc/increment defaults |
| A9 | `frd/dat` plumbing | minimal run with `*NODE FILE`, `*EL FILE`, prints | the parser extracts: NT, U, PEEQ/PS frames with true times; probe CSV written |
| A10 | Performance sensor | 250k-DoF static + 85k-DoF transient spot checks | wall-time recorded for §20 budget |

Gate output: `core/ccx/PHASE0_REPORT.md` with "RESULT" lines + a **decision record**: chosen activation lane, chosen melt lane, chosen solve-lane + any design-doc updates (this file is versioned with the port).

---

## 7. Physics translation — thermal stage, mechanism by mechanism

### 7.1 Formulation

| FreeFEM (today) | CalculiX realization | Fidelity expectations & notes |
|---|---|---|
| Unknown H (enthalpy above T_amb); T from H | Unknown NT; melt via cp(T) table with latent spike distributed across [T_sol − k·cp_spike_smooth_K, T_liq + k·cp_spike_smooth_K] so that ∫cp dT across the band = L (latent heat), per unit mass, plus base cp(T) | **Math parity**: the discretized effective-cp method is the classical Fremond equivalent of the framework's enthalpy form. Expect slightly stiffer convergence near the front; `thermal_correctors`=3 semantics disappear (ccx iterates internally); the audit's `stored_enthalpy` must integrate through the *same* Cp curve as the deck (one shared curve function, §11.2) |
| ρ, cp, k: T-dependent fields | `*DENSITY`, `*SPECIFIC HEAT`, `*CONDUCTIVITY` tables from `material_database.json` (K→°C careful: ccx wants absolute K; the deck generator converts and **records in the header that conversion happened**) | direct map |
|θ=1 BE, dt_weld 0.333 s / dt_wait 10 s / dt_cool 120 s, n_cool 20 | `*HEAT TRANSFER` blocks per stage with `DTI=?`/`deltmx` equivalent — the *outer driver* writes the SAME dt schedule it generates today (incl. adaptive Fourier cap applied *per stage*, not intra-step) | dump table: `adaptive_dt_min/max`, `fo_target=0.45`, `src_travel_fraction=8` become driver code in `inp_builder` (same math, port the node loop into a mesh pre-pass since ccx won't run it in-loop) |
| Robin hBot/hSurf on labels 1..6 with psiActive gating | `*FILM` (+`h.f` only if needed) **restricted to activated/deposited surfaces** — stage-wise film elsurfs replace the framework's psi-activation gating mechanically; label 1 uses `h_bot`, others `h_conv` | the *activation gating* (film only on born material) is a driver/state issue: per-stage `*FILM` reassignment or subroutine lane; verify in A2 |
| Radiation σ ε (T⁴−T_amb⁴) | `*RADIATE` (emissivity, ambient) on same staged surfaces | parity vs the linearized-Robin measured in A5; tolerances recorded |
| Source: Goldak double ellipsoid with arc efficiency, front/rear a,b,c + mode-switch | `dflux.f`: Q_total = η·U·I; front/rear ratio split Fd; coordinate transform from toolpath arc-length param; pState windows from toolpath (on/off); **units: deck is m/J/s (SI)** matching framework's internal SI | skeleton in §23.C; unit-test the Goldak integral = Q_total on a fine grid BEFORE physics (suite test §19.4) |
| Boiling cap at T_boil | post-audit accounting + (if consistent) a subroutine/image clamp; report `boiling_cap_removed` identical | `boiling_cap_removed` parity with FreeFEM measured in cross-validation |
| Lumped M-matrix | (not available) | documented substitution; A6 decides whether audit needs an extra `tamb_floor_added` handling parity — the ledger term already exists, so no-schema change |
| Adaptive dt | driver-side replay of the SAME algorithm on the ccx mesh (needs element sizes accessible: exporter stores per-element `h` from gmsh) | the dt sequence is *precomputed* and written as per-stage dt instructions; a mid-run divergence triggers the driver's kill/replan loop (§13.4) |

### 7.2 Deposition/activation (the physics-critical part)

- Phase-0-decided lane (expected: property-scaled quiet elements, OpenAM-SimCCX-style):
  1. All deposit elements exist from t=0 with `_quiet` material variant (k·1e-6, ρ×1 identical but cp effect handled same way as the paper: activation factor on properties each increment).
  2. Per stage (layer portions, dt slices), the deck/domain transition: `*SOLID SECTION`/material alias reassignment per band OR subroutine lane (`deposit_template.f` computes activation factor fa(x,t) from geometry+time as in the paper's Eq. 17-18; preferred since it removes driver reassignment complexity).
  3. Ledger: `quiet_node_discarded` = integral of the (bounded) flux dropped while a node is still quiet — reproduce exactly as today; † add suite test that quiet heat loss < 0.5 % of injected per layer.
- Interface bite: the 0.4 mm fusion embed already guarantees conformal union — the InP mesh inherits it; nothing new.

### 7.3 Mechanics stage

| FreeFEM | CalculiX | Expectations |
|---|---|---|
| [P1]³ tets (C3D4), optional P2 (BETA) | C3D4 / C3D10 native | C3D10 loses its BETA status (native constitutive integration); `mechanics_order=2` now maps to C3D10 cleanly — suite flip: remove "BETA with J2" warning for ccx path, keep for edp path |
| λ,μ from T-dep E,ν | `*ELASTIC, TYPE=ISO` tables | direct |
| inherent/thermal loading (sd-stress) + expansion | `*EXPANSION` + `*TEMPERATURE` initial per stage; sequential coupling = per-stage `*STATIC` runs with NT from preceding thermal job |  |
| J2 + h′ + peeq_limit | `*PLASTIC` hardening table; peeq_limit becomes a QA post-check (NO solver clamp) — gate expects |  |
| gravity on active | `*DLOAD` GRAV restricted to active/deposit elset per stage |  |
| fixture springs Kz/Kxy on label 1 faces; release stage with 1e-9 regularization | `*SPRING`/penalty BC pairs clamped; release step: remove hard springs, keep reg spring; **rigid-body guard**: after release step, max displacement sanity-check (regenerate the 2.1e7 mm runaway as a suite test to prove the guard) |  |
| springback | final `*STATIC` step with released restraint — same stage semantics |  |
| nodal Picard converg metrics (newton_iterations, force/disp residuals) | ccx `.sta`/`.cvg` per-increment residuals → parsed into same JSON fields | summary semantics: force/disp residual = last-increment values; parity flagged in report |
| TRIP trip_beta | if β>0: `*EXPANSION, TYPE=ISO` composited volumetric term in subroutine lane or labeled limitation; default β=0 makes it unexercised in MVP |  |

### 7.4 Microstructure / hardness / UVA / acoustic / Marangoni

- **Hardness pipeline**: keep the phase-logic code in Python, feed it ccx NT histories; produce the same `hardness_profile_z.csv`, `hardness_test_locations.csv`. The `solidification_phases.edp` reference stays for the FreeFEM backend; ccx twin = postprocessor-only approximation (documented).
- **UVA / acoustic / Marangoni/OpenFOAM**: out of MVP parity scope per task order ("uva forget it for now"); schema keeps the keys with explicit labels in the report (§15 completeness rule).

---

## 8. Mesh, sets, and the Abaqus export

### 8.1 Exporter (`mesh/stl_pipeline.py`, additive)

 gmsh tetra output already carries: nodes, tet connectivity, physical boundary labels after `_relabel_mesh_boundary` (labels 1/2/3/4/5/6 by geometry). Add:

1. **`write_abaqus_inp(...)`** → `<stem>.inp` *mesh-only* blocks (header → NODE → ELEMENT C3D4 (+C3D10 option) → SETS), produced from the same intermediate structures; **medit `.mesh` writers untouched** (both outputs coexist in the same run dir).
2. **`sets.json`** (the sets contract):
   - `elset_layers`: per-layer element sets (from slicer z), also `elset_layer<k>` ↔ quiet/_active twins.
   - `elset_substrate`, `elset_deposit`.
   - `nset_<label>`: nodes of each of the 6 boundary labels; `nset_probe_<i>`, `nset_tc_<station>` for probes + baseplate-center stations and hardness locations (shared with FreeFEM outputs).
   - `surfs_film_label<k>`: element-face sets for `*FILM`/`*RADIATE` per label.
   - `elset_fixture`: label-1 element faces for the fixture springs.
3. Optional `use meshio` to *read back* the generated INP in a suite test (round-trip format check).

### 8.2 Node budget parity
Same node-budget logic (`target_nodes=1500` equivalent → weights fields) — the exporter writes point sizes exactly like now (already established in the mesher), so ccx mesh densities equal FreeFEM mesh densities for any given budget.

### 8.3 Mesh quality gates carried into ccx runs
Tet-count parity: letter-Z budget-mesh expected ~9,9xx tets as measured (§1.5); suite asserts the ccx case's `nlayers` and element counts match the FreeFEM twin within 1 element (regression on the exporter).

### 8.4 Future layer-aligned hex/prism lane (documented, not MVP)
One prism layer per deposited layer → element faces on activation boundaries → source-fidelity and activation masking both exact. FreeFEM probe showed math supports hex (cube(); Q2), while the medit reader of *this* build ignores `Hexaedra`; ccx has no such issue. Bridge: `postprocess/hex_mesh_converter.py` (already exists) + a gmsh prism-extrusion recipe. Tracked as Phase-9 enhancement.

---

## 9. Heat source & deposition subroutines

### 9.1 `dflux.f` specification (target lane)

Responsibilities (from the framework's inject block + `core/heat_sources/goldak_double_ellipsoid.edp`):

1. **Input data contract** — instead of hardcoded parameters, the deck writes `toolpath.txt`, `layer_pass_times.txt`, and `src_params.txt` (beam geometry, efficiency, mode switch); `dflux.f` reads them once at INIT (Fortran stream read), maintaining: sorted weld-window table (t_start, t_end, (x,y)_at_s, layer_id), local arc-length parameterization.
2. **Window/state logic at time τ**: find current window (pState on/off from toolpath); if OFF → flux = 0 AND accumulate into the "dwell" accounting (the audit consumes these numbers from the .sta/audit file the subroutine also appends — a one-file `ccx_src_audit.log` protocol, §11.3).
3. **Positioning**: convert τ → arc-length s via per-window linear speed (from toolpath spacing); position (x_s, y_s) + current-layer zc (HzBase + 0.5·h_bead1 for layer 0, then HzBase + h_bead1 + (l−1)·h_bead_sub + 0.5·h_bead_sub — **port the exact layer-bucketing constants from edp_builder**, including the 0.45·h tolerance semantics).
4. **Goldak evaluation at (X,Y,Z,τ)**: standard double-ellipsoid formula, front/rear split 2:1 (framework value), depth profile per arc mode; volumetric flux J/m³/s with SI conversions; local k_liq_factor boost *if* the material at T ≥ T_liq and flag enabled (table check inside the subroutine).
5. **Trace protocol** (for the audit): after each call the subroutine appends `Q dt element_id vol` lines to `ccx_src_audit.log`; the audit module consumes ONLY this file for `injected_arc` (by-construction equality with `intended_arc` from window integration) — this reproduces the framework's vSrcAudit-by-construction trick without depending on ccx internals.
6. **Determinism**: no time-based JITTER or wall-clock reads; all decisions from toolpath times.

### 9.2 `deposit_template.f` (activation lane, if gate A2 selects property scaling)

Per OpenAM-SimCCX formulation: activation factor fa(x,t) from ==heat-source-march== criterion — element activates when s_current ≥ s_element (avoid remesh; quiet → solid transition scaled: k_eff = fa·k etc.). States + feedback mirror the paper; ledger `quiet_node_discarded` computed from whenever fa < 1 rejects flux (log lines appended to the same `ccx_src_audit.log`).

### 9.3 Stage-loop integration

The driver does NOT move physical activation inside ccx silently: each `*HEAT TRANSFER` step block lists the currently-active elsets *and* passes the needed state via the data files; subroutines exist to guarantee no discontinuity weirdness mid-increment (paper's found feedback subtlety).

### 9.4 Fallback lane: no user subroutines

If gate A1 fails on the current machine and stays failing (toolchain blocked):

- Moving source via per-element `*DFLUX` + per-window `*AMPLITUDE` tables (units: Hz per element face, computed by generation-time discretization of Goldak over face centroids; verified pattern from discourse; deck grows ~10⁴–10⁵ lines — bound the deck size budget ≤ 50 MB in the suite).
- Activation via per-band materials + `*MODEL CHANGE` ADD/REMOVE if gate A2 proved semantics; else change-quiet-then-active by band reassignment.
- Magnetic subroutines latency: `.dat`-only probe history, audit adaptation only in injected-arc estimation (integrate field outputs) — the equality intended==injected becomes a ≤ tolerance check instead of by-construction; the suite will keep the 1e-6 relative |diff| identity gate only in the subroutine lane.

This lane is *always available* as a documented feature flag `ccx_no_subroutines: true`.

---

## 10. Deck generation (`codegen/inp_builder.py`)

### 10.1 Architecture (mirror of edp_builder)

1. **Same build signature**: `build_inp(params, toolpath, mesh_files, sets, outdir) -> BuildResult(inp_text, src_files, warnings, schemaStamp)`.
2. **Same template discipline**: chunked f-strings with brace-doubling rules; a template *help-keys* dict so the "Generated Deck Preview" GUI tab renders the deck live (equivalent of `_refresh_generated_edp_preview`).
3. **Same warnings channel**: builder warnings surface in run log + report exactly as EDPBuilder does (`"[INP-BUILDER] …"`).
4. **Same parameter checks**: raise-on-invalid-input (e.g. `mechanics_order` ∈ {1,2}), same as edp_builder; identical errors so GUI code paths don't fork.
5. **Unit boundary**: ALL deck units SI (m, J, s, K); conversion from the framework's mm/°C parameter surface happens in ONE place (a `unit_map` dict) with a suite test that ×1000/×0.001 invariants hold for every mesh/space-related parameter. (FreeFEM path: meters because the mesh is exported in meters — keep the same internal units so the audit math is shared.)

### 10.2 Deck skeleton (keyword-level; full skeleton in §23.B)

Per case, one `job.inp` (or stage-split `stage_%.3d.inp` chaining for checkpointing) with blocks:

```
*HEADING            (framework stamp, schema, parameter hash)
*PREPRINT, ECHO=NO, MODEL=NO, HISTORY=NO
*NODE / NSET=…      ← from exporter
*ELEMENT, TYPE=C3D4, ELSET=…  (substrate / layer<k> / quiet twins)
*MATERIAL, NAME=<dep_|base_><variant>   ← tables from material_database.json (K! )
  *CONDUCTIVITY, *SPECIFIC HEAT (latent band), *DENSITY, *ELASTIC, *EXPANSION, *PLASTIC
*USER SUBROUTINE    (dflux + lane subs, when enabled)
*INITIAL CONDITIONS, TYPE=TEMPERATURE   ← T_amb everywhere
*STEP  ← per weld/dwell/cool stage; PER-STAGE:
  *HEAT TRANSFER   (dt from driver schedule)
  *DFLUX (or user dflux activation line)
  *FILM / *RADIATE on staged film surfaces
  *OUTPUT etc.
*STEP  (mechanics per stage)
  *STATIC (increments)
  *TEMPERATURE (imported NT elset-wise / from file)   ← sequential coupling handoff
  *EXPANSION, *DLOAD GRAV (active elsets), *SPRING (fixture), *BOUNDARY clamped
  *PLASTIC enforced through material cards
  *NODE PRINT, NSET=TCS, FREQUENCY=1 → thermocouple .dat
  *EL PRINT  (inherent-stress audit bits, if needed)
*STEP  (springback: released fixture, 1e-9 reg spring)
*END
```

Plus files: `src/dflux.f` (generated/templated), `src/driver_data/*` (toolpath copy, src params), `probes.csv` spec, `job.sh` (ccx invocation), `run_config.json` (everything needed to reproduce).

### 10.3 Stage/schedule generation from the toolpath (port layer-bucketing verbatim)

Port these exact semantics from edp_builder (same array math):

- layer-bucketed windows by z with `0.45·h` tolerance; layer 0 center `hz_base + 0.5·h_bead1`, k-th `hz_base + h_bead1 + (k−1)·h_bead_sub + 0.5·h_bead_sub`;
- pState gating (weld vs dwell vs reposition) at the moving-end point;
- intended-arc integration over exactly the same boolean windows;
- dwell = window gaps (torch off between beads/layers; G0 lead-ins count as OFF — this is why FreeFEM's coverage was 98.5 %, not 100 %).

Suite test: builder-vs-toolpath window replay must match the FreeFEM builder byte-for-byte in window times on the regression toolpath (a shared golden file).

### 10.4 Deck validation pass (before solve)
- lint: keyword order feasibility, set references resolve (every NSET/ELSET mentioned exists), material names resolve, no duplicate labels;
- counts: Σ elements == Σ elsets; node count parity with loader;
- deck size budget and string-print budget asserted;
- dry-run "parse-only" ccx invocation (if supported by flags) to catch syntax cheaply.

---

## 11. The energy audit — reconstructing the ledger

### 11.1 Term-by-term recipes (ccx lane)

| Ledger term | ccx-lane computation |
|---|---|
| `intended_arc` | identical formula & window integration as FreeFEM lane (η·U·I·Σdt over weld windows) — same code, same golden numbers |
| `injected_arc` | lane A (subroutines): EXACT summation of `ccx_src_audit.log` (dflux trace) ⇒ **by-construction equality** with intended, preserving the framework's strongest guarantee. lane B: volume-integrate the applied flux over active elements per window (from the deck tables) ≤ relative tolerance vs intended (report value + tolerance) |
| `stored_enthalpy` | integrate H(NT) through the SAME Cp/latent curve as the deck, over element volumes (per-element volume from the exporter; pyvista/gridlib volume sums) at audit times (end of each stage + final) |
| `boiling_cap_removed` | ∫ over nodes of (T_calc − T_boil)⁺ region enthalpy surplus at each frame (same estimator as FreeFEM lane) |
| `surface_losses` | ∫∫ film+radiate fluxes over staged surfaces with true times (h(T−T_amb) + σ ε (T⁴−T_amb⁴)), sampled at history frequency |
| `quiet_node_discarded` | lane A: from deposit-subroutine log; lane B: window-bound integral of flux applied to still-quiet bands |
| `tamb_floor_added` | rectifier accounting: ∫ over nodes of (T − T_amb)⁺ corrections — same estimator |
| `prescribed_imposed` | prescribed-T lane bookkeeping (identity 0 unless lane enabled) |
| `numerical_residual` | Σ(all in)/intended − 1; target ≤ 1 % |

### 11.2 Shared curve discipline (critical)
The Cp/latent curve function lives in **one module** (`codegen/thermal_curve.py` — extracted from current edp_builder math) and is consumed by: deck generator (cp table), audit (`stored_enthalpy`), micro/hardness postprocessor. One source of truth prevents the classic drift bug (audit disagrees with deck).

### 11.3 `ccx_src_audit.log` protocol
One append-only file in the run dir: `timestamp_us, kind, value, element, elset, layer, extra_json`. Kinds: `flux_e` (per-element applied flux·dt), `quiet_reject`, `film_energy`, `radiate_energy`, `frame_marker`. The audit parser folds it into the nine ledger terms; the file is also the debugging ground truth. Suite: replay determinism test (generate deck twice → identical log modulo timestamps).

### 11.4 Checkpoint/resume semantics (gate A7-decided)
- Preferred: per-**stage** chaining — thermal job k → write NT field → mechanical job (load NT) → k+1; state = NT+U+PEEQ(+internal state) carried in files; resume = rebuild identical deck prefix, skip completed stages (their state files are the checkpoint).
- Fallback (A7 fails): layer-granularity rerun-from-last-layer with NT from completed layer (semantics slightly weaker — labeled in the report; ledger telescoping still holds because audits are computed stage-wise and summed).
- Guard: `deckSchemaStamp` in every head/state file (the `mechOrderCur` twin) — mismatch ⇒ refuse to resume with a printed explain (suite test replicates the EDP guard's spirit).

### 11.5 solver_results.json (ccx lane)
Same keys, plus `ccx_meta: {version, solver_backend: "spooles/pastix", inc_counts, sta_summary, activation_lane, melt_lane}`. `composite_format_version` bumps once; consumers hard-version-check (suite).

---

## 12. Live output, progress, control

### 12.1 ccx process control (`core/ccx/ccx_runner.py`)
Mirrors FreeFEM runner features: subprocess with `tee` to `sim.log` (keep `run_command_with_tee` reuse), `caffeinate -i` wrapper on macOS (framework precedent), thread-safe stop flag → SIGTERM then SIGKILL after grace, environment pinning (OMP threads = user option), stdout pattern subscription.

### 12.2 Progress model
ccx increments print step counters; `.sta` appends per-increment lines. Runner tails `.sta`: current increment / planned increments (the driver knows the planned stage count because IT generated the schedule) → % complete + ETA estimate (smoothed from recent increment wall-times). Exposed to GUI as: percent, stage label ("welding layer 4/10", "dwell", "springback"), rate, ETA — same UX semantics as FreeFEM runs today.

### 12.3 Live probes while running
For thermocouple-equivalent live updates: `*NODE PRINT, NSET=TCS, FREQUENCY=1` → `.dat` fills incrementally; a tail-parsing thread appends to the same live-probe CSV the GUI mini-plot reads ( FreeFEM lane today writes these from the solver; ccx lane reads from .dat tail). Same file names, same columns → zero GUI changes.

### 12.4 Cancel & resume UX
Stop button → runner SIGTERM; on relaunch, "resume newest checkpoint" checkbox mirrors FreeFEM behavior (uses §11.4 state files). Resume incompatibility (schema stamp mismatch) surfaces as a blocking dialog with the same wording class as the EDP guard's message.

---

## 13. GUI port (tab-by-tab contract)

| Tab | Changes under `solver=CalculiX` |
|---|---|
| Geometry | none (backend-independent) |
| Process | none; dwell/sync logic unchanged (double-check `_sync_dwell_to_mesh` keeps applying to ccx dt config) |
| Material | none; material_database.json drives ccx tables; a small "K-conversion applied at deck boundary (CCX)" info line appears in preview |
| Mesh | adds "Abaqus/INP export" indicator + per-set preview (counts per layer elset) |
| Physics | keys that are FreeFEM-labeled (lumping-adjacent, UVA family) get the "ignored under CalculiX" label and remain editable; new small section "CalculiX: activation lane, melt lane (Phase-0 chosen)" — read-only reflector of the chosen lanes |
| Solver | backend radio: **FreeFEM (MUMPS / UMFPACK / CG)** vs **CalculiX (SPOOLES / PASTIX if built)**; binary path pickers for each; adaptive-dt semantics note |
| Ultrasonic | shows "FreeFEM-only" banner when ccx selected (per task order); otherwise unchanged |
| OpenFOAM CFD | unchanged |
| Parametric & DOE | unchanged mechanics; sweep matrix now stamps `solver` per case; comparison canvas reads solver_results.json from either backend (mixed-backend comparisons allowed and labeled) |
| 3D Slicer & Twin | unchanged |
| Generated Script Preview | becomes backend-aware: "Generated Deck Preview" for ccx (renders `job.inp` sections + subroutine src snippet); k-conversion info; template help-keys |
| Simulation Log | streams ccx stdout identically (tee); adds `.sta` progress bar row mapping stage↔layer |

Rule: **no tab may go dead under the new backend** — every control either functions, is clearly labeled backend-specific, or is hidden with a one-click "show FreeFEM-only controls" disclosure. The suite has a GUI parity checklist (§19.5).

---

## 14. Parametrization (full contract)

### 14.1 The parameter surface (categories with representative keys; complete migration table §23.A)
- **Heat source**: `P_weld, eta, a_f/r_f/a_r/b/c (Goldak radii), mode`, `b_band, c_band, R_activate`
- **Material**: `material, material_base, material_dep, rho, T_sol, T_liq, T_amb, latent_heat, emissivity, h_conv, h_bot, nu, T_mech` (+ `material_database.json` property tables)
- **Mesh**: `nx/ny/nz_base, nx/ny/nz_dep, mesh_source, mesh_file, target_nodes`
- **Solver/time**: `theta, dt_weld, dt_wait, dt_cool, n_cool_steps, solver(MUMPS/UMFPACK/CG→ FreeFEM; CCX-SPOOLES/PASTIX), adaptive_dt, adaptive_fo_target, adaptive_dt_min/max, src_travel_fraction`
- **Probes**: `probe_points, probe_paths, probe_interval, path_samples`
- **Restart**: `restart, restart_every, restart_resume`
- **Modules**: `enable_radiation, k_liq_factor, enable_mechanical, enable_microstructure, mechanical_bc (isostatic/fixture_clamped/cantilever), enable_j2_plasticity, thermal_correctors(+tol), cp_spike_smooth_K, mechanics_order, mech_gravity, gravity_m_s2, h_prime_iso, mech_j2_relax, mech_dgamma_max, peeq_limit, mech_plastic_tol, max_plas_iter, trip_beta, ultrasonic_* family`
- **Geometry/slicing/sync**: layer_height, bead_width, hz_base_mm (+/_sync GU to solver), scale_factor, dwell

### 14.2 Rules
1. `solver` key selects backend; defaults and presets must remain loadable untouched (backward compatibility with existing runs).
2. Every parameter maps to exactly one of: **deck keyword / subroutine data file / driver-stage behavior / postprocessor / labeled-ignored** — the mapping is the migration table (§23.A), and the suite asserts completeness (no key unaccounted).
3. Derived values (arc energy, layer centers, window schedule) are computed in ONE shared module used by both builders → golden-file parity tests (already specified §10.3).
4. Sync semantics preserved: `_sync_dwell_to_mesh`-equivalent for ccx = dwell → `dt_wait` mapping identical (dwell is a toolpath quantity; solver consumes layer_pass_times — unchanged).

---

## 15. Automation & case generation

### 15.1 One-command run
`python run.py --stl <geometry> --solver ccx [--headless] [--preset DEFAULT] ...` → case dir, all stages (§16), gates, report; exit codes: 0 all-pass, 1 build/parse error, 2 QA-gate FAIL, 3 solver failure. Headless mode for cron/CI covers everything GUI does (GUI is a thin wrapper over the same API).

### 15.2 Parametric sweeps & DOE (unchanged mechanics)
`parametric_sweep.py` + GUI DOE matrix builder (`_generate_doe_matrix`): each dot → its own case directory (§16), parameters stamped, backend selectable per sweep (`solver` column), post-sweep comparison: peak T, u_z, vm, audit residual, wall time across cases (pandas → canvas PNG + CSV). Mixed-backend sweeps supported and *labeled per row*.

### 15.3 Batch resume policy
Sweep-level: skip cases whose `solver_results.json` already exists and passes gates (idempotent); single-case resume via §11.4.

### 15.4 CI
Nightly: full e2e on letter-Z (both backends), gates + suite; PR: suite + deck-lint only. (Section 5.3's CI skeleton applies.)

---

## 16. Directory & artifact contract (ccx)

```
waam_output/<YYYY-MM-DD_HH-MM-SS>/            case_outdir
├── CalculiX/                                  run_outdir (FreeFEM/ twin)
│   ├── parameters.json                        (exact copy of GUI/CLI parameter state)
│   ├── solver_results.json                    same schema (+ccx_meta)
│   ├── sim.log                                (tee'd ccx stdout + [CCX-RUNNER] lines)
│   ├── ccx_src_audit.log                      per-element flux trace (§11.3)
│   ├── job.inp  (+ stage_*.inp state-chain basis when per-stage mode)
│   ├── job.sta  job.cvg  job.dat  job.frd     native solver outputs (all preserved, retention §16.2)
│   ├── src/  dflux.f (+ mine), driver_data/   (toolpath.txt copy, src_params)
│   ├── toolpath.gcode  toolpath.txt  layer_pass_times.txt  toolpath.layer_times.txt   (unchanged from slicer)
│   ├── geometry_sets.json                     (the §8.1 sets contract, kept for reproducibility)
│   ├── <stem>.inp-mesh / <stem>.mesh          (ccx mesh twin + FreeFEM medit twin — both kept for cross-validation)
│   ├── probes_energy/ probe CSVs              (per-probe true-time histories, live tail)
│   ├── waam_data.csv  hardness_profile_z.csv  hardness_test_locations.csv
│   ├── plots/  (7 + probe figures)  field_tpeak_white.png  field_warpage_white.png
│   ├── visual_outputs/                        (build animation, renders)
│   ├── quarry/                                (scratch frames for plots, git-ignored)
│   └── report.html
├── manifest.json                              (all files+hashes+schema stamps+backend+ccx_version)
└── (FreeFEM/ when run with --solver freefem, itself unchanged)
```

Rules:
1. `run.py::_point_latest` maintenance: "open latest case" flows must follow a case even across backends (the pointer file records which).
2. Retention: never delete reports/audits/logs/parameters/toolpaths; `job.frd` may be zipped by a cleanup command after gates pass (compression is automated, deletion never automatic).
3. Every artifact written by code — never hand-patched; QA may REFUSE a directory whose stamps mismatch its contents.

---

## 17. Postprocessing, plots, report (zero forking)

### 17.1 The frame-source adapter
`postprocess/ccx_frames.py` normalizes ccx outputs into the FreeFEM postprocessor's frame model:

| FreeFEM data | ccx source |
|---|---|
| T-field frames (time series) | `.frd` NT (per output block) or `.dat` prints for probes |
| U field, final + per-layer accumulation | `.frd` U (per mech step); layer slicing via exporter maps |
| vm, PEEQ | `.frd` Mises/equivalent plastic strain (`*EL FILE` requests) |
| thermocouple histories | `.dat` NODE PRINT tail →same CSV schema as today (true times, columns locked) |
| layer windows/pass times | unchanged (toolpath) |

The adapter is the ONLY thing that knows about `.frd`; everything downstream (plots/report/GUI/canvas) consumes the normalized structure. `.frd` reading: small parser for ASCII frd (fixed-width, per-block) — the vendored-format approach from session precedent; `ccx2paraview` allowed as a dev-time cross-check, not a runtime dependency.

### 17.2 The 7 plots + extras (unchanged plotting code)
All produce from normalized frames. Parity test: render both backends' letter-Z outputs through the SAME plot call; assert same file names, keys, axes labels; numeric curves differ only within cross-solver tolerance (§23.H). Special care:
- plot_06 probe PNGs read the same `thermocouples` CSV (adapter writes it from `.dat`).
- plot_03 layer-buildup uses export-set layer names — invariant.
- hardness figures read the identical CSV schema produced from ccx NT (§7.4).

### 17.3 `report.html`
Unchanged; only content-values differ (audit values come from the ccx ledger; newton residuals from `.sta`; labeled-substitution annex section auto-included when lanes/melting substitution applies). A new report section, `backend-crosscheck`: side-by-side table FreeFEM ↔ ccx for this geometry IF the FreeFEM twin artifacts are present in case dir (optional deep case from CI; not required for normal runs).

---

## 18. Result analysis without human touch

### 18.1 Gate battery (executed in-process after the solve; report + exit code)

| Gate | Definition | Threshold |
|---|---|---|
| G1 audit closure | \|numerical_residual\| | ≤ 1 % (baseline 0.78 %) |
| G2 injection identity | lane A: intended==injected by construction; lane B: relative diff | equal / ≤ 1e-3 |
| G3 toolpath fidelity | layer-window replay count | 10/10-layer-style: == nlayers (no unmatched) |
| G4 convergence | ccx statement from `.sta/.cvg`: no unconverged increments; last mech stage force-residual below static criteria set by driver | parsed & recorded |
| G5 physical bounds | temperature range ⊂ [floor-accounted, T_boil+ε]; no NaN anywhere in results | hard |
| G6 displacement sanity | released-stage max |u| < 50 mm (rigid-body runaway guard) | hard |
| G7 mesh discipline | element/node counts match exporter contract; non-empty each layer elset | exact |
| G8 cross-solver (optional tall case) | ccx vs FreeFEM twin key-metric deltas per §23.H | tolerances from table |
| G9 audit hygiene | all nine ledger terms present & non-null (or explicitly labeled-null) | hard |
| G10 artifact integrity | manifest hashes match, schema stamp == current | hard |

Any FAIL → exit nonzero + `report.html` header banner "FAILED GATES: …" — the "without me touching it" enforcement. WARN items render yellow with explanations.

### 18.2 Auto-failure Triage
`run.py --triage <case>` prints a diagnosis: per-gate actual-vs-threshold + the last N solver log lines + the failing stage — mirroring the framework's existing "diagnose the CAD" pattern (reference: the mesher's self-diagnosis message with the working trimesh one-liner). This makes agent/CI diagnosis hands-free.

### 18.3 Post-run summary (no touch)
The runner's final stdout prints the "headline card" exactly like the FreeFEM path: peak T, u_z, vm, intended==injected, residual, converged, sim_time, plots count — same line format tagged `[CCX-AUDIT]`.

---

## 19. Test & regression porting (`tests/physics_suite.py`)

### 19.1 Structure
Current suite = 340 checks. Port adds modules; existing checks stay (hc backend!). Target sections:
- §D1 Static deck checks (pattern-parallel of §6 edp checks): every keyword block presence/order/material table sanity on `generated_decks/*.inp` — mirrored count target ≥ the edp §6 count.
- §D2 Builder/window replay golden tests (§10.3 golden file).
- §D3 Curve/audit unit tests (§11.2 single-curve; §11.3 log determinism; analytic melt plateau — replaces gate A4 permanently).
- §D4 Subroutine unit tests: Goldak integral == Q_total; toolpath window query edge cases; deposit activation semantics vs its spec.
- §D5 Runner protocol tests: `.sta` tail → percent; kill/resume; state-file handoff determinism (both lanes).
- §D6 Cross-solver benchmarks (tolerances §23.H): 1-layer slab, 2-layer slab, letter-Z, L-prism (uses clean geometry from the mesher regression — the /tmp artifacts become permanent fixtures `tests/fixtures/`).
- §D7 J2 validation twin (`validate_j2_mechanics.py` → ccx mode), wall-probe/ultrasonic twin, specimen-case twin.
- §D8 Mesher↔exporter round-trip (meshio read-back identical).

Expected suite size at parity: ≈ 380–420 checks (340 preserved + ccx twins). CI red on any regression. `--validate` in run.py gains `--validate ccx` variant.

### 19.2 Golden numerics locks
FreeFEM regression numbers (714.5 kJ, 2,862 °C, 0.017 mm, 387 MPa, 0.78 %) become locked references with an explicit FreeFEM-tag; ccx numbers recorded alongside — never overwritten silently: a value change beyond tolerance must drop a WARN with provenance (which backend, which commit).

---

## 20. Performance plan

Baseline (measured): FreeFEM letter-Z, 9,930 tets, 10 layers: **2,461 s** wall.
Expectations (to be measured at A10): honest budget — ccx SPOOLES direct on ~10k-element transient thermal over the same stage schedule should land within 0.5×–3× of that; mechanical steps with C3D10 at `mechanics_order=2` will be the expensive part (251k-DoF precedent < 7 GB).
Levers, in order of preference: (1) element budget of prior-t (already parameterized), (2) thermal stage grouping (already), (3) pastix build, (4) OMP threads; do NOT touch physics knobs (dt, tolerances) to buy speed — record all performance numbers in `manifest.json` per case and a `benchmarks.md` accumulation.

---

## 21. Risk register

| # | Risk | P | Impact | Mitigation |
|---|---|---|---|---|
| R1 | macOS user-subroutine build fails/fragile | M | High | Phase-0 gate A1 early; no-sub lane (§9.4) is a fully designed fallback; Linux CI unaffected |
| R2 | Activation semantics weaker than FreeFEM's masks (ledger can't be by-construction) | M | High | Property-scaling lane proven (OpenAM-SimCCX); trace-protocol audit keeps equality; G2 gate enforces |
| R3 | Consistent-mass numerics show undershoot on sharp fronts | M | Med | A6 quantifies; dt policy + recorded `tamb_floor_added` term; documented substitution |
| R4 | Latent heat via cp(T)-spike distorts audit vs FreeFEM enthalpy | M | Med | shared curve module + A4 analytic closure ≤ 2 %; suite locks |
| R5 | `.frd` parsing fragility (version format drift) | M | Med | pinned ccx revision + parser unit tests against shipped sample frd; ASCII mode |
| R6 | Performance regression vs MUMPS | M | Med | §20 ladder; budgets parameterized |
| R7 | ccx restart semantics inadequate | M | Med | per-stage chaining design (§11.4) independent of native restart; A7 decides |
| R8 | Toolchain drift (upstream ccx changes keyword behavior) | L | Med | pinned rev + suite; upgrade = explicit task with re-validation gates |
| R9 | Port creep into a full rewrite (scope explosion) | M | High | this document's "additive-only" rule: edp path untouched (it stays the reference backend); all new files are twins/adapters; suite must not lose a single check |

### 21.1 Execution bottlenecks of the port (operational, beyond R1–R9)

The risk register scores bad outcomes; these are the bottlenecks that will *actually eat the days* — where wall-clock and mechanical realities, not design choices, set the speed:

1. **Solver-run clock dominates everything.** One letter-Z e2e is ~2,461 s of solver time; debugging a physics mismatch means *dozens* of full runs. Code-writing speed is irrelevant here (the whole "agentic coding gets it done in days" qualifier from the estimate discussion); the schedule in §22 is therefore padded with run-parallelism in mind (slab cases for logic bugs, letter-Z only for parity gates). Practical rule: never debug mechanics on the 10-layer case — get logic green on slabs first.
2. **`dflux.f` trace I/O hazards.** The G2 identity (intended == injected) depends on per-element flux traces appended *from inside the solver*. With OMP threads this becomes per-thread files + post-solve merge, plus a flush discipline so a crash doesn't lose the audit; and file growth is unbounded unless the trace is bounded by design (periodic compaction of identical entries). Buffering choices trade crash-loss vs runtime.
3. **`.frd` ASCII precision vs audit tolerances.** FRD fields carry ~11–12 significant characters; G1 (≤1 %) is comfortable, but the lane-B injection tolerance (1e-3) sits at the precision edge — mitigation: pull the audit's critical quantities from `.dat` prints (higher fidelity) where possible.
4. **Deck-size ceiling in the no-subroutine lane.** Per-element `*DFLUX`+`*AMPLITUDE` decks grow to 10⁴–10⁵ lines (10¹–10² MB); ccx parse time and memory scale with it, and finer element budgets make it worse quadratically in some bands. The 50 MB suite cap (§9.4) will bite: expect the no-sub lane to be *feasibility* viable but not *production* comfortable — one more reason the subroutine lane is the target.
5. **Per-band elset combinatorics.** Activation via band elsets + per-stage material aliases multiplies by nlayers × stages × (quiet/active twins); deck generation time and ccx symbolic setup grow linearly-to-quadratically. Mitigation: band grouping policy in the exporter (merge adjacent same-state bands), asserted in the suite.
6. **Stage-chain overhead.** Per-stage ccx invocations (the checkpointing fallback, §11.4) pay model-setup cost per stage; with 10 layers × (weld+dwell+cool) stages this overhead is nontrivial. Mitigation: multi-step single-job decks where A7 permits, stage-grouping where it doesn't.
7. **Grid-locked state handoff precision.** Sequential coupling transfers NT per stage; any averaging or format truncation between thermal and mechanical jobs injects systematic error into *inherited stresses* — the most sensitive quantity in the mechanics stage. Mitigation: same mesh (inherent to the design), `.dat`-level precision for the transfer, plus a suite round-trip test (write state → read state → identical field).
8. **Dt-schedule parity testing cost.** The adaptive-Fo pre-pass must produce the *same* dt sequence as the FreeFEM loop on the same mesh; validating that golden test requires a mesh exported with per-element h and a recorded reference schedule — cheap to build, but every fix to either side re-runs a moderately sized benchmark.
9. **Mesher↔exporter drift.** Two output paths from one mesh (medit + INP) can drift silently (label sets, node ordering). The round-trip test (meshio read-back, §19.1 §D8) must run on EVERY suite invocation, not only at parity time.
10. **GUI event-loop interplay.** ccx is blocking + long-running like FreeFEM was; the existing runner pattern (double-fork + caffeinate + tee) is proven, but every new runner feature (`.sta` tailing, live probe CSVs) must be re-verified against the Tkinter event loop on macOS — the environment where the process-group hygiene issues were originally found.



---

## 22. Phased delivery plan (agentic-execution ready)

Estimates assume an agent doing the transcription/mechanical work and the human reviewing gates; the wall-clock is dominated by solver runs (§0 rationale). MVP = phases 0+1+2+4-lite+6-lite ≈ works e2e on one geometry.

| Phase | Content | Exit criteria (hard) | Days |
|---|---|---|---|
| P0 | Build + 10 gates (§6) | every gate has a RESULT line + decision record | 3–6 |
| P1 | `thermal_curve.py` extraction + `sets_exporter` + mesh-INP exporter + round-trip tests | medit∧inp coexist; suite D8/D1 greening | 3–5 |
| P2 | `inp_builder.py` skeleton w/ stage schedule + deck lint | deck dry-run parses; window golden test green | 5–8 |
| P3 | Subroutine lane: dflux.f + deposit lane + trace protocol | A3 rerun in production form; injected==intended identity live | 4–7 |
| P4 | Audit module + solver_results.json | ledger closes on slab cases ≤1 %; gates G1–G7 scripted | 4–7 |
| P5 | Runner: tee/sta/progress/kill/resume | GUI log + progress works headless; resume drill passes | 3–5 |
| P6 | Mechanics stage end-to-end (incl. fixture/release) | specimen case passes G1–G7; J2 twin green | 4–7 |
| P7 | Postprocessing + report + GUI tabs polish | all 7 plots + report render from ccx case; GUI parity checklist ✓ | 4–6 |
| P8 | Full zero-touch QA + cross-solver battery + suite port completion | gates G1–G10 all live; letter-Z ccx run passes every gate; suite ≥ 380 | 6–10 |
| P9 | Hardness/micro from ccx; hex lane (optional); pastix; documentation; twin-lane hooks T1–T2 (§23.K) | parity features labeled DONE | 3–6 |
| — | **Total (parity)** | | **39–67** |
| — | **MVP subset** | | **12–18** |

Sequencing note: P3 could start early in parallel of P2 (subroutines are deck-independent). The MVP boundary is deliberate: getting e2e first makes every later phase a refinement against G-gates instead of big-bang risk.

---

## 23. Appendices

### 23.A Parameter migration table (condensed; full keys preserved in §14.1)

| Parameter (current) | ccx disposition |
|---|---|
| `theta` | driver: ccx is implicit-BE by default per stage; keep key, honored=1.0 (other values → WARN labeled) |
| `dt_weld/dt_wait/dt_cool, n_cool_steps` | driver schedule (unchanged math) |
| `adaptive_dt, fo_target, dt_min/max, src_travel_fraction` | driver pre-pass on mesh + schedule (same algorithm; suite-locked vs FreeFEM dt sequence on same mesh) |
| `solver` | backend symbol: keep MUMPS/UMFPACK/CG for ff; add CCX-SPOOLES / CCX-PASTIX |
| `mechanics_order` | 1→C3D4, 2→C3D10 (ccx removes BETA flag) |
| `h_prime_iso` | `*PLASTIC` hardening table (linear) |
| `mech_j2_relax, mech_dgamma_max, max_plas_iter` | FreeFEM-loop-only keys → labeled FreeFEM-only under ccx (post-processor keeps peeq checks) |
| `peeq_limit` | QA post-gate (no solver clamp) |
| `trip_beta` | subroutine-composited expansion (if >0) else unused (both listed) |
| `ultrasonic_*` | labeled FreeFEM-only (task order) |
| `cp_spike_smooth_K` | latent band half-width in shared curve module |
| `thermal_correctors(+tol)` | native ccx table evaluation; keys honored as no-op under ccx (labeled) |
| `mechanical_bc` | isostatic→§7.3 mapping; fixture_clamped→K springs; cantilever→BC variant (preserve scenario set) |
| `inherent_strain_fallback/chi_*` | legacy ladder retained as-is under both backends (documented) |
| `restart, restart_every, restart_resume` | stage-chain semantics (§11.4) |
| `probe_*` | same CSV contract via `.dat` prints + deck nsets |
| material family | `*MATERIAL` gen from json (K-converted, header-stamped) |
| Goldak geometry family | `dflux.f` src_params |
| `b_band/c_band/R_activate` | alt-source mode in same subroutine |
| mesh family | unchanged → exporter |
| `enable_*` modules | same gates, engine-specific outcomes |

### 23.B ccx deck skeleton (condensed; production template lives in `codegen/inp_builder.py`)
See §10.2 — full keyword-order-validated exemplar will be emitted by the builder and locked by the suite; copy-paste blocks for FILM/RADIATE/PLASTIC/GRAV per docs while coding P2.

### 23.C `dflux.f` skeleton (data-file contract + trace protocol) — see §9.1; the template begins as `core/ccx/dflux_template.f` with: INIT read (toolpath+params), per-call window lookup, s-positioning, Goldak evaluation, `k_liq_factor` boost, trace append. Written with SI units and no wall-clock calls.

### 23.D No-subroutine lane example (per-face DFLUX+AMPLITUDE) — pattern from discourse; deck bloat documented; used only if A1 fails.

### 23.E Audit pseudocode
```
for stage in stages:
    injected += parse_trace(stage)          # or window-integral (lane B)
    intended  += windows_integral(stage)    # shared module
stored = integrate(H(NT(t), curve), V)      # shared curve module
lost   = film_int + radiate_int             # staged surfaces × time
cap, floor = rectifier_accounting(frames)
residual = (stored + lost + cap + floor + quiet + ...) / intended - 1
assert |residual| <= G1
write solver_results.json (+ccx_meta, schema-stamped)
```

### 23.F File-format cheat sheet
- `.sta` — per-increment time/residual lines (runner tail → progress; driver parse → newton fields).
- `.dat` — all `*PRINT` blocks (probe history; el-requested audit bits).
- `.frd` — field frames (NT, U, MISES, PEEQ); ASCII fixed-width blocks; parser in `core/ccx/ccx_parse.py` with sample-on-ship lock tests.
- `.cvg` — convergence summary per increment.

### 23.G Acceptance gates checklist (the zero-touch battery) — §18.1 G1–G10; scripted in `codegen/ccx_audit.py::run_gates();` invoked by run.py ALWAYS (no flag to skip — lazy mode is a CI-only exception recorded in the report).

### 23.H Cross-backend tolerance table (initial, refine after P8)

| Metric | FreeFEM ref (letter-Z) | ccx tolerance |
|---|---|---|
| intended/injected equivalence | identical | identical (lane A) / ≤1e-3 (lane B) |
| audit residual | 0.78 % | ≤ 1 % |
| peak T | 2,862 °C | ±3 % |
| final u_z | 0.017 mm | ±10 % (both are stressed; C3D10 default at parity stage) |
| peak vm | 387 MPa | ±12 % |
| stored-enthalpy closure | — | ≤2 % vs FreeFEM ledger |
| layer-window replay | 10/10 | 10/10 mandatory |
| sim wall time | 2,461 s | recorded, no gate in MVP |

### 23.I Glossary
- **Quiet elements**: elements present with near-zero properties until activated (the AM activation workhorse — proven in OpenAM-SimCCX).
- **Layer-bucketed windows**: the framework's scheduler: weld time windows assigned per z-layer from the toolpath (the thing that fixed clock drift).
- **Lane A/B**: subroutine vs no-subroutine implementations of source+activation (§9).
- **G-gates**: scripted zero-touch acceptance battery (§18.1).
- **deckSchemaStamp**: cross-artifact version guard (the `mechOrderCur` successor).

### 23.J Dead ends and attempted-but-unfinished experiments (evidence log)

Recorded so the port never repeats them unknowingly, and so the *lessons* are shipped, not just the failures. Each entry: what was attempted → what happened → the shipped consequence → what should be reincarnated under CalculiX.

| Attempt | Result (measured) | Shipped consequence | ccx-lane reincarnation |
|---|---|---|---|
| Mesh the hand-built L-prism (`/tmp/slice_chk/L.stl`) as the custom-geometry test case | `is_watertight=True`, exact volume, yet 0 tets in every engine; tetgen refused ("self-intersections"); manifold self-union did NOT sanitize (still 20 faces, 0 tets) | Root-caused to inverted concave cap triangulation; framework can now refuse loudly but still cannot auto-repair | Keep as the *expected-failure* fixture; build the self-intersection screen; the clean rebuild (`trimesh.creation.extrude_polygon`) becomes the geometric fixture (already planned, §19.1 §D6) |
| Force FreeFEM to read hexes from disk | `readmesh3` ignores the medit `Hexaedra` section (both spellings tested: 8 vertices, 0 elements) while `cube(2,2,2)` runs P1/Q2 natively (27/125 DoF) | Conclusion: hex math exists in FreeFEM, file loading doesn't — hex lane documented (§8.4) not shipped | Non-issue in ccx (C3D8 native); if the hex lane is built, ccx is the backend that can consume it without format surgery |
| TetGen as an alternative tetrahedralizer | python API mismatch ("too many values to unpack (expected 2, got 4)"); raw-union also refused for self-intersections | Route parked; gmsh ladder shipped instead (algorithms 4→7→1) | Re-probe only if gmsh-classify proves fragile in production; else parked permanently |
| HXT (gmsh Algorithm3D=10) on the failing unions | "HXT 3D mesh failed" | Deprioritized in favor of the 4→7→1 ladder | Same |
| Delaunay first in the retry ladder | Ground >7 min on a pathological shell (vs seconds for frontal 0-tet) | Reordered ladder to 4→7→1 with Delaunay last; 1800 s worker timeout added | Default ccx algorithm choice should respect the same "try cheap, then robust, then slow" doctrine |
| Consistent-mass thermal operator | Broke the discrete maximum principle: −30,087 °C dips; floor rectifier re-injected 39 % of arc energy (measured on the 2-layer benchmark) | Full-lumping operator shipped with audit quadrature kept identical (row sums preserved) | Documented substitution; gate A6 checks ccx's own scheme for the same pathology |
| Masked thermal mass during activation | −24 kJ (−17 %) audit residual: per-step balance stopped telescoping | Mass deliberately unmasked; quiet conduction/Robin masked instead | Same failure mode waits for the ccx lane: keep the telescoping test in the suite before changing masking |
| Ad hoc masked quadrature for the source audit | 15 kJ phantom gap vs assembly | `vSrcAudit` with matched quadrature → intended==injected by construction | The trace protocol (§9.1/§11.3) is the direct analogue; preserve by-construction semantics |
| Fixture on the wrong label (top of bead) | Nearly-free rigid body; Picard oscillation (Fresid 0.34→0.17) | Moved to plate underside (label 1) | ccx lane: fixture mapping (§7.3) carries the *lesson*, and the runaway test (2.1e7 mm) becomes a suite gate |
| Rigid-body released solve with no regularization | 2.1e7 mm "warpage" on a converged solve | 1e-9 regularization spring shipped, labeled pending 3-2-1 support | Isostatic mapping in P6 (§7.3) |
| UVA amplitude-driven Blaha effect | `ultrasonic_frequency` was plumbed, amplitude never read (elastic-only softening) | Both wired to the yield surface this session; still unvalidated vs experiments | Parked by directive ("forget UVA for now") — schema label rule covers it |
| `mechanical_model` / `chi_x/y/z` anisotropic inherent-strain keys | Declared, GUI-exposed, never read by the emitted solve | Dead-parameter audit created; keys now legacy-labeled with `inherent_strain_fallback` | §14.2 completeness rule prevents recurrence |
| FreeFEM parser + builder interaction bugs | f-string brace NameError from a brace in a comment; FreeFEM rejects ternary inside `max(a, b?c:d)` | Both fixed this session; the pattern-suite now guards the class | Same class applies to Fortran-in-f-string templates (§4 design rules; suite check §19.2) |
| Exact-tangency fusion (no embed bite) | `classifySurfaces` aborts ("Wrong topology of boundary mesh for parametrization") | 0.4 mm fusion bite remains mandatory; bite formula documented (0.10·h, capped) | Inherit; tangency remains unsupported (§1.9 A) |
| gmsh STL reader on small structurally-valid files (`square_rt.stl`) | Silent "Error loading" (20-facet files load fine) | Parked rabbit hole; workaround = round-trip through trimesh | Inherit; report as mesher warning when triggered |



---

### 23.K Digital-twin sensor-fusion contract (owning document — both backend plans reference this)

**Aim restated.** The pipeline's destination beyond self-parity is a **digital twin of the WAAM build**: asset-bound state, measured-world ingestion, measured-vs-predicted reconciliation, and — at the top of the ladder — whitelisted closed-loop corrections. This port does NOT build the twin (a separate workstream); it must FORECLOSE NOTHING, so the twin lane can be built later without touching physics again.

**K.1 Instrumentation to add in the WAAM cell** (requirements per stream; several already exist — substrate TCs, DDCS V2.1, visual outputs):

| Stream | Hardware | What it must deliver |
|---|---|---|
| Electrical (the arc is the richest built-in sensor) | Voltage/current acquisition from the power source (GMAW), ≥ 100 Hz, arc-on edge capture (RS-485 / OPC-UA / DAQ depending on source) | P_arc(t) = V·I; per-pass η characterization; power-deviation anomaly flags; `measured_arc` ledger column |
| Wire | Feeder encoder out + gravimetric wire-mass consumption per build | WFS_ENC(t), stickout proxy (voltage-coupled), wire-balance ledger column |
| Motion / controller | DDCS V2.1 stream (executed positions, arc edges, step events) | executed-vs-commanded schedule delta: dwell/G0 gaps, velocity profile error — resolves the "commanded vs measured" closure class already flagged (§1.9-E) |
| Thermal · stationary (have) | Substrate thermocouples at the existing probe stations (thermocouple channel CSVs) | formally sampled 1–5 Hz; stable channel naming per the probe-CSV contract |
| Thermal · dynamic (add) | Pyrometer or small IR/camera on the deposit surface; optional coax melt-pool camera (30–60 fps gray is sufficient) | melt-pool width/length/aspect features per frame; surface-temperature stream |
| Topography (add) | Post-pass laser line scan (or contact probe), one map per completed layer | actual layer height/width/bias map vs nominal h_bead — the single most twin-deciding datum (predicted 3.0 mm vs deposited 3.4 mm problem) |
| Ambient (have) | T / RH | convection boundary correction |

**K.2 Data plane (per-build, backend-agnostic)**
```
sensors/
  raw/           per-stream raw dumps (device-native formats)
  normalized/    parquet (or sqlite): ts_source, ts_anchor, s_toolpath, value
  events.csv     arc_start / arc_end / pass windows — SAME window definitions as the builders' golden schedule
  calib.json     per-stream calibration (η, h, ε tables per material/pass)
  session.yaml   asset identity: build stamp, geometry hash, wire batch, plate batch, controller id
```
Time-base rule: every sample carries `ts_source` (device clock) and, where available, `ts_anchor` (toolpath-relative second, computed by anchoring to arc edges). Fusion never trusts a single clock.

**K.3 Feature plane** — per-pass/layer reduced observables consumed by each assimilation lane:
- `arc`: P_arc(t), WFS(t), η̂, arc-length-normalized energy density → `measured_arc` vs `intended/injected` (the ledger gains a measured column).
- `thermal`: per-channel TC transients; cooling rates and Δt8/5 measured vs predicted (the same estimators the plot generator already computes); pyrometer surface T vs predicted frame-local values.
- `optical`: melt-pool width/length/area (frame segmentation), temperature.
- `topo`: per-layer height/width/bias maps, overfill counters, flatness slope.
- `motion`: executed-vs-commanded drift statistics.
- `wire`: consumption integral per pass vs toolpath contributions and deposited volume.

**K.4 Assimilation plane — the fusion ladder (levels, not one algorithm)**
- **L0 Calibration (offline, per material/pass combo)** — fit η, h_conv, ε from TC/optical histories vs solver frame predictions (via parameter sweeps now; Stochastic Tools Bayesian lane if the MOOSE path is chosen).
- **L1 Offline reconciliation = digital shadow (record-only)** — every case gains `measured_*` ledger columns; report annex renders predicted-vs-measured curves; gates **G11** (sensor data present & schema-valid), **G12** (energy closure |measured_arc − injected_arc| within appendix-table tolerance), **G13** (per-pass TC channel agreement) are *proposed* and run only when the sensor lane ships. No model state is altered.
- **L2 Near-live state observer (twin engine, still read-only on the process)** — a **surrogate ROM** (POD/latent-NN trained from the framework's own parametric ladder — this is what those runs are for) drives an EKF/UKF updating the *digital state* per pass (intra-pass where the ROM is fast enough), correcting: effective η drift, interpass temperature offsets, layer-height truth from topography. Full FEM per-step correction is NOT run in-loop (a ~2,461 s solve cannot observe a live melt pool; a surrogate is the only credible way in).
- **L3 Closed loop (whitelist-only feedback)** — allowed corrections, each with its own gate: (i) interpass-temperature gate (extend dwell / capped-power wait); (ii) next-pass power modulation caps; (iii) h_bead adaptation from topography for the NEXT layer; (iv) abort conditions (sag / blow-through / feed-instability detectors). Whitelisted `toolpath.txt`/G-code regeneration only; nothing bypasses the safety envelope or edits already-welded geometry.

**K.5 Artifact integration (applies to BOTH backend plans)**
- `solver_results.json`: reserved twin columns (`measured_arc_J`, `measured_coverage`, `twin_meta{...}`) — null/absent until sensors attach; schema bump once; consumers must accept absence.
- `report.html`: measured-vs-predicted annex section (hidden while no sensor streams exist).
- The case directories (calculix.md §16 / moose.md §16) gain only the `sensors/` stanza; the manifest hashes its contents when present.
- Gates G1–G10 untouched; G11–G13 activate with the sensor lane.

**K.6 Twin-lane phases (T-numbered, all optional, strictly post-P8)**
T1 ingest (raw → normalized + events) · T2 ledger fusion columns (L1 shadow) · T3 ROM trainer · T4 observer (L2) · T5 control hooks (L3 whitelist). None blocks MVP or parity gates in either backend.

**K.7 What the port must NOT do (twin-scope-creep guard)**
No real-time requirements on ccx/FreeFEM/MOOSE runs; no sensor-driven physics changes in P0–P8; audits remain deterministic-solver-time. The port's twin responsibility is **openness, not operation**.

---

## 24. Execution order recap (the shortest honest path)

1. P0 gates → decision record (this file is updated with gate outputs).
2. Mesh/sets + curve extraction (P1) — stable ground to build on.
3. Deck builder + dry-run (P2).
4. Subroutines + trace (P3) ⇒ **injected==intended restored by construction**.
5. Audit + gates (P4) ⇒ ledger closes on slabs.
6. Runner + UX (P5–P6) ⇒ mechanics parity.
7. Postprocess + GUI polish (P7) ⇒ daily-used tool.
8. Zero-touch battery + suite (P8) ⇒ **the ship gate** — `python run.py --stl letter_Z.stl --solver ccx` from a clean checkout, no human touches, exit 0, report green.
9. Stay twin-open (§23.K): ship the `sensors/` stanza + `measured_*` ledger reservations + asset-state fields with the first ccx release, so the shadow→twin lane (T1–T5) builds on a frozen backend without re-opening physics phases.
