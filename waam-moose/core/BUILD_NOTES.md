# BUILD_NOTES.md — WAAM-MOOSE app

## Install lane (decided 2026-10-19)

**Lane 2 (source), pre-built tree** — the MOOSE source tree already built on this machine is used
directly; no conda `moose-dev` environment involved.

| Item | Value |
|---|---|
| MOOSE tree | `/Users/pandeyji/projects/moose` |
| MOOSE git SHA | `8bc7d5b4` (2026-07-09, `Application Version: 8bc7d5b4`) |
| Modules linked into `waam_moose` | `heat_transfer` (+ `heat_conduction` app), `solid_mechanics` |
| App build | `cd waam_moose && make -j8` (links against prebuilt module libs in the tree) |
| Executable | `waam_moose/waam_moose-opt` |
| MPI | in-tree MPICH; binary runs without any environment activation |
| License | LGPL 2.1 (framework). No Fortran toolchain required for the app. |

## Build history

- 2026-10-19 — app skeleton (`WAAMApp`, `main.C`, Makefile) created and built; smoke test
  `smoke.i` (3D transient heat conduction, 4×4×4 generated mesh) exits 0 with converged solves.
  Gate **M1: PASS** (first evidence line in `PHASE0_REPORT.md`).

## Mesh I/O contract (verified 2026-10-19)

The `FileMeshGenerator` of this MOOSE build reads Exodus II only in **netCDF classic
(CDF-2)** format — HDF5/netCDF-4 files are rejected ("Attempting to open the netcdf-4 file").
gmsh-native `.msh` (4.1/2.2) files do not deliver sideset/nodeset names to MOOSE reliably.

Working lane (implemented in `mesh/medit_to_exodus.py`, deps: `meshio`, `netCDF4`):

```
WAAM medit .mesh (SI metres, refs 1=zmin, 5=zmax, 2..=flanks)
  -> medit_to_exodus.py
  -> Exodus II CDF-2, 1 tet block "domain",
     sidesets AND nodesets named "lbl_<ref>" for every medit ref
```

Verified facts:

- `DirichletBC boundary = lbl_1` works (NodalBCs need Exodus *nodesets* — the converter
  writes both `node_ns` and `elem_ss`/`side_ss` per ref).
- `AreaPostprocessor` on `lbl_1` / `lbl_5` matches analytic footprint area
  (letter-Z: substrate 2.25e-2 m², bead top 5.8e-4 m²; sweep case: 2.25e-2 m² both).
- Tet face mapping: libMesh sides `{0:(0,2,1), 1:(0,1,3), 2:(1,2,3), 3:(2,0,3)}`,
  Exodus side = `{0:4, 1:1, 2:2, 3:3}[libmesh_side]` (libMesh `tet_face_map` in
  `exodusII_io_helper.C`; consistent with Exodus tet side table).
- Exodus file structure mirrors a known-good MOOSE-suite file (attrs `api_version=8.03`,
  `len_name=256`, `eb_prop1/ss_prop1/ns_prop1` with `name='ID'`).

## Toolpath/activation contract (parity-locked 2026-10-19, verified)

Source of truth: `WAAM-Framework/codegen/edp_builder.py` (FreeFEM generated program) +
baseline run `waam_output/2026-10-17_17-46-55/` (`sim.log`, `FreeFEM/toolpath.txt`,
`FreeFEM/layer_pass_times.txt`, `FreeFEM/parameters.json`). Implemented in
`WAAMToolpathUO` + `WAAMTorchProbe`/`WAAMActiveFraction`/`WAAMActivationAux`.

Clock and arc gating:

- Row `j` has time `tpT[j]` and the pState of the move *ending* at `tpT[j]`.
  Layer `l` pass time `tPass_l` from `layer_pass_times.txt`; window `[j0, j1]` =
  rows with `|tpZ[j] - zc_l| <= 0.45*h_l` (error if unmatched or non-contiguous).
  `zc_0 = hz_base + h_l/2`, `zc_{l+1} = zc_l + h_l/2 + h_{l+1}/2`.
