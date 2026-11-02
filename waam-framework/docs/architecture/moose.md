# WAAM-Framework → MOOSE: Complete Porting Methodology

**Repository:** `WAAM-Framework` (backend swap: FreeFEM++ → MOOSE)
**Companion document:** `calculix.md` — the porting methodology for the CalculiX lane. The two documents share the same ground truth (§1.1–1.9 of `calculix.md`): same run-directory contracts, same `toolpath.txt`/`layer_pass_times.txt` semantics, same nine-term energy ledger, same `solver_results.json` schema, same seven plots, same GUI tab set, same 340-check suite, same measured baselines (714.5 kJ, 2,862 °C, 0.017 mm, 387 MPa, 0.78 % audit residual, 2,461 s). This document does not restate those; where a contract is identical it is **referenced, not repeated**.
**Target:** a zero-touch, fully parametrized MOOSE backend with GUI, live output, postprocessing, plotting, directory/case generation, and hands-off result analysis — at parity with the FreeFEM reference, using MOOSE's strengths (native checkpointing, parallel PETSc solves, h-adaptivity, Stochastic Tools UQ, PhaseField microstructure as a research lane) to *remove* limitations the FreeFEM backend shipped with.

---

## 0. Purpose, principles, and what changes vs. the CalculiX plan

### 0.1 Why a third backend document is warranted

MOOSE is not "another solver"; it is a **framework for building solvers** (Idaho National Laboratory, LGPL 2.1, C++/libMesh/PETSc). That has three structural consequences for this port, all favorable:

1. **The mover of the port is not the solver — it is the app.** In the CalculiX lane, physics lives in generated Fortran subroutines + decks. In the MOOSE lane, the deposition logic becomes a small set of **C++ classes in a project app** (kernels, materials, user objects) compiled ONCE, with every per-run variation expressed in a generated `.i` input file through MOOSE's native parameter system. This is architecturally *the same shape as the existing `codegen/edp_builder.py` → parameters → FreeFEM* pattern, transplanted: `parameters.json` → `moose_builder.py` → `waam_moose.i` (+ one compiled app). It means the framework's "one reviewable artifact per run" principle survives: the artifact is now the `.i` file.
2. **The hills CalculiX must climb disappear.** No Fortran toolchain (killed its R1), no missing element-birth primitives handled via per-band deck combinatorics (activation is an ordinary material function), no textual `.frd` precision ceiling on the audit (field output = Exodus II, double precision, ParaView-native), **native checkpoint/restart** (`Checkpoint` output + `--recover`), independent **dt-adaptation machinery** (`IterationAdaptiveDT`, `PostprocessorDT`), and MPI-parallel PETSc solves with MUMPS/SuperLU_DIST available — directly closing the FreeFEM-information "parallel production solves" and UMFPACK-OOM ceiling gaps.
3. **New hills appear and are named honestly here:** MOOSE gestures at *nothing* you get for free — element activation, Goldak moving source, the deposition schedule, the audit, the fixture release are all code you write as C++ classes (§7–§9). The learning curve (MOOSE class hierarchy, AD system, libMesh mesh semantics, PETSc flags) is real and is why the parity day estimate (§22) is similar to CalculiX even though whole subproblems vanish.

### 0.2 Definition of done (identical invariants, MOOSE clause added)

The ten non-negotiable invariants of `calculix.md` §0.2 apply verbatim, with backend symbols renamed (`"CCX"`→`"MOOSE"`), plus two MOOSE-specific clauses:

11. **Native restart must be used, not forked.** Checkpointing (`Checkpoint` output + `restart_file_base` / `--recover`) replaces the FreeFEM path's custom checkpoint files at layer/step granularity — the framework's `restart`/`restart_every`/`restart_resume` keys map onto native mechanics (gate M8), and the `deckSchemaStamp` guard becomes an app-level registered parameter bump.
12. **The activation material must pass the telescoping test.** The single most expensive bug class this session (masked thermal mass breaking the ledger: −24 kJ, −17 % residual; `calculix.md` §23.J) is *pre-registered as a suite test* in the MOOSE lane before the activation material is finalized: mass terms are UNMASKED by design; only conduction, Robin, and source are masked by the activation factor. If a refactor breaks telescoping, the suite turns red in CI, not in someone's windshield.
13. **Open twin lane.** Same hook package as the ccx plan's invariant 11 (owner: `calculix.md` §23.K): every `Moose/` case dir carries the `sensors/` stanza contract, `solver_results.json` reserves `measured_*` columns, report can render the measured-vs-predicted annex; no real-time/sensor requirements on any MOOSE run in P0–P8.

### 0.3 Reading map (structure mirrors `calculix.md`)

Same section numbering where content is analogous (§1 ground truth, §3 capability map, §4 architecture, §5 Phase-0 gates, §6–§9 physics, §10 deck generation, §11 coupling/checkpoint, §12 live output, §13 GUI, §14 params, §15 automation, §16 directories, §17 postprocessing, §18 zero-touch gates, §19 tests, §20 performance, §21 risks+bottlenecks, §22 phases, §23 appendices). §24 is new: the backend decision analysis (MOOSE vs CalculiX vs FreeFEM vs Abaqus/Ansys/other) you asked for; §25 is the execution recap.

---

## 1. Ground truth (delta form)

Everything in `calculix.md` §1 holds — module inventory, toolpath contract, `solver_results.json` schema and nine ledger terms, run-directory contents, the seven-plot set, the 12 GUI tabs, and the §1.9 shortfall inventory (missing features, bottlenecks, attempted-but-unfinished work with evidence). Only the **disposition column changes** for the MOOSE lane; §1.9's rows re-dispositioned as follows (this is the delta table — read `calculix.md` §1.9 for the "why"):

| Gap (`calculix.md` §1.9) | FreeFEM status | MOOSE disposition |
|---|---|---|
| A. CAD self-repair / self-intersection screen | Missing (refuse-only) | **Inherit** (mesher is backend-independent); screen remains a shared backlogged build |
| A. Hex/quad file-loaded meshes | Stalled (`readmesh3` ignores `Hexaedra`) | **Fixed class** (libMesh reads `cube`/prism/hex, and Gmsh MSH; C8H* elements native). Layer-aligned hex lane becomes realistic in `moose` (verify in gate M9) |
| A. TetGen fallback lane | Stalled | **Park** (gmsh ladder remains the mesher) |
| B. Consistent-mass conservative scheme | Labeled compromise (lumped) | **Fixed properly reachable**: MOOSE integrates the consistent (lump-free where desired) operator with standard algorithms; the DMP pathology and lumping tradeoff is *your dt/mesh choice again*, benchmarked at gate M2 |
| B. Radiation view factors | Missing (linearized Robin) | Partial: `GrayLambertNeumannRadiationBC` exists (view-factor-to-boundaries radiation) — better than linearized Robin; still not full shielding/chamber model |
| B. Solver-driven h-adaptivity | Missing | **Fixed**: native `[Adaptivity]` markers; *but* activation + extra-element-ID coherence under refinement is a research lane (gate M9) |
| C. True isostatic/3-2-1 restraint | Compromised (1e-9 spring) | **Fixed properly reachable**: penalty supersprings via Contact module or TensorMechanics spring BCs (gate M5 verifies the exact mechanism) |
| C. Volumetric-locking-free plasticity at coarse order | Compromise (P1-locked; P2+J2 BETA) | **Likely fixed**: TensorMechanics `IsotropicPlasticityStressUpdate`/`IsotropicHardeningStressUpdate` radial-return (native J2 with isotropic hardening), independent of element order; C8H/Tet suppress hex-class locking differently — gate M5 fingerprints |
| C. Fully-coupled thermo-mech | Missing (by design, sequential) | Optional lane: MOOSE *can* run coupled temperature-displacement system literally in one executioner's variable list port — retained sequential by default (same decision as the ccx plan §0.3) |
| D. Grain-scale microstructure | Missing | **Research lane fixed in principle**: PhaseField module (dendritic solidification, grain evolution) — the only backend in the open-source set with this; not MVP |
| D. UVA | Partial (unvalidated) | **Parked by directive** (same as ccx plan) |
| D. Multi-material pools | Partial | **Inherit** (`material_database.json` → `*Materials` properties; same regression coverage) |
| D. Marangoni/OpenFOAM chain | Hooked only | **Inherit + additional degree**: MOOSE Navier-Stokes (INSFV) module offers in-solver melt-pool CFD as a far-future lane replacing the OpenFOAM sidecar if desired (out of MVP) |
| E. Power modulation / weave / interpass enforcement / supports | Missing | **Inherit** (router/scheduler gaps are backend-independent in both alternatives) |
| E. Live propulsion-feedback (measured-vs-commanded) | Missing | **Inherit** |
| F. Parallel production solves / memory ceiling | Partial (serial MUMPS; UMFPACK OOM >100k) | **Fixed**: MPI + parallel mesh + PETSc MP-solvers standard (gate M10); MUMPS/Aclumulator via the bundled PETSc build (SuperLU_DIST fallback) |
| F. Iterative solver lane | Partial (CG exists unused) | **Fixed class**: PETSc KSP/PC preconditioners optioned natively |
| F. GPU | Missing | Off the roadmap (MOOSE PETSc has CUDA endpoints, but this is not the GPU lane for MVP) |
| G. Experiment auto-calibration / UQ | Missing (channels only) | **Partially fixed**: Stochastic Tools module (samplers, Bayesian calibration) gives a native UQ/calibration platform; wiring platforms to measured data is still shared backlog |
| H. Dead-parameter class rule | Fixed (audit retained) | Inherit |