- `tLocal in [0, tPass_l]` maps 1:1 onto `[tpT[j0], tpT[j1]]` (window may include a
  trailing +t_wait row; `tLocal` never reaches it). Layer starts are cumulative
  `Sigma(tPass_k + dwell)`. Arc on iff `tLocal <= t_win + 1e-9` AND the bracketing
  row's pState == 1 (inWindow guard reproduces `pState=0` at pass end).
- Arc energy parity: FreeFEM integrates `Pweld*dt` with
  `dt_l = tPass_l / NweldSteps_l`, `NweldSteps_l = int(tPass_l/dt_weld + 0.5)`
  (NOT the raw `dt_weld` parameter). Baseline letter-Z: `NweldSteps` per layer
  `[62,59,57,60,57,57,57,59,57,57]`, `dt_l ~ 0.3319 s`, 56 arc-on steps/layer,
  `Earc = 714.514 kJ` exactly. Any consumer of injected energy must use this
  schedule (see `WAAMEnergyAuditUO`).
- Dwell steps in FreeFEM use a staircase dt: `0.5, 1, 2, 5, then 10 s`
  (`min(dtWait=10, remaining)`). The cooling tail after the last layer is a
  separate loop. MOOSE v1 runs a constant dt; exact dwell/cooling parity is a
  P4 item — encode the FreeFEM step times in a `TimeSequenceStepper` generated
  by the builder (every FreeFEM step time can be reproduced exactly).

Activation ledger (NODAL, cumulative — `_psi_data` in the UO):

- Two equivalent access paths:
  1. **Persisted ledger** (`psiNode`/`faCumulative`, restartable): updated in
     `execute()` (default `timestep_end`), kept as the restart truth.
  2. **Pure time query** (`psiAt`/`faAt`/`numActiveAt`): `ledger ∪ gate(t) ∪
     consolidation(t)` as a pure function of the schedule. This is what the
     kernel/material/aux consume; the aux kernel
     (`WAAMActivationAux`, `execute_on = 'initial timestep_begin'`) writes the
     nodal `psi` field at the **new** step time `t_n` (verified: a probe at
     `timestep_begin` reports `x(t_n)`, same as at `timestep_end`), so step n's
     own assembly sees its own gate — exactly FreeFEM's loop order
     (`tLocal += dt` → torch(t_n) → psi update → srcMask → assemble).
- Gate: node activates iff `t > layer_start + 1e-9` (strictly inside the pass:
  FreeFEM's first sample is at `tLocal = dt`, never 0, and dwells sample
  nothing), `(dx/af)^2 + (dy/bG)^2 <= 1`, `|z_node - z_torch| <= max(cG,
  0.85*h_l)`; ignores pState (rapids weld too).
- Substrate nodes `z <= hz_base + 1e-6` active from t=0.
- Consolidation: all nodes `z <= z_consol_l = max(zc_l + h_l/2, z_torch_end +
  h_l/2) + 1e-5` activate strictly **after** the layer pass end (`t >
  pass_end + 1e-9`) — the last weld step's own assembly does not see it,
  matching FreeFEM's post-loop placement.
- Ledger persists via `declareRestartableData<std::vector<char>>("psi_data")` and
  `"consolidated"`; `buildLedger()` must skip re-initialization when
  `_app.isRestarting() || _app.isRecovering()` (recovering a checkpoint clears
  `isRestarting()` — this bug cost one debugging cycle; recovered drill now matches
  the continuous run 801/801 rows on all columns).
- MOOSE execution order within a flag (`FEProblemBase::execute`):
  controls -> samplers -> PRE_AUX UOs -> aux systems -> POST_AUX UOs. Outputs
  (CSV/checkpoint) run after both. UO at `timestep_end` (ledger truth) + aux at
  `initial timestep_begin` (field at `t_n`) is the parity configuration;
  `WAAMActivationAux` writes nodal `psi` and elemental `fa` (majority of 4 tet
  nodes).

Element masks (for P3.3 material/kernel):

- `srcMask_e = (majority of nodes active)` -> `fa` aux (elemental).
- `bornMask_e = max(srcMask_e, 1e-5)` multiplies conduction `k`.
- Effective conductivity: `k_eff = k(T) * max(psi_qp, 1e-4) * max(srcMask_e, 1e-5)`
  (psi sampled at qp from the nodal aux); Cp and rho are never masked.
- FreeFEM additionally rescales the volumetric source each step so the quadrature
  integral equals `Pweld*dt_l` exactly (printed deviation −69.83% on the baseline);
  MOOSE v1 does NOT rescale — the audit measures raw fidelity (deferred, see P4).
  Quantified impact (letter-Z smoke, dt=1): mid-pass raw masked power ≈ 3460 W vs
  Pweld 3840 (−9.9%); first weld step ≈ 1600 W (mask truncation) — with FreeFEM's
  per-step rescale those steps are boosted to exactly 3840 W (factor ~2.4 early,
  ~1.11 mid-pass). P4 parity option A: replicate the rescale via a step-integral
  UO feeding a `source_scale`; option B: keep raw + carry the fidelity factor in
  the audit. Decision pending temperature comparison.

Heat source kernel (P3.2):

- `WAAMGoldakKernel` (ADKernelValue): residual contribution `-q(x_qp, t) * psi_qp
  * fa_e`; `q` from `WAAMToolpathUO::goldakQ` (pState-gated, tanh split along
  dirSign*(x−xT) by layer parity, eps = split_epsilon or fallback).
- `use_masks=false` gives the raw Goldak (diagnostics / audits).
- `WAAMSourcePower` (ElementIntegralPostprocessor): instantaneous `∫ q*psi*fa dV`
  [W]; `use_masks=false` for the raw integral.
- Cross-check: at t=400 (mid-pass, layer 5) an independent 4-point tet quadrature
  over the same mesh gives 3454.4 W vs MOOSE's 3460.7 W (0.18 %, quadrature-rule
  difference); zero during dwells/after the arc (pState gate).

Verification evidence (2026-10-19):

- 115/115 torch state rows and 70/70 FreeFEM-logged step positions reproduced by an
  independent Python re-implementation of the builder (max err 4.8e-5 mm = print
  rounding); Python energy model reproduces `714.514 kJ` bit-for-bit.
- UO smoke run (`/tmp/opencode/uo_smoke.i`, dt=1 s, 801 CSV rows):
  - ledger count vs Python replica trajectory: `800/800` identical;
  - pure time-query count vs Python replica: `800/800` identical;
  - ledger vs time-query columns: equal on all 801 rows (t=0 included);
  - `--recover` at t=400 with the final semantics: `801/801` rows identical on
    every column to the continuous run.
- Probe check: a `WAAMTorchProbe` at `timestep_begin` reports `x(t_n)` (new
  time), confirming the aux-at-`timestep_begin` parity design.

## Activation material (P3.3, parity-locked 2026-10-19, verified)

`WAAMActivationMaterial` — two-zone piecewise-linear tables, exact transcription of
the generated FreeFEM functions (`sim.log` lines 283–540):

- Zone switch per qp: `z_qp <= hz_base + 1e-6` → substrate (SS316L), else deposit
  (SS308L). `hz_base = 5e-3` for letter-Z.
- `k_eff = kMat(T,z) * max(psi_qp, 1e-4) * (T > TliqMat(z) ? kLiqF : 1) * max(fa_e, 1e-5)`
  with `kLiqF = 1.0` in the baseline (factor present but disabled);
  `TliqMat` = 1440 K substrate / 1457 K deposit.
- `cp = CpMat(T,z)` — latent spike as piecewise-linear nodes straight from the
  builder: substrate `1377→1438 K : 4683.783`, deposit `1404→1455 K : 5665.528`;
  **not** masked. `rho = 7900` substrate / `7850` deposit; not masked.
- All three properties are non-AD (`MaterialProperty`) and the smoke uses non-AD
  kernels: the generated FreeFEM program assembles a linear problem per step with
  `kEff`/`CpEff` frozen at the current temperature (Picard style), so a Jacobian
  without `dk/dT`,`dcp/dT` is the parity-faithful choice.
- P2 `moose_builder` must emit the table vectors from
  `core/multimaterial/material_database.json` (same data `edp_builder.py` uses).

Verification evidence (2026-10-19):