**Net expectation:** a MOOSE lane closes more of the §1.9 gap column than the CalculiX lane does, and at *cleaner* engineering cost (C++/no Fortran), but with higher physics-authoring burden — and the audit/telemetry discipline must be rebuilt as native MOOSE objects rather than as generated-script text.

**End-goal note — the project aims for a digital twin.** Both backend plans serve a program whose destination is a **digital twin of the WAAM build**: per-asset state, measured-world ingestion, measured-vs-predicted reconciliation, whitelisted closed-loop corrections (planning engine → digital shadow → twin). The owning contract for everything twin-related is **§23.K of `calculix.md`** (per this document's own RM7 rule: shared changes live in the document that owns the contract). The MOOSE lane's twin obligations are therefore exactly the openness hooks of `calculix.md` §0.2 invariant 11 — `sensors/` stanza, reserved `measured_*` ledger columns, report annex — plus nothing else during P0–P8.

**Forward pointer:** a second-generation *flexibility architecture* built on this lane — zone ledger, mixed meshes, torch/fixture rosters, Qt model-tree GUI — is drafted separately in **`moose_v2.md`** (dev-roadmap plan). Its phase gates are prerequisites for nothing in this doc, but P0–P6 here are prerequisites for it (the v1 builder core is reused).

---

## 2. Target architecture

```
                     ┌──────────────────────────── run.py (orchestrator) ───────────────────────────┐
                     │  slice (mesh/slicer_api.py)          [UNCHANGED]                             │
                     │  → toolpath.txt, toolpath.gcode, layer_pass_times.txt                       │
                     │  mesh (mesh/stl_pipeline.py)         [UNCHANGED + meshio Exod/conversion]    │
                     │  → mesh.exo (ExodusII) + .mesh (medit, FreeFEM twin both kept)               │
                     │  build (codegen/moose_builder.py)    [NEW twin of edp_builder.py]            │
                     │  → waam_moose.i + audit/plot contract map + CSV/Ledger contracts              │
                     │  solve (moose_runner)                [NEW; console tail, cpr checkpoints]     │
                     │  → waam_app -i waam_moose.i (compiled-once WAAM app)                        │
                     │  audit (codegen/moose_audit.py)      [NEW nine-term ledger from CSV/exo]     │
                     │  → solver_results.json (schema-identical, +moose_meta)                       │
                     │  post (postprocess/*, GUI already)   [UNCHANGED via adapter]                 │
                     └─────────────────────────────────────────────────────────────────────────────┘
```

New/changed modules:

| Module | New/Modified | Responsibility |
|---|---|---|
| `waam_moose/` (project app) | NEW (C++) | One MOOSE app: `WAAMGoldakKernel` (or material+kernel pair), `WAAMToolpathUserObject`, `WAAMActivationMaterial`, `WAAMEnergyAuditUserObject` (+ per-thread-safe accumulation), optionally `WAAMConvectiveFluxBC`/`WAMMRadiationBC` (staged film/radiation with activation gating), app-level input parameters registering the entire parameters.json surface |
| `codegen/moose_builder.py` | NEW | Generates `waam_moose.i` + the contract map (probe station nset names, output intervals) — mirror of `edp_builder.py` architecture, incl. f-string discipline and the warnings channel (`[MOOSE-BUILDER] …`) |
| `moose_builder` appreciation of `thermal_curve.py` | Shared (extraction done once for both alternative backends) | The ONE Cp/latent curve module (calculix.md §11.2) → typed into the `.i` as piecewise tables, consumed by materials, audit, and hardness postprocessor |
| `core/moose/moose_runner.py` | NEW | Process control: console tee (`run_command_with_tee` reuse), live CSV tail, checkpoint counting, stop flag, `caffeinate` reuse (macOS, framework precedent) |
| `mesh/stl_pipeline.py` | Modified (additive) | `write_exod(...)` via meshio (or gmsh→exodus via gmsh's `write` in Exodus format directly — gmsh has native Exodus output since v4.x; **choose ONE path and lock it with a round-trip test**); medit `.mesh` writer untouched |
| `codegen/moose_audit.py` | NEW | Nine-term ledger from audit UserObject CSVs + postprocessor CSVs + exodus fields; writes `solver_results.json` with `moose_meta` |
| `run.py` | Modified | Backend plumbing (`find_moose_app()`), case dir `Moose/`, `--solver moose`, exit contracts identical |
| `gui/app.py` | Modified | Backend selector + `.i` preview + runner metrics (§13) |
| `postprocess/moose_frames.py` | NEW adapter | Exodus → the framework's normalized frame model (feeds the unchanged `plot_generator.py`) |
| `tests/physics_suite.py` | Extended | MOOSE twins (§19); expected ≥ 380 checks at parity |
| `generated_moose/` | NEW | Static preset `.i` files (DEFAULT.i, uva preset) pattern-checked like suite-§6 |

The FreeFEM and (if built) CalculiX paths remain untouched; the port's additive-only rule applies to all three lanes.

---

## 3. MOOSE capability map vs the physics list (`calculix.md` §1.4 #1–20)

| # | Framework capability | MOOSE native | Verdict |
|---|---|---|---|
| 1 | Enthalpy latent heat | Apparent heat capacity via smooth phase-band Cp table (the `thermal_curve.py` piecewise table — same math as the FreeFEM enthalpy form in the discretized limit). PhaseField has true phase-change lanes (heavy) | **Build-as-table**; parity gate M2 |
| 2 | θ-scheme / BE | TimeIntegrators (Implicit-Euler default, BDF2, Crank-Nicolson) | **Native**; `theta` map documented (1.0 ↔ ImplicitEuler, 0.5 ↔ CrankNicolson) |
| 3 | Goldak double-ellipsoid | No builtin; the documented MOOSE pattern is a custom Kernel (or ADKernel) evaluating a moving formula, plus per-element activation masks | **Build** `WAAMGoldakKernel` (§7.2); integral test = suite |
| 4 | Alt. heat sources | Same custom-kernel surface (one kernel with a `source_model` parameter, exactly like the FreeFEM multi-source design) | **Build** (one class, mode-switched) |
| 5 | Quiet-element activation | No builtin birth; the MOOSE-native pattern is an activation-material with property switching driven by a time/position function (UserObject), plus extra-element-ID co-track if refinement needed | **Build** `WAAMActivationMaterial` (§7.3) — the most delicate class in the port |
| 6 | Convection + radiation BC | `heat_conduction` module: convective flux BCs; `GrayLambertNeumannRadiationBC` for view-factor radiation; voxel/one recording lind | **Native + small custom wrapper** for the activation factor on the film side |
| 7 | Boiling cap | No cape | **Build** as wrapper material + audit accounting (same as ccx plan) |
| 8 | Lumped matrix scheme | Not applicable/lane lost — MOOSE is always the consistent operator | **Substitution documented**; gate M2 measures the FreeFEM's documented pathology class directly |
| 9 | Adaptive dt | `IterationAdaptiveDT` (growth/cut factors, error-based), `PostprocessorDT` (dt steered by a postprocessor — can literally host the Fourier-number rule) | **Native + small custom**; golden parity test retained (same dt sequence vs the FreeFEM schedule on the same mesh) |
| 10 | Property iterations (`thermal_correctors`) | Consistent evaluation of T-dependent material properties is intrinsic each Newton iteration | **Native (superior)**; keys retire to "no-op under MOOSE" labels |
| 11–14 | Mechanics: elasticity, thermal strain, J2+hardening, gravity, fixture+release | TensorMechanics: `ComputeLinearElasticStress` family + `ComputeThermalExpansionEigenstrain`, `IsotropicPlasticityStressUpdate`/`IsotropicHardening*` (radial-return), `Gravity` kernel, penalty/spring guidance; release stages via normal MOOSE step inputs | **Native + mapped**; A5-style fingerprint gate M5 |
| 15 | microstructure/hardness | PhaseField module (dendrites, grain evolution) as a research lane; the shipped Vickers pipeline is postprocessor-only from NT histories (same as ccx lane) | Inherit + research lane |
| 16 | UVA | none | **Parked** |
| 17 | Acoustic / Marangoni / OpenFOAM | MOOSE Navier-Stokes (INSFV) as a future in-solver option; OpenFOAM sidecar unchanged | Inherit |
| 18 | Probes (points/paths, true times) | `Postprocessor` system: `PointValue` (nsets at stations), integrals; CSV output system with true times (`execute_on=TIMESTEP_END`, CSV output native). Path probes: pre-interpolated stations at deck-gen time (same approach as ccx plan) | **Native + contract map**; same CSV contracts as FreeFEM lane (the framework's `probe_points` keys keep meaning) |
| 19 | Checkpoint/resume | **Native**: `Checkpoint` output (`[Outputs]`), `restart_file_base`, `--recover`, `--half-transient`; UserObject state restartable if declared restartable | **Native** — replaces the FreeFEM path's own checkpoint mechanism; gate M8 = equivalence of monolithic vs resumed result |
| 20 | Multi-material | `*Materials` per-block, T-dependent property functions native | **Native** |
| Direct solvers | MUMPS (41x) | PETSc with MUMPS/SuperLU_DIST (bundled builds): 249k-DoF-class mechanical solves feasible *in parallel* | **Native**; §20 performance gate |
| Mesh.io + adaptivity | readmesh+gens | libMesh + `[Adaptivity]` markers (GradientAdaptivity, ErrorFractionMarker) | **Native** (activation coherence under refinement = M9) |
| Mesh formats in | medit `.mesh` core | **libMesh supports**: Exodus (.exo/.e/nemesis), Gmsh msj files, Medit format has support? LibMesh has a `MeditImport`? libMesh DOES have `MediReader`? historically "Medit Import" isn't in mainline; don't rely — convert via meshio Exod II (the "round-trip, ONE path" decision addr) | Convert; not load |
| Output | .edp-side | Exodus II (ParaView native), CSVs, checkpoints, console | **Native** |
| GUI | Tkinter | Ensures existing MOOSE GUIs (peacock) are NOT used — the framework's own GUI governs, same as ccx plan | Tkinter retained |
| License | — | LGPL 2.1 (+ INL grant wording) | Commercial use by the terms is allowed; record the exact grant text into `core/moose/BUILD_NOTES.md` per pinned version |

**Shared module note.** `thermal_curve.py` extraction (calculix.md §11.2) is the shared ground between both alternatives; it is the first file P1 lands (§22), since both deck lanes and the audit need the same curve.

---

## 4. Toolchain & builds

### 4.1 The decision that removes `calculix.md` R1
No Fortran anywhere. The app is C++17 compiled against MOOSE; per *run* configuration is a text `.i` file — per-run "subroutine recompilation" (a CalculiX-lane cost) disappears entirely.

### 4.2 Two install lanes (pin one; put SHA into `core/moose/BUILD_NOTES.md`)
1. **conda/mamba binary lane (recommended to start):** install the INL environment (`moose-dev` metapackage from the MOOSE channel, tag-pinned); instant env; includes paraview-split assists; verify the pinned tag ± suites.
2. **Source lane (research-grade control):** build MOOSE + required modules: `framework`, and the needed modules: `heat_conduction`, `tensor_mechanics`, `phase_field` (research lane), `stochastic_tools` (UQ upgrade lane), plus `contact` (isostatic-restraint verification). Build with MPICH/OPENMPI; run `./run_tests -j N` green per module before app work.
Gate M verifies the chosen lane: M1 = install fresh, `python -c "import moose"`‑equivalent smoke (a demo `.i` run + `./waam_app-opt -i` work), and this runs on macOS Apple Silicon Linux/Windows in CI with equivalent behavior.

### 4.3 App skeleton
Scaffold via the MOOSE app starter (stork convention): `waam_moose` with `src/base/WAAMApp.C` registration; classes live under `src/kernels/`, `src/materials/`, `src/userobjects/`, `include/base/`. Every class registers its own `InputParameters` names — **this is the bridge that makes `parameters.json` the single source of truth** (§15).

### 4.4 CI
Linux matrix: conda build of the app + full suite + nightly e2e (letter-Z) with both FreeFEM and MOOSE; gate failures hard-red. Portability note: physics forks only acceptable with an issue number that ships in `manifest.json`.

---

## 5. Phase 0 — feasibility spike (mirrors `calculix.md` §6 structure; gates M1–M12)

Each gate: small setup + printed `RESULT …` line + decision record appended to the plan. Bounded probe time ~6 agent-days; any failed gate re-scopes the MOOSE design, not the deadline.

| Gate | Question | Setup | PASS criterion |
|---|---|---|---|
| M1 | Install lane works on this Mac (Apple Silicon) | §4.2, demo `.i` runs, app skeleton runs | `WAAM-Demo RESULT: pass` on toy heat kernel |
| M2 | Thermal with latent-heat band parity | 1-layer slab; analytic latent closure vs NT-integrated enthalpy | closure ≤ 2 %; DMP-style check for the consistent-operator pathology (record if present; dt mitigations) |
| M3 | Goldak kernel integral + toolpath march | per-quadrature-point integration of the kernel over a fine volumetric test = Q_total; marching footprint vs `toolpath.txt` clock | integral rel-diff ≤ 1e-4; window open/close within half a dt of the schedule |
| M4 | Activation material telescoping | 2-layer slab, audit ledger | NO phantom mass (replicate the ccx plan's −17 % failure-expectation test as a *negative control*: masked-mass variant must fail the suite), unmasked-mass telescopes exact |
| M5 | J2 + thermal-strain fingerprint | bar + mini-weld case vs analytic/FreeFEM fingerprint | vm/peeq within cross-solver tolerances; restitution/relax fits stable; records the isostatic mechanism verified (penalty vs spring) |
| M6 | Film + radiation BC parity | plate cooling vs FreeFEM reference | T(t) mid-cool within tolerance; `GrayLambertNeumann` vs linearized δ documented (calculix.md A5 analogue) |
| M7 | Sequential coupling via exodus | thermal → NT in exo → mechanical job `SolutionUserObject` imports NT at the exact right times | field round-trip preserved (identical grid: exact readback); monolithic vs staged equivalence measured |
| M8 | Native restart parity | `Checkpoint` + `restart_file_base` mid-run resume vs monolithic letter-Z slab | residual-state equivalence; layer granularity matches `restart``/<every>` |
| M9 | Adaptivity + activation coherence | AMR on activation front + `extra_element_ids` | correct `fa` after refinement (no orphan deposit faces); marks feasibility only (facility lane, not MVP) |
| M10 | Parallel + memory ladder | 250k-DoF mechanical + 85k-DoF thermal (same probes as FreeFEM's ≤7 GB / 249k-DoF Measurement) | wall-times recorded; memory flat or better; no-sided ladder in manifest |
| M11 | Audit/postprocessor plumbing | `PointValue` CSVs, integrals, `VectorPostprocessor` for probe-path variables, time-true outputs | same CSV contracts (names, columns, times) as the FreeFEM lane produce at *bind-level* byte-parity |
| M12 | (optional lane) Stochastic tools sample | a 4-case MonteCarlo demonstration over `no` parameter → outputs | CSV round trip per case id; informs §16 | 

Gate output: `core/moose/PHASE0_REPORT.md` + decision record (activation lane, latent lane, dt policy, restart policy, restraint mechanism).

---

## 6. Thermal stage translation

| FreeFEM (today) | MOOSE realization | Fidelity expectations & notes |
|---|---|---|
| Unknown = enthalpy H; T recovered from H | Unknown = NT; latent heat inside Cp via the shared `thermal_curve.py` piecewise band (apparent heat capacity) | Same discretized physics; the FreeFEM "exact at any dt" enthalpy-mass statement holds in the limit; audit uses the *same* curve for `stored_enthalpy` (one-source-of-truth rule — calculix.md §11.2) |
| ρ, cp, k: T-dependent fields | `WAAMMaterial` with T-dependent properties from `material_database.json` (moose units: **K** surfaces! the material tables convert C→K at property-call time, recorded in the header stamp) | Map directly; property ideality naturally consistent |
| θ=1 BE schedule (dt_weld/dt_wait/dt_cool + adaptive Fo) | Executioner with `ImplicitEuler`; per-stage time-block written by `moose_builder.py` in the SAME clud schedule (dt sequence golden-locked to the FreeFEM loop on the same mesh, via `IterationAdaptiveDT` disabled in parity mode, enabled in production mode) | The Fourier cap and source-travel cap live in a `PostprocessorDT`-fed postprocessor or precomputed dt list — the faster rule is: parity first, adaptivity lane later (M2/M9) |
| Robin hBot/hSurf on labels 1..6 with psiActive gating | film BCs (heat_conduction module) on `nset_<label>` surfaces, times a `fa` activation factor per quadrature point (small custom BC wrapping the native convective form, or driven by a `fa` material function) | Exact semantic parity: film only acts where material exists; label→nset mapping from the sets contract |
| σ ε (T⁴−T_amb⁴) radiation | First phase: same linearized Robin form (custom radiation BC with the `fa` factor). Upgrade lane: `GrayLambertNeumannRadiationBC` view-factor radiation | Phase-0 shape: find parity baseline; the view-factor lane is an *upgradation* documented not shipped |
| Goldak source + pState windows | `WAAMGoldakKernel` (+ mode-switched gaussian/conical/band source params) querying `WAAMToolpathUserObject` for position/window state | §7.2 details; unit test locked (M3) |
| Boiling cap | Material-side clamp (abduces effective cp blowup beyond T_boil) + audit accounting of `boiling_cap_removed` computed from field history frames | Report the term identically |
| Fully-lumped operator availability | Not present in MOOSE — always the consistent operator | Substitution documented; gate M2 gives the Cold Standard record on whether consistent-integration needs the same mitigation (bigger dt, finer create path) — the FreeFEM-lane shipped documentation of the pathology (−30,087 °C, 39 % re-injection) is the stronger baseline |
| Energy audit | `WAAMEnergyAuditUserObject`: per-element injected (dt·q·V) aggregated per timestep, output as CSV ledger (the analogue of `ccx_src_audit.log`, but native and clean: no thread hazard, restartable) | By-construction equality retained: intended (window integration in `moose_builder`) == injected (kernel integral aggregated by the UO) |
| Adaptive-dt source-travel cap | The dt truncation rule (torch advance ≤ src_width/8 per step) computed by the driver (same formula) or forced via `IterationAdaptiveDT` max-dt | Golden-locked schedule |

### 6.1 Stage/window semantics — carried over verbatim
Layer-bucketed window replay, pState gating, dwell == OFF standers, 0.45·h tolerance, layer-center z formulas (`hz_base + 0.5·h_bead1`, then `hz_base + h_bead1 + (k−1)·h_bead_sub + 0.5·h_bead_sub`) — ported *identically* into `moose_builder.py`; the same golden file test as the ccx plan (§10.3) asserts byte-for-byte window equality with the FreeFEM builder (shared single-curve single-schedule principle).

---

## 7. Deposition & activation (the physics-critical part, as in the ccx plan)

### 7.1 The lane
Property-scaled quiet material — the same decision as CalculiX lane, implemented *in C++ instead of generated Fortran subroutines*: 

1. Every deposit element exists from t=0, marked by its layer ID (`extra_element_id` or elset-name convention).
2. `WAAMActivationMaterial` computes the **activation factor fa(x,t)** at every quadrature point: `fa = 0` while the deposition front has not reached the element's centroid arc-length (per the ToolpathUserObject state at the current sim time), then ramps it 0→1 within the smoothing window (same activation-band constant as the FreeFEM path's psi-activation transition, to keep comparisons consistent).
3. Properties evolve per the paper-standard quiet-element scaling: `k_eff = k_quiet + fa·(k_active − k_quiet)`, `ρ` constant (never scaled — invert at `os of the audit telescoping rule), `cp_eff = same curve + smoothing`, mechanical `E/σ_y` carried by fa into the TensorMechanics materials.
4. **The telescoping suite test is written BEFORE the material** (gate M4): masking mass instead of k is forbidden by construction — the −24 kJ failure mode of the FreeFEM lane is a pre-registered negative control.

### 7.2 `WAAMGoldakKernel` (spec)
- InputParameters registered from the same schema keys (source_model, goldak front/rear radii, efficiency, indices/pState data lookup).
- At each quadrature point × timestep: fetch current window from the ToolpathUserObject; if in-window, compute the Goldak formula front/rear (coordinate transform to local beam frame); else q=0. Track and aggregate per-element energy per timestep into the audit UO (dt·q·V via `elementVolume` or computed from the element auxiliary). This is the by-construction injected-arc collector.
- Optional per-window `k_liq_factor` boost as a fa-conductive property interaction (same rule as FreeFEM).
- AD discipline: implement as an ADKernel so property dependencies and Jacobians are automatic; `fa` is fetched from the ToolpathUserObject at material time (not a coupled-variable dependency), so no manual sensitivity work is needed.
- Registration: kernel parameter names chosen so that `moose_builder` can emit `.i` `[]` blocks with human-readable keys matching `parameters.json` 1:1 (audit + GUI preview both read them).

### 7.3 `WAAMToolpathUserObject` (spec)
- Input: `toolpath.txt` + `layer_pass_times.txt` + `src_params` (one data file copied into the run dir for reproducibility).
- Maintains: sorted weld-window table, per-layer z-centers, arc-length parameterizations, state (weld ON/OFF/dwell/reposition); one stable API for kernels/materials/books: `currentWindow()`, `positionAt(t)`, `fa(elCentroid, t)`; restartable (declared restartable so Checkpoint resumes carry the schedule pointer).
- Determinism rule (same as ccx lane): ALL decisions from toolpath times; zero wall-clock reads.

### 7.4 The audit UO
`WAAMEnergyAuditUserObject`: accumulates per-timestep: injected (from the kernel aggregation), quiet-rejected (integrated where fa<1), film/radiate passes (SideIntegral postprocessors or UO callbacks); writes one axis-referenced CSV row per timestep: `time, layer, injected_J, quiet_rejected_J, film_J, radiate_J, ...`; plus frame markers at stage boundaries. `moose_audit.py` folds this CSV into the nine ledger terms — replacing the ccx trace-file approach with native restartable state (a G2 robustness *improvement*).

---

## 8. Mechanics stage translation

| FreeFEM | MOOSE | Notes/pitfalls |
|---|---|---|
| `[P1]³` small-strain + thermomech load | TensorMechanics with linear displacement variables (C3D-equivalent order) + `ComputeLinearElasticStress`, inherited T-field drives `ComputeThermalExpansionEigenstrain` | Same door; inertia none (static); gravity via the `Gravity` kernel (fa-gated — custom trivial wrapper or material-activated body force) |
| J2 + isotropic hardening (h′=1.5 GPa), peeq_limit, Picard | `IsotropicPlasticityStressUpdate` + `IsotropicHardeningStressUpdate` (radial return, native), peeq_limit becomes QA post-check | The FreeFEM nodal-Picard-vs-quadrature distinction **dissolves** (MOOSE integrates at q-points, native) — this is a correctness *upgrade* counted in the capability map |
| λ, μ from T-dep E,ν | `ComputeIsotropicElasticityTensor` T-dependent | direct |
| Fixture springs (label 1, clamped → released with 1e-9 reg) | First lane: penalty `spring` BCs / penalty-Dirichlet pairs; better lane: **Contact module** penalty contacts on the fixture surface. Release stages as separate step inputs weak spring retained (the 2.1e7 mm lesson is a suite gate) | gate M5 chalks the exact mechanism |
| Springback stage | Normal step with released restraint | identical model semantics |
| Newton iterations/residuals → JSON | Executioner/PETSc diagnostics: from console + `.json` outputs (MOOSE can dump solver statistics) | mapped into the same `newton_*` JSON keys |
| TRIP (trip_beta) | Constitutive option (custom eigenstrain class, small) OR labeled-unimplemented (default 0 unexercised) | same handling as ccx plan |
| Mechanics order (P1/P2) | variable order (FIRST/SECOND displacement bases) | C3D10-analogue un-beta-ed (gate M5 fingerprints hex/tet) |

### 8.1 Optional fully-coupled lane
One `[Executioner]/[Variables]`-class coupled solve (temperature + displacements in one linear system) is *supported* by MOOSE directly; it is deliberately NOT the default (same §0.3 rule as ccx): the sequential, staged, audit-per-stage design is the validated architecture. A Phase-0-cleanup variant may be recorded in `PHASE0_REPORT.md` for later exploration.

---

## 9. The MOOSE app — authoring guide (what you write, what you get)

### 9.1 Files you write (approx. scope)
```
waam_moose/
├── include/
│   ├── kernels/WAAMGoldakKernel.h          (AD)
│   ├── materials/WAAMActivationMaterial.h  (quiet packing/activation/fa)
│   ├── materials/WAAMThermalMaterial.h     (T-dep k, cp, ρ; thermal_curve pieces)
│   ├── userobjects/WAAMToolpathUO.h        (schedule, restartable)
│   ├── userobjects/WAAMEnergyAuditUO.h     (ledger state, restartable)
│   ├── bcs/WAAMConvectiveFluxBC.h          (fa-gated film)  [optional: also radiation]
│   └── base/WAAMApp.h
├── src/            (the .C files)
├── tests/          (M-grid app tests registered into the 340+ suite)
└── unit/           (C++ unit tests for Goldak integral, fa query, curve)
```
That is **7–9 small C++ classes** — the whole physics surface that had to exist as generated Fortran in the ccx lane (dflux/deposit/e_c3d/resultstherm) is explicit class work here, compiled once, parameterized per run. Bug surface shrinks; testability rises (C++ unit tests are *faster* than deck tests).

### 9.2 What you get native (no code)
Checkpoint/restart; exodus/CSV outputs with true times; MPI parallelism; PETSc solver stack; adaptivity; mesh renumbering; window semantics from command line; restartable UserObject state; recovery CLI; TSV/JSON console; log colorization; test harness.

### 9.3 Discipline carried over from `edp_builder`/ccx plan
- All `.i` text generated from ONE builder with the same f-string escape rules (`.i` uses `[Blocks]` and quoted strings — fewer braces than FreeFEM but the suite still greps forbidden raw strings).
- Every run prints tagged progress lines (windows `[MOOSE-RUN…]`, `[G-CODE]`, `[ARC AUDIT]` equivalents) so parsing is grep-able — the same contract the framework already enforces on the FreeFEM path.
- Warnings channel `[MOOSE-BUILDER]` and `[MOOSE-AUDIT]`, same conventions (report.html annex, gates).
- `deckSchemaStamp` = a registered input parameter (e.g., `waam_schema = "2026-10-18.15"`) checked on resume by the audit module (equivalent of `mechOrderCur`) — native since it is a checkpointed app parameter.

---

## 10. Deck generation (`codegen/moose_builder.py`) — the `.i` twin

Same architecture rules as calculix.md §10 (mirror of edp_builder, same warnings channel, same parameter validity errors, same unit boundary discipline: **`.i` carries SI with K-converted material tables**, recorded in the header stamp), with MOOSE-specific content:

### 10.1 The generated artifact set
```
waam_moose.i                main input (single file preferred for review)
    [Mesh]        file = mesh.exo   (+ layer blocks via subdomain naming from sets contract)
    [Variables]   T [ (thermal stage) ; disp_x/y/z (mechanical stages) ]
    [Kernels]     heat conduction + WAAMGoldakKernel + Gravity (mech)
    [Materials]   WAAMActivationMaterial + WAAMThermalMaterial + TM models (fa-driven)
    [BCs]         Dirichlet (probe-driven or spring) + WAAMConvectiveFluxBC (+radiation)
    [UserObjects] WAAMToolpathUO + WAAMEnergyAuditUO
    [Postprocessors] PointValue@TCS stations, element integrals, side integrals
    [Executioner] staged Transient blocks (per stage dt from the driver schedule)
    [Adaptivity]  off in MVP (M9 later)
    [Outputs]     exodus (interval), CSV (postprocs, true times), Checkpoint (restart), console
waam_moose.i.meta           parameter hash, toolpath hash, schema stamp, backend = moose
run_config.json             reproduction envelope (like ccx plan)
```

### 10.2 Stage/window schedule generation
Ported verbatim from `edp_builder` — same layer-bucketing (0.45·h, layer-center z formulas), same pState gating and dwell semantics; the shared golden test (window equality vs the FreeFEM builder on the regression toolpath) is P1 deliverable (§22).

### 10.3 Deck validation pass (pre-solve)
- `.i` lint: block-nesting sanity, referenced nsets/elsets exist (from the sets contract), parameter names exist in the app's registered InputParameters (a **static registry check**: enum of every accepted key — this automates the §14.2 completeness rule), no duplicated out-of-block sections;
- warm-up dry-run: MOOSE supports a *parse-only* pass (app exits after input parsing via flags) — exercised in CI cheaply;
- counts: Σ elements per layer elset == exporter; node count parity.

---

## 11. Sequential coupling and checkpointing

### 11.1 Thermal → mechanical handoff (native)
1. Thermal stage job writes NT field to Exodus at intervals covering the full time series (interval = stage closure).
2. Mechanical stage job loads NT via `SolutionUserObject` (reads exodus, interpolates in space AND time — same mesh ⇒ exact readback, gate M7 proves field round-trip at float equality).
3. Driver-level stage chaining (`moose_runner`) — the same orchestration shape as the ccx plan §11.4 ("per-stage chaining"), except the state transport is a native high-fidelity format rather than domain-specific file surgery.
4. Optional *coupled* lane (§8.1) is recorded, not shipped.

### 11.2 Checkpointing (native — replaces ccx-plan's hand-built chaining as an option)
- `restart = layer|step|off` maps to: layer ⇒ `Checkpoint` output at every layer-boundary stage with a `restart_file_base` rerun; step ⇒ Checkpoint every `restart_every` timesteps.
- Resume: `--recover` (or `restart_file_base`) picks the newest `.cpr`; the ToolpathUserObject and the audit UO are declared restartable so schedule pointer and ledger state resume exactly (suite test: monolithic vs resumed equivalence — M8).
- This REMOVES the CalculiX plan's biggest open risk (R7: restart semantics) and gives the same UX the FreeFEM lane's "resume newest" behavior delivers — the runner will print identical `[CCX-RUNNER]`-style `[MOOSE-RUNNER]` stage lines plus resume provenance.

### 11.3 `solver_results.json` — same schema, plus `moose_meta`
Keys identical (`calculix.md` §1.3); `moose_meta` adds: `{app_git_sha, moose_version, petsc_version, executioner_summary, checkpoint_lanes, activation_lane}`.

---

## 12. Live output, progress, control

| Aspect | FreeFEM lane today | MOOSE realization |
|---|---|---|
| Streaming log | `run_command_with_tee` capture | identical (same runner plumbing) |
| Progress | implicit; after-the-fact stage lines | console prints *per timestep*: time, dt, residual, KSP iterations — the runner computes a *better* progress model than the ccx lane (timestep-aware, not stage-count-only) |
| Live probes | thermal-side CSV written by the script | `PointValue`/`VectorPostprocessor` CSVs grow per `TIMESTEP_END` — GUI mini-plot reads the same files/columns; live figure parity is native |
| Cancellation | SIGTERM-with-grace pattern (framework precedent: double-fork + caffeinate) | same harness; MOOSE responds cleanly to SIGTERM mid-step, and the `.cpr` checkpoint is exactly the resume handoff |
| ETA | stage-count extrapolation | timestep-count + smoothed dt estimate |

The live-output parity gate is M2-part of the P5 phase acceptance (§22), not a separate phase.

---

## 13. GUI port (mirror of calculix.md §13, MOOSE line items)

| Tab | MOOSE changes |
|---|---|
| Geometry / Process / Material / Mesh | none / none / K-conversion note in preview / adds Exodus export indicator + per-layer elset preview |
| Physics | FreeFEM-only keys labeled; a MOOSE controls sub-pane appears (activation lane, restart policy, adaptivity off/on) reflecting Phase-0 decisions; MOOSE lanes reflect the app's registered parameters automatically (one source: InputParameters registry) |
| Solver | backend radio FreeFEM (MUMPS/UMFPACK/CG) | CalculiX (SPOOLES/PaSTiX) | **MOOSE (MUMPS / SuperLU_DIST / PETSc-KSP)**; binary locator for the app per backend; dt-parity note |
| Ultrasonic | "FreeFEM-only" banner as directed |
| OpenFOAM CFD | unchanged |
| Parametric & DOE | unchanged; mixed-backend comparisons labeled |
| 3D Slicer & Twin | Exodus renders through the same pyvista path |
| Generated Script Preview | becomes "Generated Input Preview" (`.i`; sections + registered-key docs) — same live re-render as today's edp preview |
| Simulation Log | streams exactly as today; plus per-timestep progress bar (§12) |

The GUI-parity checklist test (§19) applies per backend.

---

## 14. Parametrization

### 14.1 The mapping principle (a structural improvement over both ccx/FreeFFEM lanes)
Every `parameters.json` key becomes a **registered InputParameter** of the app, so the builder never invents keys and the app validates unknowns at parse time — the dead-parameter class bug (`calculix.md` §23.J) is *structurally* prevented, because unregistered keys abort loudly at startup.
`moose_builder.py`'s job: parameters.json → `[Blocks]` with the registered names; the generated `.i.meta` hashes parameters + toolpath; the migration table is `calculix.md` §23.A reused with MOOSE column (the semantic mappings for `theta`, dt, mechanics order, peeq_limit, ultrasonics, material family, and mesh family all carry across in the same labels — only mechanics-loop keys like `mech_j2_relax`/`mech_dgamma_max` retire entirely (native radial return) instead of being passthrough warnings).

### 14.2 Presets & golden files
`DEFAULT` and `uva_waam_ss308l_ss316` generate `DEFAULT.i` / `uva_waam_ss308l_ss316.i` into `generated_moose/`; suite-§6 pattern checks apply (block presence ordering, key coverage vs parameters.json, material K-conversion stamp).

---

## 15. Automation & case generation (calculix.md §15 semantics, unchanged)

Same `run.py` single command, same exit-code contract (0 / 1 / 2 / 3), same `_point_latest` behavior, same batch-idempotency, same sweep mechanics (`parametric_sweep.py` and the GUI DOE tab unchanged, mixed backends labeled). The **MOOSE-specific upside** recorded as a backlog lane: the Stochastic Tools module (gate M12) can later replace the grid-DOE loops with native Monte Carlo / optimization / Bayesian calibration runs *shipped through the same case-dir contract*, which is the cleanest reachable path to the §1.9-G gap (UQ/calibration).

---

## 16. Directory & artifact contract (`Moose/` twin)

```
waam_output/<stamp>/
├── Moose/                        (the FreeFEM twin layout per calculix.md §16)
│   ├── parameters.json           solver_results.json          sim.log
│   ├── waam_moose.i              waam_moose.i.meta            run_config.json
│   ├── mesh.exo                  (+ <stem>.mesh — medit twin kept for cross-validation)
│   ├── out_exodus/               (field frames, .eXXXX / – single .exo with time steps)
│   ├── out_csv/                  (postprocessor ledger CSVs — true times)
│   ├── checkpoints/              (.cpr per Checkpoint interval)
│   ├── toolpath.gcode  toolpath.txt  layer_pass_times.txt       (unchanged)
│   ├── geometry_sets.json                                  (sets contract)
│   ├── waam_data.csv  hardness_profile_z.csv  hardness_test_locations.csv
│   ├── plots/  field_tpeak_white.png  field_warpage_white.png  visual_outputs/
│   └── report.html
├── manifest.json
```
Rules inherited: retention never deletes reports/audits/logs/parameters/toolpaths; artifacts are code-written only; stamps are enforced.

---

## 17. Postprocessing, plots, report

All seven plots and the report use the unchanged generators via the frame adapter (`postprocess/moose_frames.py`): Exodus → pyvista/pyvista-frames → normalized model (exact inverse of the FreeFEM postprocessor contract: same variable names, same true times). The Exodus position is a *strength* over the ccx plan: double-precision, ParaView-native, time-series native — and pyvista (already in the framework's stack per README) reads Exodus out of the box. Hardness CSVs come from the `NT` frames through the same phase-logic postprocessor (identical schema). `report.html` untouched; a backend-crosscheck annex may appear like the ccx plan. The adapter is the only file that knows the word "exodus" (same layering discipline as the ccx plan's `.frd` layering).

---

## 18. Zero-touch result analysis (same G1–G10 gate battery, MOOSE data sources)

All gates from calculix.md §18.1 keep their thresholds; the *data sources* differ: ledger from the audit UO CSVs (native restartable = the trace-file hazards of the ccx plan §21.1-#2 vanish); convergence from Executioner/PETSc diagnostics; bounds checks from field frames esp. exodus; G6 displacement sanity identical; artifact integrity covers `.i.meta` stamps. A duplicate G2-method risk (ccx lane's `.frd` precision) doesn't apply: Exodus doubles are exact-enough by construction (still asserting the parser round-trip in the suite).

---

## 19. Test & regression porting

| Suite section | MOOSE-lane content |
|---|---|
| §19.1 D1 (deck patterns) | `.i` static checks on `generated_moose/*.i` — mirrors suite-§6 edp pattern checks 1:1 |
| D2 (window golden) | shared with ccx lane: same golden file |
| D3 (curve/audit units) | shared `thermal_curve.py` tests + kernel-integral test (Goldak == Q_total); latent-band closure (analytic) |
| D4 (subs to interfaces) | C++ unit tests: fa query, toolpath UO, activation transitions, kernel modes |
| D5 (runner protocol) | runner tailing, kill/resume via native checkpoints, state handoff |
| D6 (cross-solver) | slab/letter-Z/L-prism cases both backends; same tolerances as calculix.md §23.H |
| D7 (J2/specimen twins) | `validate_j2_mechanics.py` gains a MOOSE mode; wall-probe/ultrasonic and specimen cases likewise (ultrasonic remains FreeFEM-only by directive) |
| D8 (mesher/exporter round-trip) | meshio/gmsh-Exodus read-back equality (byte-level labels) |
| NEW D9 (MOOSE-native) | restart equivalence (monolithic vs `--recover`); adaptivity coherence (M9, when lane enabled); multiple-timestep resume determinism |

Total suite size target ≥ 380–430 at full parity (both backend lanes combined), monotone-increasing per CI gate.

---

## 20. Performance plan

Baselines (FreeFEM): letter-Z 10 layers 9,930 tets → 2,461 s wall, serial MUMPS; mechanical ≤ 7 GB at 251k DoF class; UMFPACK OOMs >100k DoF (documented in the parameter table).
MOOSE lane expectations (to be MEASURED at M10): same element budget with Hidden-Dim method differences can shift walltime ±20–50 %; the decisive advantage is *parallel lane*: MPI-parallel PETSc (MUMPS/SuperLU_DIST direct or KSP+PC for larger meshes) should beat serial MUMPS beyond ~50k DoF; adaptivity is a per-case *time saver* only when M9's activation coherence is proven (do not enable before). All numbers recorded per case in `manifest.json` + accumulated `benchmarks.md` (same discipline as the ccx plan).

**Run-profile ownership note (RM7):** the *serial-vs-parallel decision system* — per-geometry suitability model, measured scaling probes at 1/2/4/8/… cores with early-stop, solver profiles per mode, and the serial-replay/parallel-tolerance reproducibility policy — is **owned by `moose_v2.md` §17**; it consumes this lane's M10 benchmark methodology. Serial replay stays the deterministic backbone for gates and the suite in BOTH lanes. Mesh-kernel options (incl. native-MOOSE generators and the layer-cake lane) are analyzed in `moose_v2.md` §18.

---

## 21. Risks and execution bottlenecks (MOOSE-specific)

| # | Risk | P | Impact | Mitigation |
|---|---|---|---|---|
| RM1 | MOOSE learning curve slows the port (class system, AD, libMesh) | H | High | 9 small classes only (§9.1); unit-test-first (M3/M4 before mechanics); pair with §23 day estimates |
| RM2 | Activation-material subtlety (the ccx lane's hardest class replicated in C++) | M | High | same lane design as calculix plan §9.2 with better tooling (restartable UO, unit tests); M4 negative-control test |
| RM3 | Builds/environments drift (conda channel changes, pin rot) | M | Med | pinned SHA in BUILD_NOTES.md; CI matrix; source-build documented as an escape hatch |
| RM4 | Exodus/adapter edge cases (per-time output naming, gxyz/nek meshes) | M | Med | round-trip suite test; single export path locked in P1 |
| RM5 | PETSc/solver flag choices mis-fit (direct vs iterative, preconditioning) | M | Med | M10 ladder; defaults locked after measurement, options exposed as registered parameters |
| RM6 | Port creep (sameentre as ccx-plan's R9) | M | High | additive-only rule (§0.3); both prior lanes untouched |
| RM7 | Momentum loss across two canvases (moose.md + calculix.md maintained) | M | Med | decision: shared changes go into whichever document OWNS the shared contract (audit, plots, dirs) and others cross-reference — no content forks |
| RM8 | PhaseField/GrainTracker scope explosion (research-lane temptation) | M | Med | hard MVP line: D-lane items enumerated as optional P9 (§22); acceptance gates are physics-parity, not research deliverables |

Execution bottlenecks (mirror of calculix.md §21.1, MOOSE-specific items): C++ instantiate-build-test cycles dominate unit-fix time (slower off the printer than Python but each correction later compounds); debugger disinline with consoles (admitted environment habit); the ToolpathUserObject query cost O(log n) per element per timestep at 10⁵ elements × 10³ steps requires a per-layer binning discipline (build it in from day one); checkpoint volume management for 250k-DoF classes (`.cpr` sizes recorded in manifest, retention rule same as the ccx plan).

---

## 22. Phased delivery plan (agentic-ready, exit criteria hard)

| Phase | Content | Exit criteria | Days |
|---|---|---|---|
| P0 | Install + gates M1–M12 | decision record in `PHASE0_REPORT.md` | 4–7 |
| P1 | `thermal_curve.py` shared module + Exodus/meshio exporter + sets contract + round-trip tests | `.exo` <-> medit coexist; D8/D1 green | 3–5 |
| P2 | `moose_builder.py` skeleton (stages, dt schedule, registry lint) | dry-run parses; window golden test green | 5–8 |
| P3 | The app: ToolpathUO + ActivationMaterial + GoldakKernel + audit UO (M3/M4 in-app tests) | M3/M4 RESULT lines; injected==intended live | 6–10 |
| P4 | Audit module + `solver_results.json` + gates G1–G7 | ledger closes on slabs ≤ 1 % | 4–7 |
| P5 | Runner (console tee, progress, kill/resume native) | GUI log + progress works headless; resume drill passes (M8) | 3–5 |
| P6 | Mechanics stage (TensorMechanics + fixture + release + springback) | specimen case passes gates; J2 twin green (M5) | 4–8 |
| P7 | Postprocess + report + GUI tabs polish (`generated_moose` presets) | all 7 plots + report render from a MOOSE case; GUI parity checklist | 4–6 |
| P8 | Zero-touch QA + cross-solver battery + suite completion | gates G1–G10 live; letter-Z MOOSE run exits 0; suite ≥ 380 | 6–10 |
| P9 | Optional research lanes: PhaseField microstructure, Stochastic Tools UQ, adaptivity-after-M9, coupled lane, twin-lane hooks T1–T2 (owner: `calculix.md` §23.K) | each lane = separate outcome record; none MVP-gating | 6–12 |
| **MVP boundary** | P0–P4 + thin P5 (headless) | MOOSE case runs e2e on one geometry, audit green | **19–32** |
| **Full parity** | all through P8 (excluding research lanes) | same Go-live contract as calculix plan | **39–61** |

The two documents' phase skeletons are intentionally parallel so shared infrastructure lands once (P1 extraction served both; P8's gate battery shared).

---

## 23. Appendices

### 23.A Parameter → `.i` mapping (condensed; full carries from `calculix.md` §23.A)
`theta` ↔ TimeIntegrator choice (ImplicitEuler/BDF2/Crank-Nicolson, labeled); `dt_*` ↔ per-stage Executioner blocks; `adaptive_dt*` ↔ PostprocessorDT lane (production) / precomputed list (parity mode); `solver` ↔ `MUMPS | SuperLU_DIST | KSP+PC`; `mechanics_order` ↔ displacement variable order (FIRST/SECOND); `h_prime_iso` ↔ `IsotropicHardeningStressUpdate` table; `peeq_limit` ↔ post-check only; `mech_j2_relax` / `mech_dgamma_max` / `max_plas_iter` ↔ **retire** (native radial return; keys rejected at registry lint under MOOSE and labeled under FreeFEM); `trip_beta` ↔ optional eigenstrain class or labeled-off; `ultrasonic_*` ↔ parked label; `cp_spike_smooth_K` ↔ latent band in `thermal_curve.py`; `thermal_correctors*` ↔ retired no-op (native property evaluation); `mechanical_bc` ↔ isostatic: penalty-spring/Contact mechanism (gate M5), `fixture_clamped`, `cantilever` variants preserved; `restart/restart_every/restart_resume` ↔ native `Checkpoint`/`restart_file_base` intervals; `probe_*` ↔ `PointValue`/`VectorPostprocessor` CSV contract (same names/columns); material family ↔ `WAAMThermalMaterial` tables from `material_database.json` (K-converted, stamped); Goldak family ↔ `WAAMGoldakKernel` params via `src_params` data file + `.i`; `b_band/c_band/R_activate` ↔ alternate source models in the same kernel (mode parameter); mesh family ↔ `mesh.exo` exporter (unchanged upstream); `enable_*` ↔ same gates.

### 23.B Generated `.i` skeleton (condensed form; the builder emits the full validated deck)
```
[Mesh]
  file = mesh.exo
  # subdomain IDs == layer IDs from geometry_sets.json (exporter contract)

[Variables]
  [T] [family = LAGRANGE; order = FIRST] []     # thermal stages
  # displacement vars for mechanical stages (order per mechanics_order)

[Kernels]
  [diffusion]    type = HeatConduction;      variable = T; ...
  [source]       type = WAAMGoldakKernel;    variable = T;      # mode, radii, eta ...
  [gravity]      type = Gravity;             variable = disp_z; # (mech, fa-gated)

[Materials]
  [wam_material]  type = WAAMActivationMaterial      # fa, layer id, masks
  [wam_thermal]   type = WAAMThermalMaterial         # k(T), cp(T) band, rho
  [wam_mech]      type = ComputeIsotropicElasticityTensor + IsotropicPlasticityStressUpdate ...

[BCs]
  [film_i]  type = WAAMConvectiveFluxBC;  boundary = '<nset_labelI>'; h = h_conv [h_bot]
  [rad_i]   type = WAMMRadiationBC;       boundary = '<nset_labelI>';   # linearized (parity) lane
  [clamp]   type = PenaltyDirichletBC / spring-pair; boundary = '<nset_label1>'  # fixture (gate M5 mechanism)

[UserObjects]
  [toolpath]  type = WAAMToolpathUO;    toolpath_file = toolpath.txt; layer_times_file = layer_pass_times.txt
  [audit]     type = WAAMEnergyAuditUO; toolpath_ref = toolpath;   # restartable

[Postprocessors]
  [tc_i] type = PointValue; variable = T; point = '<TCS i>'       # CSV out, true times
  [stress_max] type = ElementExtremeValue; ...                     # (mech stages)

[Executioner]
  type = Transient
  scheme = implicit-euler                                        # maps theta
  [TimeStepper] type = ConstantDT / PostprocessorDT ...           # driver schedule / adaptive lane
  solve_type = 'PJFNK' | 'NEWTON'; petsc_options = '...'          # MUMPS/SuperLU via -pc_type

[Outputs]
  [exodus]  file_base = out_exodus/<stem>; interval/sequence per stage closure
  [csv]     file_base = out_csv/probes; execute_on = 'TIMESTEP_END'   # true times contract
  [checkpoint] file_base = checkpoints/<stem>                       # restart = layer/step
  console
```
Validation: registry lint (every key exists in the app's InputParameters), set references resolve, dry-run parse pass.

### 23.C C++ class skeleton notes
- `WAAMGoldakKernel::computeQpResidual()` — fetch `u.time`, `u.point` from the ToolpathUO; if out-of-window return 0; else standard Goldak front/rear formula at the q-point coords; kernel parameter names == schema keys. Add AD for Jacobians.
- `WAAMActivationMaterial` — `computeQpProperties()`: `fa = toolpath.fa(_current_elem_centroid, _t)`; emit `_k_eff`, `_cp_eff`, `_rho` (ρ unscaled — telescoping rule), `_fa` property for BCs/mechanics; latent band folded into cp table.
- `WAAMToolpathUO::execute()` — maintains schedule state; **declared restartable**; per-element binning by layer id (O(log n) queries).
- `WAAMEnergyAuditUO::execute()` — accumulates per-timestep energy bookkeeping (fed by the kernel and side integrals); writes the ledger CSV row per timestep; restartable; frame markers at stage boundaries.
- Unit tests cover: Goldak integral == Q_total; fa transition band; telescoping (M4 negative control); cp table closure (analytic latent test).

### 23.D Activation math (shared with the ccx plan)
`fa(x,t)`: 0 while deposition front arc-length s(t) < s_elem − w/2; smoothstep→1 across the activation band; k/cp/E/σy scale linearly in fa; ρ NOT scaled; film/radiation BC activity multiplied by the surface's fa at q-points. Same constants as the psi-transition of the FreeFEM lane for cross-solver comparability.

### 23.E Audit folding pseudocode (mirror of `calculix.md` §23.E)
```
for stage in driver_schedule:
    injected += audit_uo CSV rows (dt·q·V)   # or window integral in parity mode
    intended += builder window integral      # one shared module
stored   = ∫ H(NT, thermal_curve) dV        # exodus frames (double precision — no .frd ceiling)
lost     = film_int + radiate_int           # side integral CSVs
cap/floor= rectifier accounting from frames
residual = Σ/intended − 1                   # ≤ 1 % gate
write solver_results.json (+moose_meta, schema-stamped)
```

### 23.F File-format cheat sheet (MOOSE lane)
- `.exo` Exodus II — field frames, double precision, ParaView/pyvista-native (no `.frd` parsing at all).
- `out_csv/*.csv` — postprocessor time histories (probes, integrals, ledger rows) with true sim times.
- `checkpoints/*.cpr` — native restart states (Checkpoint output).
- `console` — per-timestep lines (time, dt, residual, linear/nonlinear iterations).
- `.i`/`.i.meta` — generated inputs + human-readable stamp block (parameter/toolpath hashes, schema).

### 23.G Gates checklist
Phase-0: M1–M12 (§5) with decision record in `core/moose/PHASE0_REPORT.md`. Shipping: G1–G10 (`calculix.md` §18.1, MOOSE data sources per §18). CI: nightly e2e letter-Z both backends + suite.

### 23.H Cross-backend tolerance table
Identical to `calculix.md` §23.H (same reference numbers, same thresholds; the injection identity is by-construction within both the ccx-lane-A and the MOOSE audit-UO; the |Δ| ≤ 1e-3 fallback tolerance applies only in parity/window-integral modes).

### 23.I Glossary (MOOSE additions)
- **AD/ADKernel** — automatic-differentiation kernel base; property/Jacobian bookkeeping automatic.
- **UserObject (restartable)** — stateful helper object that survives checkpoints; home of the toolpath schedule and audit state.
- **Executioner / TimeStepper** — MOOSE's solver-controller: time integrator + dt rules.
- **Exodus II (.exo/.e)** — the field-output format (double precision); what `.frd` is in the CalculiX plan, minus its precision ceiling.
- **`.cpr` / `Checkpoint` output / `--recover`** — the native restart machinery that replaces hand-built stage chaining as an option.
- **fa (activation factor)** — quiet-element 0→1 material state property, the *only* intersection of both alternative docs' deposition lanes.
- **SolutionUserObject** — reads a field from a previous run's output (the sequential thermal→mechanical handoff).

---

## 24. Backend decision analysis: what is actually right for this project

*(the requested comparison: MOOSE vs CalculiX vs FreeFEM vs Abaqus vs Ansys — plus "something else")*

### 24.1 The scoring axes this project really cares about
Grounded in what the framework is and what it must become: (1) physics fidelity for WAAM (moving source, activation/birth, latent heat, J2, restraint/release); (2) **auditability** — the framework's differentiator (by-construction energy ledger; no black-box numerics); (3) automation-parametrization fit (generated-input model, parameter registry, headless CI); (4) long-horizon extensibility (UQ, microstructure, parallel scale, coupled lanes); (5) toolchain/integration risk on THIS machine (macOS Apple Silicon TODAY); (6) validation continuity (the 340-check suite, the golden benchmark numbers); (7) cost/ecosystem.

### 24.2 Capability matrix

| Axis | FreeFEM (today) | CalculiX | **MOOSE** | Abaqus (commercial) | Ansys (commercial) |
|---|---|---|---|---|---|
| Moving Goldak source | Built (validated) | `dflux.f` (+ Fortran toolchain risk on macOS) or amplitude-deck lane | custom kernel, C++, compiled once | native + `DFLUX`/`UMDFLUX`/`UAMP` subroutines (mature) | AM module source models native |
| Element birth / activation | masks (validated, ledger-telescoping discipline shipped) | quiet elements / property-swap lane (no native birth) | activation material + UserObject (no native birth; full control) | `*MODEL CHANGE` ADD/REMOVE incl. STRAIN-FREE (**native**) | native in Additive Additive-suite |
| Latent heat | enthalpy form (exact) | cp-spike lane (gate) | shared cp-table lane (same math as Abaqus-standard) | native `*LATENT HEAT` | native |
| J2 plasticity quality | nodal Picard (P2 BETA) | native `*PLASTIC`, good | native radial-return, good, quadrature-point (upgrades the current model) | best-in-class documentation | native |
| True isostatic restraint | compromised (1e-9 spring) | spring/pénalty BCs build | **Contact/penalty native** (gate verifies) | contact native | contact native |
| Checkpoint/resume | custom (validated; guarded) | weak (variant lane) | **native**, restartable UOs incl. schedule/ledger | native (restart jobs; costly sim time) | native |
| Parallel solve | partial serial MUMPS (249k/6.7 GB ceiling) | SPOOLES serial-ish; PaSTiX build optional | **MPI + PETSc standard** (Debe-verified ladders) | native | native |
| Mesh adaptivity (h) | none | none | **markers native** (activation-coherence research gate M9) | solver-side ALE-ish (limited AM use) | limited for this use |
| UQ / DOE platform | sweeps via Python only | none | **Stochastic Tools module** (samplers, Bayesian calibration) | commercial add-ons | optiSlang-class extras, commercial |
| Microstructure/melt-pool depth | hooks (phase→hardness CSV only, Marangoni/OpenFOAM sidecar) | none | **PhaseField/INSFV modules** (real research route) | none general-purpose | none general-purpose |
| Auditability (& an energy ledger in your schema) | **best**: built, exact, printed | achievable (trace protocol lane) but extra plumbing | achievable, cleaner than ccx (restartable UO, no thread hazards, double-precision outputs) | achievable but against the tooling's grain (you audit what the deck does, not what it hides); Python scripting helps | same class as Abaqus |
| Headless/codegen fit | **ideal (that's the current architecture)** | good (text decks) | **ideal (same shape: codegen → `.i`)** | good (`.inp` decks; Python API adds real power) | Workbench scripting is GUI-first; headless possible but clunkier |
| Toolchain risk on your Mac today | none (validated) | **HIGH (Fortran+user-subs build, gate A1 could fail)** | **low-medium** (conda lane first, C++ source as fallback; no Fortran) | low (vendor install) but licensing | low (vendor) but licensing |
| Learning curve for you (C++/MOOSE reality) | zero (done) | low-medium (deck+Fortran) | **medium-high at first, lowest friction afterwards** | low-medium (docs excellent) | low-medium |
| License/cost | free (GPL-ish FreeFEM) | free (GPL) | **free (LGPL 2.1)** | tens of k$/yr (dassault terms) | tens of k$/yr |
| Validation continuity (suite/benchmarks) | keep as-is | keep (twin lanes) | keep (twin lanes); largest suite additions | restart from zero (or as a partner deliverable only) | same |
| WAAM/welding precedent in community | niche-but-published (your own validation) | solid discourse + OpenAM-SimCCX | **growing AM literature** (INL ecosystem, laser/PBF/EB papers) | the industry standard for welding sim | the parallel industry standard for AM distortion (Additive Print) |

### 24.3 My recommendation, by scenario (and what I'd actually pick for you)

- **If the goal is a defensible research platform + publishable open science + eventually UQ/calibration and microstructure depth** → **MOOSE**. It is the only lane that closes §1.9's F-class (parallel/memory ceiling), G-class (UQ), B-class (consistent operator option), and opens the PhaseField microstructure lane — with a toolchain risk *lower* than CalculiX's (no Fortran) and an integration shape *identical* to your existing architecture (codegen → generated input). The honest price: authoring 7–9 C++ classes (§9) and a learning curve the first month is steep. **This is what I'd pick as the primary strategic backend.**
- **If the goal is the fastest industry-interoperable deliverable (Abaqus-shaped decks, a collaborating lab using CAE-style tools)** → **CalculiX** lane only — its deck conventions are Abaqus's, and any later Abaqus partnership would re-use ~most of that work programmatically. Accept its Fortran gate, its no-birth quiet-element lane, and a weaker UQ story. **Build only if such a partner exists; otherwise it is a second backlog lane, not the primary.**
- **FreeFEM** stays: the validated reference, the audit-behavior oracle, and the only backend whose every numeric behavior (lumping pathology, telescoping discipline) is *characterized in this session's measurements*. Kill it and you lose your ground truth for cross-validation (§23.H tolerances are determined by comparisons like this).
- **Abaqus / Ansys**: the physics is *ready-made and excellent* — you would spend days, not weeks, on physics and instead spend them calibrating trust (audits harder to own, parametric plumbing through vendor APIs, licensing fireworks for sweeps/DOE at scale: sweeping N=200 cases against a commercial license dissolves savings fast). Choose only under a partnership/funding constraint that buys the licenses; then prefer **Abaqus** over Ansys if welding-fidelity docs and `DFLUX` maturity matter, or **Ansys Additive** if distortion-only screening (inherent-strain fast lane) is the deliverable.
- **"Something else", briefly**: **Elmer** (LGPL, multiphysics, mediocre AM-precedent, same Fortran class of toolchain risk as ccx — dominated by MOOSE for this purpose); **FEniCSx/dolfinx** (elegant weak-form Python, but you'd rebuild kernels/activation/adapter exactly and live with narrower solution scope — dominated by the MOOSE lane unless the team is Python-only); **Kratos** (C++/Python app framework, adaptivity, decent — a plausible second-choice behind MOOSE, weaker AM ecosystem); **Simufact Additive/Welding** (the commercial *specialist* product closest to WAAM idioms — worth a demo if an industrial partner funds it; not a port target, a tool someone else ships). **preCICE** is a coupler, not a candidate.

### 24.4 Sequencing advice (concrete)
1. Freeze today's FreeFEM as the reference (no physics edits without suite coverage).
2. Land the shared P1 infrastructure once (`thermal_curve.py`, extractor, sets contract) — it serves every lane.
3. Execute the MOOSE lane per §22 (P0 first; the gates decide, again).
4. The CalculiX `calculix.md` plan stays on the shelf as a partner-triggered lane — its MVP (12–18 d) estimate is only valid if *started fresh*, which is precisely why gating it on need matters.
5. Re-decide at the P8 ship gate with measured wall-times: if MOOSE doubles the FreeFEM walltime on the benchmark, the parallel lane exists precisely to amortize it — but record the number in `benchmarks.md` before believing anything.

---

## 25. Execution recap (the shortest honest path for the MOOSE lane)

1. P0: gates M1–M12 → decision record.
2. P1: shared infra (`thermal_curve.py`, Exodus exporter, sets contract, round-trips).
3. P2: `.i` builder + registry lint + window golden.
4. P3: the app (ToolpathUO → ActivationMaterial + telescoping test → GoldakKernel + audit UO) ⇒ **injected==intended by construction, again**.
5. P4: ledger close + G1–G7 on slabs.
6. P5–P6: runner + native checkpoint + mechanics parity (fixture release lesson carries; specimen case).
7. P7: postprocess/GUI polish + preset `.i`s.
8. P8: zero-touch battery G1–G10 + suite ≥ 380 + letter-Z MOOSE e2e exit 0 — **the ship gate**.
9. P9 (optional research): PhaseField microstructure; Stochastic Tools UQ/calibration; adaptivity coherence; coupled lane — each separately recorded, none MVP-gating.
10. Stay twin-open: ship the `sensors/` stanza + `measured_*` ledger reservations with the first MOOSE release (owner contract `calculix.md` §23.K), so the shadow→twin lane builds on a frozen backend without re-opening physics phases.