- `mat_check.i` (2 elements, one per zone, T = 1400 K, psi = fa = 1): computed
  (k, cp, rho) = substrate `(32.0, 4683.783, 7900.0)` / deposit
  `(32.485149, 649.801980, 7850.0)` — identical to an independent Python
  interpolation of the FreeFEM tables.
- Full letter-Z smoke with the material (dt = 1 s): 112 steps converged before the
  manual cutoff, plausible trajectory. **Noted:** the latent spike makes Newton
  stiff at dt = 1 s (~29 NL iterations/step); the v1 builder uses the FreeFEM
  per-layer arc dt (~0.33 s), evaluated in P4. If needed, P4 adds
  `IterationAdaptiveDT` or the enthalpy method.

Open boundary piece for P4 (constants already extracted from `sim.log`):
Robin = `hConv 15 + hRad` on flanks/top (`hRad = 0.7*5.67e-8*(T^2+Tamb^2)*(T+Tamb)`),
`hBot 50` on `lbl_1` (bottom), all ψ-weighted — matching FreeFEM faces
`int2d(Th,1)(hBot*psiActive*(Tamb-T))`, `int2d(Th,2..6)(hSurf*psiActive*(Tamb-T))`.

## Energy audit (P3.4, verified 2026-10-19)

`WAAMEnergyAuditUO` + `WAAMEnergyAuditPP` (quantities: `intended_energy`,
`injected_energy`, `injected_energy_raw`, `intended_power`, `fidelity`).

- Intended counter reproduces FreeFEM `EintJ += Pweld * pState * dt` (sim.log line
  1213): at each step ending at `t_n`, a welding torch state adds `Pweld * dt`
  with `Pweld = 3840` (effective power; input `P_weld=4800`, `eta=0.8`).
- Injected counters use the same right-endpoint rule as the per-step assembly:
  `E += P(t_n) * dt` with the masked (`src_power`) and raw (`src_power_raw`)
  `WAAMSourcePower` values.
- **Trap (cost one cycle):** GeneralUserObjects get `initialize()` called before
  *every* `execute()` at each flag (`FEProblemBase::computeUserObjects`,
  ~line 5237), so zeroing counters in `initialize()` resets them every step.
  Cumulative state lives only in `declareRestartableData<Real>` (initial 0,
  restored on `--recover`); `initialize()` is a documented no-op.
- Evidence (fast-config `uo_audit.i`, dt=1 s, 801 rows):
  - `e_intended = 721920 J` = 188 welding steps × 3840 W × 1 s, bit-equal to an
    independent Python sum of the CSV `torch_pstate` column;
  - `e_injected = 416462.77463982 J`, `e_injected_raw = 529561.09800548 J` —
    bit-equal to Python Σ `src_power(·)*dt` over the same rows;
  - `--recover` at t=400 (checkpoint chunk + continuation): `801/801` rows
    identical on every column to the continuous run.
- With a `TimeSequenceStepper` carrying the FreeFEM step times (P4) the intended
  counter reproduces the baseline `Earc = 714.514 kJ` exactly (dt=1 s gives
  721.92 kJ because the step boundaries differ). Fidelity aggregates over a
  different dt schedule are not comparable to FreeFEM's per-step rescale factors;
  compare per-step in P4.

## DECK generation (P2, 2026-10-19)

`WAAM-Framework/codegen/moose_builder.py` — the `.i` twin of `edp_builder.py`.
It consumes a FreeFEM run dir (`FreeFEM/parameters.json`, `toolpath.txt`,
`layer_pass_times.txt`, medit mesh) and reuses `edp_builder` as the single
source of truth for validation/defaults (`EDPBuilder(params)` instantiation),
Goldak auto-sizing, the latent cp smoothing (`smooth_cp_spike`) and
`eps_split = max(0.1*min(af,ar), 0.25*lx/nx_dep)`; k/cp tables are typed from
`material_database.json` (smoothed cp matches the generated program exactly:
1376.99/1438.01 : 4683.783 base; 1403.99/1455.01 : 5665.528 deposit).
Auto-size replication verified: `P_eff = I*U*eta = 3840 W`, `eps_split = 1.5e-3`,
`bG/cG/af/ar` identical to the smoke configuration.

Emissions per run: `<run>/moose/{waam_moose.i, waam_moose.i.meta, mesh.exo}`
(`.meta` hashes parameters/toolpath/mesh/input; `mesh.exo` via
`WAAM-MOOSE/mesh/medit_to_exodus.py`, found through `WAAM_MOOSE_HOME`, default
the sibling of the framework checkout).

Time schedule (freefem_step_times): per layer
`N = max(int(tPass/dt_weld+0.5),1)`, `dt = tPass/N` (N = {62,59,57,59,57,57,57,
58,57,57}, 580 weld steps), dwell staircase 0.5/1/2/5 then min(dt_wait, rem)
(10 steps/layer), final cooling 1/2/5/10/30/60 then min(dt_cool, rem)
(26 steps). `TimeSequenceStepper` block: parameter name is **`time_sequence`**
(not `time_steps`). Output interval parameter is **`time_step_interval`**
(`interval` etc. are rejected). **`.i` comments are `#`** — `//` lines are a
syntax error at parse time (cost a cycle).

GOLD-LOCK verification (2026-10-19):
- generated schedule: 706 steps, end `3192.723323 s` (= FreeFEM weld end
  792.723 + 2400 cooling; the last dwell lands exactly on 792.723 like the
  program);
- full-schedule drill (fast-config conduction) `seq_drill.i`: exit 0, 707 data
  rows;
- per-step audit: `e_intended = 714514.05792 J` — the FreeFEM baseline
  `Intended arc input (Pweld*dt): 714.514 kJ` reproduced EXACTLY (matches an
  independent Python replica of the UO's torchStateAt gain mapping, 56 arc-on
  steps per layer).

torchStateAt boundary correction (part of the same gold-lock): FreeFEM's first
weld sample is at `tLocal = dt > 0` and dwell steps carry `Tsource = 0`, so an
exact pass-start instant is silent. The dwell's final step lands exactly on the
next `layer_start` (`t_local == 0`) and previously reported the upcoming layer's
row pState as arc-on (paid `Pweld * dt` once per layer): `p_state` now requires
`t_local > 1e-9`, matching the gate's rule. Effect on the dt=1 s smoke: none
(no exact-boundary steps on that grid); effect on the true schedule: closes
714.514 kJ exactly.

## Negative-temperature root cause + FreeFEM clip parity (2026-10-21)

Symptom: production letter-Z run trips `DIVERGED_LINE_SEARCH` from step ~15
(t ~4.98 s) into a dt = 1e-12 retry spiral; separately `tmin` goes negative
(-87 C on step 1, -826 C by t ~8 s).

Root causes, in order of impact:
1. **`Outputs/show` filters VARIABLES, not just postprocessors.** A PP-only
   `show` list made `vals_nod_var1` never be written, so per-step Exodus frames
   collapsed to one. Fix: `show = 'T psi fa <pp list> ...'`.
2. **`TimeSequenceStepperBase::computeFailedDT`** halves the sequence gap on
   each failed step and `mooseError`s once the gap <= `dtmin` (default 1e-12),
   producing the retry storm. Fix: `dtmin = 1e-4` (all physical FreeFEM gaps
   are >= 0.33 s so this never inflates a real step), `error_on_dtmin = false`
   for a clean "timestep already at or below dtmin" stop.
3. **`bt` line search** gives up with `DIVERGED_LINE_SEARCH` at ~4e-9 residual
   (already below tolerance) in the torch-off cooling tail. Fix: `l2`.
   `nl_abs_tol` relaxed 1e-9 -> 1e-6 (1e-9 is unphysical for a 25..2862 C field).
4. **Boiling gate discontinuity.** The old Goldak kernel zeroed the source
   inside the kernel where `T >= Tboil` -- a T-discontinuous residual that flips
   between q and 0 across neighbouring Newton iterations as the pool rides the
   2862 C plane. Replaced with `WAAMBoilingCapKernel`, a C1 smoothstep sink
   `Q = rho*cp*rate*r(T)*(T - Tboil)` that pins the pool and exports the removed
   power; audited by `WAAMCapPower` (P4 term `boiling_cap_removed`, matches
   FreeFEM `EcapJ`). `t_amb` was removed from the kernel (the lower clip is
   handled by the bounds below). `WAAMGoldakKernel`'s dead `t_boil` param removed.
5. **P1 moving-source undershoot (the real negative-T cause).** FreeFEM keeps a
   **consistent** Galerkin mass matrix (same as MOOSE) but CLIPS the nodal field
   after every solve:
   `Temp = max(Temp, Tamb); if (psiActive<0.5) Temp = Tamb;
    if (Temp >= Tboil) Temp = Tboil;`.
   MOOSE has no post-solve assignment, and the under-resolved ~4e10 W/m^3 Goldak
   spike on ~9.5 mm tets smears arc energy onto cold neighbours -> tmin < 0.

### Mechanism choice: Bounds + vinewtonrsls (NOT a Corrector)

A `WAAMFreeFEMClip` Corrector was implemented and provably clips
(`tmin_in=-87 -> tmin_out=25`), BUT `FEProblemBase::computeUserObjectsInternal`
runs element user objects (all postprocessors) BEFORE general user objects, so
`tmin`/`tmax` sample the raw field (CSV still showed -267 C). Hard ordering
constraint, not a clip bug.

Chosen mechanism: **`WAAMFreeFEMBounds`** (`BoundsBase` AuxKernel) + PETSc
`-snes_type vinewtonrsls`. Bounds are applied INSIDE the SNES solve each Newton
step, so every PP / output / next-step residual sees the bounded field with no
ordering games:
- active node (psi >= 0.5): upper bound = Tboil, lower bound = Tamb;
- quiet node (psi < 0.5): both bounds = Tamb (node pinned at ambient);
- upper object returns Tamb on quiet nodes, Tboil on active; lower object
  returns Tamb always. `getBound()` reads psi per node via `coupledValue`.
- Needs a scratch aux var `bounds_dummy` (LAGRANGE/order 1) to match T's feType.

Builder emissions (`codegen/moose_builder.py`):
- `[Bounds][t_upper][t_lower]` (guarded by `enable_freefem_bounds`, default on);
- `bounds_dummy` aux var;
- Executioner `petsc_options_iname = '-snes_type -snes_max_it
  -snes_linesearch_type'`, `values = 'vinewtonrsls 120 l2'`;
- `[cap]` (no `t_amb`) + `[cap_power]` PP; show list includes `cap_power`,
  `num_failed_steps`.

Validation (letter-Z, 20 s drill `b20.i`): tmin = 25.0 C exactly for ALL steps,
tmax 1593 -> 2281 C approaching the 2862 plateau at t ~ 7.96 s (the FreeFEM
"Tpeak >= 2860" zone). No undershoot. Remaining cost: steps at the 2862 C
plateau (t ~ 7.30, 7.96 s) hit `snes_max_it = 120` and cut back before
recovering -- a plateau/active-set robustness issue, NOT physics error. Average
~3 s/step away from the plateau, ~20 s/step on it.

Dead code kept for reference: `WAAMLumpedHeatTimeDerivative` (mass lumping fix,
abandoned: diverges from FreeFEM's discretization and ~10x slower),
`WAAMFreeFEMClip` (Corrector, abandoned due to the UO ordering constraint).

## Live residual monitor (pyFoam-style) — 2026-10-21

`codegen/waam_live.py` monitors a MOOSE transient solve in flight, the way
pyFoam does for OpenFOAM:

    # launch a solve and watch it
    python3 codegen/waam_live.py --case <run_dir>
    # or attach to a log
    python3 codegen/waam_live.py --log run/moose/waam_moose.log
    # force the terminal view (headless/SSH)
    python3 codegen/waam_live.py --log run.log --ascii
    # dump the parsed history
    python3 codegen/waam_live.py --log run.log --json history.json

Two renderers:
- **ASCII** (default when there is no display): a Fluent-like table refreshed
  in place — step, time, dt, nonlinear iterations, final |R|, a log-scaled
  residual sparkline, the divergence/cutback counters and the live thermal
  envelope (tmin/tmax/failed steps).
- **matplotlib** dashboard: residual history per time step (pyFoam style, the
  last 12 steps highlighted), the worst residual per step with the divergent
  steps marked, and the tmin/tmax envelope against time. Saves
  `<log>_live.png` at the end.

It parses the MOOSE console stream (`Time Step N, time = T, dt = D`,
`n Nonlinear |R| = X`, `n Linear |R| = X`, `Damping factor: X`,
`did not converge due to ...`) and reads the run CSV for the thermal
envelope.

Gotchas found while building it:
- The child must be read through a **pipe**; sharing one file descriptor
  between the reader and the child corrupts the log (both advance the same
  offset) and a file-backed stdout is block-buffered, so the residual stream
  would arrive in 4 KB lumps.
- The CSV is **not** found automatically unless it is named `<log>_out.csv`
  (MOOSE names it after the input file, `waam_moose_out.csv`).
- A log that was killed mid-solve has no "Finished Executing"; the tool then
  attaches to the tail and waits, so it also needs `--idle-timeout` to give
  up on a dead run.

The builder now emits a `[console]` output with
`execute_on = 'nonlinear linear timestep_end'` so the residual stream is
always in the log.

## CALPHAD integration — 2026-10-21

`codegen/calphad.py` computes the solidification path each alloy needs:
solidus, liquidus, latent heat, the WRC-1992 ferrite number and the
**phase fractions vs temperature**.

Backends (selected automatically, always recorded in the emitted artifact):
- `pycalphad` — real CALPHAD (equilibrium against a TDB). Needs the
  `pycalphad` package AND a thermodynamic database (`--tdb` or
  `WAAM_CALPHAD_TDB`). NOT installed in this environment, so it stays dormant.
- `scheil` — built-in fallback, always available: a Scheil solidification
  path `f_s(theta) = 1 - (1-theta)^(1/(1-k))` with
  `theta = (T_liq - T)/(T_liq - T_sol)` on the database mushy range and an
  effective partition coefficient driven by the WRC-1992 Cr_eq/Ni_eq ratio.
  The fully-solid phase mix comes from the framework's own family schemes
  (ALLOY_SCHEMES) and, for the austenitic stainless steels, from the
  WRC-1992 ferrite number (SS308L FN 8.04 > SS316L FN 5.49).

The fallback is a MODEL, not a thermodynamic database: it reproduces the
mushy range and the retained-phase split with the right trends, but it is not
a substitute for a real CALPHAD assessment. The backend used is always
stated in `calphad.json`.

Integration:
- `codegen/moose_builder.py` emits the phase-fraction tables into the `.i`
  and writes `<run>/moose/calphad.json` (the full model, the real phase names
  behind each thermal slot, and the backend).
- `WAAMActivationMaterial` gained the CALPHAD tables and publishes the
  material properties `phase_fraction_liquid`, `phase_fraction_primary` and
  `phase_fraction_secondary` (interpolated against the local temperature).
- `WAAMMeltPoolPhase` (a **nodal** postprocessor) reports `max_liquid`,
  `molten_fraction` and `mean_liquid` for the audit.

MOOSE parameters are static, so the phase fractions are exposed as three
fixed thermal slots (liquid / first-forming solid / remaining solid); the
real phase names (delta-ferrite as primary, austenite as secondary in FA
mode) travel in `calphad.json`.

### MOOSE gotcha: element user objects see the PRE-solve variable values

At `EXEC_TIMESTEP_END` the element-level user objects (element
postprocessors, aux kernels) see the **pre-solve** values of a nonlinear
variable: the variable cache is only refreshed by the output step, which runs
AFTER the user-object batch. Measured on the letter-Z drill: an
`ElementIntegralVariablePostprocessor` on T returned the initial-condition
integral while `NodalExtremeValue` (a NODAL user object) returned the solved
1951 C maximum. The raw solution vector is always current.

Consequences:
- The melt-pool statistics are implemented as a **nodal** postprocessor: the
  nodal batch recomputes the nodal values from the live solution vector.
  Verified: `max_liquid` = 1 exactly when Tmax crosses the 1457 C liquidus,
  `molten_fraction` = 2.5e-4 .. 1.2e-3 of the domain, growing with the pool.
- The phase fractions are **not** exported as an auxiliary field: an aux
  kernel would carry the initial condition, and the auxiliary system keeps a
  copy of T that is only synchronised at the output step. The fractions stay
  available as material properties (correct during the solve, which is where
  they matter physically) and through the audit postprocessors.
