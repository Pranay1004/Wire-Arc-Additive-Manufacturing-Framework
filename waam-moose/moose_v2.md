# `moose_v2.md` — Zone Ledger: the MOOSE-based framework, flexibly (v2 architecture plan)


NOTE : 

* Write ROBUST and EXTENSIVE COMMENTS in all FILES CREATED

* CREATE VERSIONING AND UPDATES based tracking too.
  READ MOOSE DOCS extensively

**Status:** planning draft (this document drives implementation; phase exit criteria are binding).
**Version doctrine:** `moose.md` = v1 — the *parameters-compatible port* of the current rigid pipeline (M-gates, P0–P9). This document = **v2 — the flexibility architecture**: the layer that turns the ported pipeline back into something that behaves like the commercial suites you use (region-of-interest meshing, optional baseplate, N clamps anywhere, several torches, mixed elements) while keeping everything this program has already made binding: the nine-term energy ledger, the physics suite, the twin hooks (`calculix.md` §23.K), and the loop-closed artifact contracts. v2 replaces NO v1 contract — it extends all of them with a zone dimension and deprecates exactly one assumption instead: *“one torch, one fixture label, one mesh.”*

**Prerequisites:** P0–P6 of `moose.md` (especially the `codegen/moose_builder.py` rail and `core/moose/` tree). F0–F2 of this doc may begin in parallel with v1 work (pure data model + scripts); every F-phase after that consumes the v1 builder's stage/window rail.

---

## 0. What “robust requirements” means here (validated framing)

| Flexible things (as observed in the commercial suites)                                        | Our framework — v1                                                                  | v2 (this doc)                                                                                                    |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| Region-of-interest meshing — hex sweep here, tets there, quads on shells, one part at a time | one builder, one mesh (tet uniform) or full-plate hex                                | **per-zone mesh plan** (element type, algorithm, size per named region)                                    |
| Optional baseplate; optional everything — absence is data, not a code branch                 | hardcoded flag `max(0, ...)` in builder code                                       | zone instances that a scenario simply omits                                                                      |
| Clamps: 1 corner / 4 corners / arbitrary spots                                                | implicit fixture tied to a fixed boundary label ('label 1' springs)                  | **N clamp objects**, arbitrary placement, → named sidesets                                                |
| Multiple torches, coaxial, tandem, dual-torch                                                 | one torch position wired into `edp_builder`; `heat_sources/*.edp` = 6 primitives | torch rosters as objects that path-follow the toolpath; tandam/coax as**compositions** of those primitives |
| Mixed elements in one solve                                                                   | FreeFEM: blocked, one mesh type per domain (measured dead end)                       | measured working: mixed blocks per zone reach MOOSE from one `.msh`                                            |
| Model tree feel; undo/redo; "playing with the tool"                                           | one-shot regenerate-everything pipeline                                              | staged solve DAG + editor that edits*files* (never has secret state)                                           |
| Professional restraint (ParaView's window)                                                    | tk dashboard, 147 hex colors                                                         | the**ParaView criterion** (lint-gated)                                                                     |

## 1. Requirements ledger (R1–R16)

| ID  | Requirement                                                                                                                                                                               | Commercial wormhole it closes                      | Acceptance gate |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | --------------- |
| R1  | Mixed element types across named zones in one solve                                                                                                                                       | Ansys/Abaqus part-mesh mixdo                       | Z3              |
| R2  | Per-zone mesh plan (type/algo/size) editable without global rebuild                                                                                                                       | Mesh options per part                              | Z3              |
| R3  | Baseplate optional — as scenario data, absent-as-policy                                                                                                                                  | "there may not be one"                             | Z6              |
| R4  | N fixtures, arbitrary placement geometry, rigid or spring, by named mask                                                                                                                  | "one corner, all 4, random"                        | Z5              |
| R5  | Torch roster: single goldak/gaussian/…, dual, tandem (**merge_pool**), coax ring, driver/follower                                                                                  | multiple heat sources & arrays                     | Z2              |
| R6  | Generated `.i` references **zone names** — zero baked geometry in physics keywords                                                                                               | parametric decks at scale                          | Z4              |
| R7  | Parametric parts (box/extrude/cylinder) via gmsh OCC + STL import fallback                                                                                                                | geometry flexibility                               | Z1              |
| R8  | Staged solve DAG with resumable checkpoints                                                                                                                                               | interactive back-tracking                          | Z7              |
| R9  | **File parity rule**: every GUI-editable thing is a file; GUI edits — and only edits — those files                                                                                | headless reproducibility                           | Z8              |
| R10 | **ParaView criterion**: no theming slop (lint-enforced, see §10)                                                                                                                   | visual restraint                                   | Z9              |
| R11 | Energy audit stays deterministic-solver-time; new columns per torch; zone-split telemetry                                                                                                 | measured-vs-modeled accounting                     | Z12             |
| R12 | Suite grows: ≥ 70 substantive zone-domain sections on top of v1's ≥ 380                                                                                                                 | —                                                 | Z12             |
| R13 | Twin hooks retained per `calculix.md` §23.K (sensor stanza, `measured_*` columns)                                                                                                    | shadow→twin lane                                  | Z12             |
| R14 | Legacy scenarios (DEFAULT, uva_waam SS308L/SS316L) load into the zone ledger without edits                                                                                                | back-compat                                        | Z11             |
| R15 | Mixed-mesh acceptance without a FreeFEM oracle on hex data — pre-registered constructed checks                                                                                           | validation honesty                                 | Z3 + §7 Lint   |
| R16 | Performance budget: thermal run ≤ 1.4× v1 per-layer wall time (mixed meshes give some rebate)                                                                                           | daily usage                                        | Z10             |
| R17 | Run-profile manager: per-geometry serial-vs-parallel decision + core count, decided by MEASURED scaling probes (1/2/4/8/… ranks, early-stop at the knee) — never assumed                | throughput on every unique geometry                | Z13             |
| R18 | Serial replay is the deterministic backbone (suite/gates/golden runs serial); parallel runs accepted only within preset tolerance bands (incl. audit Δinjected/injected ≤ 0.2 %)        | reproducibility trust                              | Z14             |
| R19 | Meshing kernel is per-zone swappable (`kernel:` in mesh_plan): gmsh today, alternatives later — one contract (named blocks/sidesets, conformal interfaces)                             | no vendor lock on meshing                          | Z15             |
| R20 | Native prismatic mesh lane: layer-cake generator built INSIDE the MOOSE app (per-layer blocks DEPOSIT_L1…LN from the existing slicing output), no external mesher for the canonical path | true native mesher where geometry is honest prisms | Z16             |

## 2. Measured ground truth (fresh probes, 2026-10-19)

| Probe                                                                                                                                                                                                            | Result                                                                                                       | Consequence                                                                                                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `~/projects/moose` git `8bc7d5b4` (2026-07-09): `combined-opt --version` and smoketag transient solve                                                                                                      | exit 0, no env activation needed (absolute dylibs in tree)                                                   | v1 M1 gate pre-satisfied; every v2 run uses this binary path                                                                                                                     |
| Modules present in combined app:`heat_transfer`, `solid_mechanics`+`tensor_mechanics`, `phase_field`, `stochastic_tools`, `contact`, `navier_stokes`, `xfem`                                     | confirmed via module_loader dylib name string                                                                | v2 needs no ray-trace; torch UOs put wait: zone-roster plugging in v1's*already-designed* UOs                                                                                  |
| `gmsh` 4.15.2 python: `gmsh.write('…exo')`                                                                                                                                                                  | **FAIL `Unknown output file format`**                                                                | no native .exo writer ⇒ export path C (below), not A                                                                                                                            |
| `gmsh.write('…inp')` with `addPhysicalGroup(..., name=...)`                                                                                                                                                 | **OK** (named elsets!)                                                                                 | geometry/mesh names survive to file                                                                                                                                              |
| `gmsh` mixin: recombine(2D) + `occ.extrude` on box                                                                                                                                                           | hex-dominant recombination present (mixed element-type ids in one .msh)                                      | mixed export realistic, with pyramid transitions                                                                                                                                 |
| 2-volume scene (BASE box + WALL box) with physical names →`mixed.msh` → MOOSE `FileMeshGenerator`                                                                                                          | **mesh loads, blocks named**; error only on undeclared boundary (`left`) — i.e. blocks parsed, good | export path C = primary: gmsh `.msh` (v4.1) read directly by libMesh GmshIO — v2 needs NO exo writer at all; sidesets just need explicit `addPhysicalGroup(2, …, name=…)` |
| `meshio` absent                                                                                                                                                                                                | utility lane only (pip-installable), never default                                                           |                                                                                                                                                                                  |
| MPI-initialized MPICH present and working (the earlier probe process was run without activating any environment;`combined-opt` initialized MPI cleanly); final core-count scaling is measured only in gate Z13 | v2 assumes mpich is capable as the MPI base                                                                  |                                                                                                                                                                                  |

## 3. Architecture — the model tree

```
scenario/                       (a scenario = a directory of ledgers)
  parts.yaml        parametric geometry features (box/extrude/cylinder/…) OR `stl:` source
  zones.yaml        named regions + OCC membership + face masks
  assignments.yaml  torches / fixtures / material / initial T per zone
  mesh_plan.yaml    per-zone element type, algorithm, sizes, layer options
  solve_plan.yaml   stage DAG, checkpoints, solver options, gate refs
  toolpath.txt      same dialect as v1, + optional per-torch columns (dialect v2)
        │
        ▼  (build kernel, pure data-model, no physics)
  geometry_kernel.py  → gmsh OCC: boolean fuse/cut producing NAMED volumes = zones (STL fallback = v1 slicer tet path)
  mesh_kernel.py      → per-zone generation + conformal assembly  → wall.msh (v4.1, named blocks/sidesets)
  zone_builder.py     → wall.i  (blocks, sidesets, UOs, TORCHES from assignments.yaml)
        │
        ▼  (runner, resumable)
  DAG: G0 mesh → G1 thermal window 1 → G2 coupling → G3 mech … (each node picks up or checkpoints)
        │
        ▼  (postprocess — unchanged contract)
  solver_results.json (+ zone_meta) · plots · report.html · case dir (incl. twin hooks)
```

Architectural doctrine: **"Rigidly bound the engine, get N³ combos free."** — the five ledgers bound each dimension (exact schema, exact vocabulary); combinations across them are unlimited. Every torch-like code branch in v1's builder becomes a ledger row; that is the whole point.

**File parity rule (R9):** the GUI never owns state. It reads ledgers, writes ledgers, launches `run_v2.py --scenario <dir>`. Headless = GUI-minus-rendering. This is how commercial tools actually work under their shells, and it keeps the twin hooks, parametric sweeps and CI identical whether or not the GUI was ever opened.

## 4. Zone ledger spec (data model)

### zones.yaml — annotated draft (Appendix A holds a full-example)

```yaml
schema: waam_zone_ledger/1
parts:
  - id: baseplate        # OPTIONAL: absence of the part = absence of the case; no builder branch
    kind: box
    params: {L: 60, W: 60, H: 6}
    zones: [base]
  - id: wall
    kind: extrusion      # from toolpath layer schedule; per-layer z-handoff grows this part or zone
    params: {stack: toolpath:nlayers}
    zones: [deposit]
zones:
  - id: base            # plural zones allowed (choose by instance, but ids are stable - hashed from id+parent)
    kinds: [volume]
    faces:
      bot: {kind: face, by: tag-or-param, name: BASE_BOT}    # sideset names below go to .i
  - id: deposit
    kinds: [volume, layered_material]
    faces:
      bot_layers: {kind: layers, z: auto}                    # layer wires needed per-slot from toolpath
fixtures:                    # R4: N entries, arbitrary placement as geometry
  - id: clamp_nw
    mask: {kind: cylinder, at: [15,15], r: 6, spanning: z}
    behavior: rigid
  - id: clamp_ne
    mask: {kind: box, at: [50, 4], size: [6, 6, z]}          # arbitrary location
    behavior: spring {kx: 1.0e6, ky: 1.0e6, kz: 1.0e5}       # replaces "label 1" springs
  - id: clamp_botplate                                        # thermal-only clamp if wanted
    mask: {kind: face, name: BASE_BOT}
    behavior: thermal
torches:                     # R5: N torches; each follows a toolpath row-set or its own path
  - id: torch_main
    kind: goldak
    path_ref: toolpath/1
    params: {b_band: 3.0, c_band: 2.0, R_activate: etc}      # same v1 parameter vocabulary
  - id: torch_tandem_b
    kind: goldak
    path_ref: toolpath/1
    offset: {along_tangent: +3.0}
    composition: {merge_pool_with: torch_main}               # tandem = overlapping sources share the pool; ledger gets both
  - id: torch_coax_ring                                       # coax deposit: ring-shaped volumetric source
    kind: gaussian_volumetric
    shape: {ring: {r_inner: 1.0, r_outer: 3.4}}
    path_ref: toolpath/1
mesh_plan:
  base:     {element: hex,   algo: transfinite_prism, size: 0.8, kernel: layercake}   # omitted kernel = gmsh
  deposit:  {element: tet,   algo: hxt,               size: 0.8, layers: {kind: boundary, n: 2}, kernel: gmsh}   # R1: zone-by-zone progress
solve_plan:
  stages: [thermal, mech]
  checkpoint: {policy: window, dir: checkpoints, there_references_to: moose.md §11.2}
lints:
  - zone_rule: physics keywords may only reference zone/sideset NAMES — never raw tags or tags' coordinates   # R6
  - torch_solos: each torch needs ≥ 1 energy-pickup source; merge_pool sums under ONE pool-bookkeeping item etc.
```

Identity and absence rules:

- Same ids stable across regenerations: zone identity hash included in `.i` and case manifest (digest like `zone:base#IN hash`); renamed = deprecated, not auto-corrected (v1 DB-style renames are scary).
- Absence of a part/zone = nothing in `.i` for it; no builder branch.
- zones are volume-RAW; faces/sidesets are cast by declarative rules (tag ranges, param regions, planar cuts) — plausible mappings checked by `zone_builder` (faces must exist on at least 1 element — GZ dry-run).

## 5. Torch roster (R5) — composition rules

| Kind              | Meaning                                                           | Composition of v1 primitive               | Ledger bookkeeping                            |
| ----------------- | ----------------------------------------------------------------- | ----------------------------------------- | --------------------------------------------- |
| single            | 1 stand-alone heat source                                         | one `goldak`/`gaussian_volumetric`/… | `injected` columns                          |
| dual              | two torches, side-by-side, separate paths                         | two sources, distinct paths               | 2 columns + total                             |
| tandem            | two torches on ONE shared path, pool shared (`merge_pool_with`) | two sources, same path, tangent offset    | 1 pool: sum under one item + both sub-columns |
| coax ring         | annular ring heating                                              | 1 source with ring shape                  | 1 column                                      |
| driver / follower | one torch heats ahead, second follows with lag toolpoints         | two sources, lagged paths                 | 2 columns, no merge (no plan cross-pool)      |

Composition merges never bypass the audit: v1's UO (`WAAMEnergyAuditUserObject`) gains per-torch columns — the **total** ledger keeps the same nine terms (compat), zone columns extend the *injected* axis. Dry-run test (suite D10) re-derives: `Σ torch columns = injected_arc`.

## 6. Fixture roster (R4)

- Placement specifier kinds: `{kind: box|cylinder|sphere|face, at/named}` → produces boundary masks in `zones.yaml` readable by `zone_builder`.
- Behaviors:
  - `rigid` — Dirichlet on named sideset (v2 feeds `solid_mechanics` BCs; no more implicit label-1 hops).
  - `spring` — Robin on named sideset; stiffnesses editable per dof (replaces the current single-label era that measured the wrong-direction fixture bug).
  - `thermal` — side effect only, e.g. `thermal clamp` = `TEMPERATURE` BC or a cooled Robin on named sideset.
  - optional `contact` lane (MOOSE contacts exist) for rigid-frame clamping — kept optional; springs remain the default for stability.
- N fixtures always allowed; fixture count is unrestricted data, never a builder case.

## 7. Mesh plan and mixed meshes (R1, R2, R15)

### gmsh capability table (working truth from v1 mesher + today's probes)

| Method                                       | Quality                                                    | Where applicable                      |
| -------------------------------------------- | ---------------------------------------------------------- | ------------------------------------- |
| `hxt`/Delaunay tets                        | best default (this session's verified ladder)              | default for all natural/rounded zones |
| transfinite extrude + recombine → prism/hex | measured working on nav boxes (prism-class)                | baseplates, prismatic pads            |
| hex8 pure                                    | works ONLY for strictly box-like volumes (transfinite)     | rare; keep goal — not default        |
| quads on cap surfaces                        | fine (2D recombine)                                        | deposit's smooth caps,                |
| hex-dominant volume recombine                | present but contains pyramid transitions, less predictable | never by default; opt-in + warning    |

- **Conformal assembly**: shared OCC faces between neighboring zone volumes MUST be single faces shared by both volumes (boolean cut/fuse relations), so conformal block interface is shared nodes in one `.msh`. Non-conformal = reject at mesh_kernel time (explicitly: no transfer-based multiapp substitute for physics continuity at the degree boundary).
- Export: **path C measured primary** — gmsh `.msh` (v4.1 binary L for size) → `FileMeshGenerator` direct; requires **boundary sideset naming via `addPhysicalGroup(2, …, name=…)`** (validated at Z4). Fallback B (pip `meshio`, exo writes for other consumers) declared, never default.
- Zone block naming contract: every volume/surface zone gets its OCC physical name = the zone id (matching `[BasePlate]`, `[-1,  'DEPOSIT_3']` style layer properties for walls).

### R15 — Mixed-mesh validation without a FreeFEM oracle

FreeFEM reference stays the gold oracle **on the tet-path and on thermal/mech values** it can represent (v1 pipeline). For mixed meshes the oracle does not exist, so we pre-register constructed checks instead (patch field, symmetric clamp, Dirichlet analytic limits, single-torch energy lint per torch on mixed as on tet, mesh-independence at 3 size ratios). Acceptance numbers are set in Appendix D on tet-agnostic refs first (box sinking checks), so the exact numeric thresholds exist before the first mixed run. No mixed result ships unless its built-ins vs an equivalent tet rebuild agree within those tolerances (Z3).

## 8. `.i` generation and solver-side consumption (R6)

- `codegen/zone_builder.py` — same rail as v1 `moose_builder.py` (windows, activation, checkpointing, exported-to-CLI) but it reads the ledgers, not a baked geometry map:
  - `[Mesh] FileMeshGenerator file=…` + optional `[MeshModifiers]` from mesh_plan extensions — no hand-written mesh in the deck;
  - physics keyword `block = 'base deposit'`, boundaries from `sideset_name()` mapping;
  - per-torch UOs, per-zone material IDs (`[Materials]` blocks stay zone-scoped) — zone names in deck, not geometry constants;
  - the deck lint gate GZ (within Z4) runs `grep 'zone_rule'`: fails deck if any raw tag/coordinate appears in a physics keyword (this is the R-discipline equivalent of the v1 builder's registry).
- Deck validation pass (pre-solve, v1 §10.3 style) extended: verify every zone has material; every torch path cell faced a block; every fixture mask maps on ≥ 1 element; every sideset name used by a BC exists on the found mesh. One dry-run failure message = one row that does not parse — the same important UX as today, not more.

## 9. Runner DAG & resumability (R8)

```
run_v2.py --scenario <dir>
  node G0 mesh_kernel      → wall.msh + mesh_report.json        (checks quality floors, zone audit)
  node G1 thermal window*  → checkpoints/cp_window_*            (moose.md §11.2 native)
  node G2 mech checkpoint  → checkpoints/cp_mech
  node G3 audit_res        → solver_results.json (+ zone_meta, torch_meta)
  node G4 plots/report     → report.html                        (contract unchanged)
```

- a node that's already done is skipped on re-run with the same zone-sig; `--from <node>` re-launch a node forward from a previous one → its outputs stay reflected all the way (solver-registry consistency, previously only the ledger's own internal numbers, now also outputs).
- every GUI-launched run is a plain `subprocess` on the same script, since the GUI may not own state (R9).

## 10. GUI plan (PySide6) + the ParaView criterion (R10)

You right-attribute the trade: the commercial windows look professional because they use a **native toolkit's defaults + a scene graph + command-pattern undo/redo + no custom theming**. ParaView is C++/Qt/VTK; the Python there is a *console*, not the window. GUI plan:

- Stack: **PySide6**, three panes: model tree (QTreeView fed by a QAbstractItemModel that wraps the five ledgers as the tree's backing store), 3D view (PyVista/VTK Qt widget; zones semi-transparent — plain grayscale fill; no custom palettes), console/messages pane tailing the run log + audit. Toolbar: Undo / Run / Pause / Stop / Gates. Everything else lives in the tree context menus.
- Undo/redo: QUndoStack of ledger edits (command pattern) — i.e. the tree, mesh plan and assignments are just undo-edits against the YAML files.
- Run control = relaunch/spy on `run_v2.py`; progress from the same v1 run-log tail (no GUI-side state); the audit tail streams alongside.
- **ParaView criterion** (lint-enforced — this is what prevents drift into a colorful dashboard):
  1. grep-based: **zero hex-color literals** (`#[0-9a-fA-F]{6}`) in `gui_v2/**` (tk's 147-color slop is the named anti-pattern; regression test in the suite — D11);
  2. no stylesheet/theme overrides; OS/Qt native palette only;
  3. no GUI-only state: every display (plot, gates, tree) rereads artifacts or ledgers on refresh; deleting a view costs $0 state.
  4. motion budget: ice-launching a scene causes ≤ 1 IPC call; the render/renderer message pane may only append the run's own text.
- **Back-compat**: legacy `gui/app.py` stays orchestrating the v1 pipeline until F6 (a.k.a d10); the ParaView criterion lint does not apply to it (already-shipped legacy does not turn red); the *de-slop commit* for `app.py` colors = zero risk, separate, whenever the lane is picked.

## 11. Zone gates (Z1–Z12) — acceptance required numbers hard

| Gate                                                                                                          | Pass criterion                                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Z1                                                                                                            | one scenario runs end-to-end from ledgers: box baseplate (hex/prism) + 3-layer wall (tets), v1-comparable outputs (same window, same `Solver`),                                                     |
| run reproduces v1 thermal+mech targets within v1 § 23.H tolerance on that EXACT geometry when both lanes tet |                                                                                                                                                                                                       |
| Z3                                                                                                            | mixed BASE(prism/hex) + WALL(tet) done; mixed-block audit passes applied R15 checks; halves acceptable; mesh_report shows both blocks                                                                 |
| Z4                                                                                                            | **Zone rule enforced**: deck lint fails raw-tag/coord keywords; zero-torch? deck should warn; Zlint: no orphan zone referenced                                                                  |
| Z5                                                                                                            | fixture roster: 2 clamps arbitrary placed with springs; the label-1 era is dead (grep finds no legacy fixture)                                                                                        |
| Z6                                                                                                            | scenario WITHOUT baseplate runs cleanly (absence as data: no basepart — no `BASE` block anywhere in deck/mesh)                                                                                     |
| Z7                                                                                                            | DAG resume true: kill mid-window,`--from G1` resumes with intact checkpoints, audit totals reconcile to the same energy total                                                                       |
| Z8                                                                                                            | file parity: changing only ledgers via editor, re-run, outputs equal — and deleting the GUI entirely has no runable lane gap                                                                         |
| Z9                                                                                                            | ParaView criterion suite-lint green: zero hexcolors (D11) + no style sheets + no GUI-only state                                                                                                       |
| Z10                                                                                                           | performance budget R16 met on the mixed scenario (≤ 1.4× v1 per layer)                                                                                                                              |
| Z11                                                                                                           | legacy DEFAULT scenario loads via `legacy→ledger` compatibility importer unchanged totals v1 vs ledger                                                                                             |
| Z12                                                                                                           | suite ≥ 460 with new zone-relevant sections (D9–D12); twin hooks (G13-lane receipts with scenarios) still present post-v2                                                                           |
| Z13                                                                                                           | probe reproducibility: two back-to-back probe runs differ ≤ 3 % wall; recommendation is a stable artifact (`probe_report.json` + profile chip in report)                                           |
| Z14                                                                                                           | parallel-vs-serial: same window, k ranks vs serial — thermal frame agreement within appendix-H bands and audit Δinjected/injected ≤ 0.2 %                                                          |
| Z15                                                                                                           | mesh-kernel swap: one zone meshed with a second kernel (Netgen or Cubit) passes the SAME conformality + naming checks (no kernel-specific special-casing in `zone_builder`)                         |
| Z16                                                                                                           | native layer-cake lane: per-layer blocks `DEPOSIT_L1…LN` + planar top/bottom sidesets; re-meshing ONE layer leaves others byte-stable; activation schedule intact; wall total within v1 tolerances |

## 12. Test & suite sections (R12)

- D9 zone_ledger: parser + hashes + absence + legacy importer.
- D10 torch/fixture roster: per-torch ledger sums, merge_pool sums, 2-clamp spring, thermal clamp.
- D11 GUI lanes: the ParaView criterion lint (hexcolors grep in gui_v2), file-parity smoke, undo-redo operations checks.
- D12 run-profile rows: fixed scenario with a recorded knee (E(4)/E(8)) in a golden file (parallel regressions turn red); memory-model fit error < 15 %; serial replay byte-stability; kernel-swap unit checks.
- v1 suite untouched: zone additions **accumulate** — the target is v1's ≥ 380 + ≥ 70 = **≥ 460** checks.

## 13. Performance plan

- v1 budgets preserved throughout; mixed meshing actually helps (prism baseplate ≫ tet for equivalent accuracy → fewer wall-node DOFs) — but budget must not regress: mixed run ≤ 1.4× v1-per-layer (Z10).
- Mesh kernel wall time budget: zone meshing ≤ 20 s per scenario for the small-complexity defaults; quadratic scale budget from v1 (§20).

## 14. Risks (ZR table)

| ID   | Risk                                                                              | Likelihood | Impact | Mitigation                                                                                                 |
| ---- | --------------------------------------------------------------------------------- | ---------- | ------ | ---------------------------------------------------------------------------------------------------------- |
| ZR1  | Mixed-mesh runs validate but that's through a nonconformal wart nobody noticed    | M          | H      | conformal strictly enforced in mesh_kernel; mesh-report RF debug output; Z3 needs block-DIY reports        |
| ZR2  | libMesh GmshIO limits w/ v4.1 or higher-order/complex types                       | M          | M      | write v4.1 format; keep leading v4.2; ready private msh→exo converter as backup B-lane                    |
| ZR3  | GUI scope creep (styling, custom floats) wins over ledgers                        | H          | M      | Z9 lint + file parity + the doctrine "the tree is the app"                                                 |
| ZR4  | merge_pool (tandem) physics vs separate sources: physical validation unidentified | M          | M      | drive with v1 param sweep; extra gate G13-like; laser alternative later if uncertain                       |
| ZR5  | zone explosion in yamls when walls grow to N layers                               | M          | M      | layering-part kind with a single `stack` reference; zones stay few                                       |
| ZR6  | Two lanes racing: ledgers change while MOOSE M-lanes (v1) also evolve             | M          | M      | F0–F2 lane could start in parallel with v1; F3+ requires v1 P3 builder rail locked                        |
| ZR7  | mixed-mesh zone→block id hash renames due to OCC → engine mismatch              | L          | M      | stable zone ids verified by hash at build; rename-after-hash fail-fast                                     |
| ZR8  | baseplate-absent scenarios change normalization (BC counts, sink paths)           | M          | H      | baseplate.absence is its own suite scenario (D9), dashboard shows absent-zone summaries                    |
| ZR9  | Over-subscription / HT false speedups poison the knee detection                   | M          | M      | use PETSc perf_log (CPU vs wall) as probe telemetry; refuse ranks > nproc−1 without flag; D12 golden knee |
| ZR10 | Memory model wrong on new hardware (MUMPS fill-in differs per matrix)             | M          | M      | per-rank memory measured per probe, recorded, model fit error gate (D12);`--reserve-mem` guard           |
| ZR11 | Cross-kernel conformality drift (Netgen/native zone against gmsh neighbor)        | M          | M      | cross-kernel zones allowed ONLY along planar interfaces (policy §18); Z15 proves one swap end-to-end      |
| ZR12 | Native layer-cake lane drifts vs slicer geometry updates                          | M          | M      | lane CONSUMES the slicer's per-layer polygons (no second slicing code); D9 golden geometry diff            |

## 15. Phased delivery (F-phases; each exit criterion hard)

| Phase | Content                                                                                                                                                 | Exit criterion                                                               | Days   |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------ |
| F0    | ledgers schema + parser + legacy importer + hash rules + demo scenario data                                                                             | Z11                                                                          | 2–4   |
| F1    | geometry kernel (gmsh OCC; boolean fuse/cut; named zones; STL fallback)                                                                                 | a docket geometry → named zone volumes + sidesets                           | 3–5   |
| F2    | mesh kernel: per-zone plan, conformal assembly, mesh_report, path C export w/ named blocks+sidesets                                                     | `.msh` loads in combined-opt with blocks & sidesets (echantillon scenario) | 4–6   |
| F3    | `zone_builder.py` (reads ledgers → `.i` v2), deck lint, dry-run UX                                                                                 | Z4                                                                           | 4–6   |
| F4    | torch roster compositions (dual / tandem / coax / driver-follower) + roster audit columns                                                               | Z2                                                                           | 3–5   |
| F5    | fixture roster (boxes/cylinders/face masks; rigid/spring/thermal)                                                                                       | Z5, Z6 (alongside baseplate-absence)                                         | 2–4   |
| F6    | GUI PySide6 skeleton: tree+undo+3D view+file parity; legacy GUI continues running v1                                                                    | Z8, Z9                                                                       | 5–8   |
| F7    | mixed-mesh pre-registered acceptance checks (R15) + DAG resume + solver_results zone_meta + torch_meta                                                  | Z3, Z7, Z10                                                                  | 4–6   |
| F8    | gates battery + suite D9–D11 to ≥ 450 + perf profiling                                                                                                | Z9–Z12                                                                      | 3–5   |
| F10   | run-profile manager: hardware profile, suitability model, probe harness (1/2/4/8/… early-stop), per-mode PETSc solver profiles, profile chip in report | Z13, Z14                                                                     | 3–4   |
| F9    | twin hooks + docs + ship (agentic-ready: run_v2 `--scenario demo_v2` green from clean checkout)                                                       | ship gate                                                                    | 2–3   |
| F11   | (optional, strategic) native layer-cake lane: MeshGenerator C++ class consuming slicer polygons; per-layer blocks; layer-only re-mesh                   | Z16                                                                          | 10–15 |

**Sums:** MVP (F0–F4): 16–26 d; **full build (F0–F10)**: 35–56 d; **+ layer-cake lane (F11, optional)**: 45–71 d — the strategic native-mesher step. F0–F2 can run in parallel with v1 phases P3–P6. These figures are honest: the ledgers are code-friendly (parsers + codegen rail exist); the true v2 cost is the meshing integration and the GUI rebuild.

## 16. Recap

1. F0 (data model) starts whenever you say — it is independent of v1's P-phases and unblocks both.
2. F1–F2 meshing integration; Z3 proves the mixed path; path C (gmsh `.msh` direct) is the already-measured mover.
3. F3/F4/F5 make the zone path honest: torch and fixture rosters replacing baked positions, audit extended per torch.
4. F6 GUI rebuild on native PySide6 with the file-parity rule; the ParaView criterion lint becomes a suite-gated feature.
5. F7–F9: validation, gates, suite and ship; FreeFEM stays the tet-oral and audit checkpoint reference throughout; the twin lane (calculix.md §23.K) is preserved with all hooks by design.
6. F10 FREE run profiles: every geometry gets a measured serial-vs-parallel recommendation (probe at 1/2/4/8/…, early-stop at the knee); serial replay stays deterministic for suite/gates (v1 §20 pointer inserted for this contract).
7. F11 (optional strategic): the NATIVE mesher lane for prismatic deposition — layer-cake MeshGenerator inside the app; general 3D meshers stay external (gmsh primary; Netgen/Cubit alternate), because a general mesher is person-years and the layer-cake is weeks (§18).

---

## 17. Run-profile manager (R17, R18) — serial/parallel per geometry, decided by MEASUREMENT, not vibes

MOOSE brings the parallel engine for free (PETSc/MPI); robustness means the *decision layer*: every geometry is unique, so the framework PICKS the profile per case and proves the pick cheaply.

### 17.1 Hardware profile (once per machine, cached in `machine.yaml`)

```yaml
machine_profile/1:
  n_cores: <sysctl hw.ncpu>           # logical; n_cores_physical measured at probe (HT check)
  ram_gb: <sysctl hw.memsize>
  scratch_speed: <measured: write 1 GB, read back>   # checkpoint band M/1 bandwidth matters
  mpi: {impl: MPICH?, ver: <mpirun --version>, ranks_max_ok: <nproc>}
  solver_avail: [MUMPS, SuperLU_DIST, GAMG, ASM]
```

### 17.2 Suitability model v0 (the free first guess — no probing needed for small/unusual cases)

Inputs are the mesh/kernels/v1 baseline knowns: `DOF_thermal`, `DOF_mech ≈ 3×`, `element count`, `layer count` from `mesh_report.json`:

| Regime (thermal stage guide)           | Decision                                                          |
| -------------------------------------- | ----------------------------------------------------------------- |
| DOF < 250 k**and** windows < 20  | **serial** (direct LU; deterministic; no probe needed)      |
| 250 k ≤ DOF < 800 k                   | **probe** (knees near 2–4)                                 |
| 800 k ≤ DOF and/or mech anatomy heavy | **probe mandatory** (budget path: ≥ 4 ranks default guess) |
| MUMPS memory guess > 0.75×RAM         | switch candidate to KSP+ASM/GAMG FIRST, then probe                |

Min per-rank floor: **≥ 12k DoF/rank** (below: overhead-dominated → recommend fewer ranks than that floor supports — report the honest answer even if it's "serial").

### 17.3 Probe protocol (the answer to your "initial time using 1,2,4,8,10… cores and come back")

- Same mesh + same solver set, NEVER re-mesh. Probe uses the "first `k_w` thermal windows" of the ACTUAL scenario (k_w = clamp(ntotal/6, 3, 10)) — real physics, real UOs, real I/O — not a synthetic benchmark.
- Probe sequence `[1, 2, 4, 8, …]` up to `n_cores` (10/12/16 included where hardware allows — automatic early-stop:
  - stop when E(k) < 0.55 AND E(k−1) already recorded, OR when marginal wall-benefit of the next step < 15 %;
  - if E(4) ≥ 0.85, 8+ runs only when per-rank DoF > 80k (memory pressure suggests true scale).
- Telemetry per run (from PETSc perf_log, not just wall): wall, CPU, per-rank peak memory, solver iterations, mesh partition time — into `probe_report.json` (see below).
- Fit and report: S(k) speedup, E(k) efficiency, knee = max k with E ≥ 0.55 AND next-step benefit > 15 %;
  per-rank memory curve — a CHOICE line: `profile: {mode: parallel, k: k_rec, per_rank_mem_gb: …, rationale: numbers}`.
- Then a confirmation run: k_rec on a mid-size window set, reconciles against the serial run of the same frame (same Z14 band); final chip: a stamped profile artifact + a one-line "recommendation" is what the GUI front page shows.
- Budget: probe ≤ ~15 min for a 250k-DoF-class scenario; if the suitability model says serial deterministically, the probe is SKIPPED entirely (cost 0).

=== probe_report.json (artifact contract) ===

```json
{
  "probe": {"v": 1, "scenario_sig": "…zone hash…", "k_profile": [1,2,4,8],
             "rows": [{"k":1,"wall_s":…,"cpu_s":…,"mem_gb_pp":…,"s":1.0,"e":1.0}, …],
             "knee": 4, "efficiency_at_knee": 0.72, "memory_limit_used": 0.61,
             "profile_recommend": {"mode": "parallel","k": 4,"serial_profile_cost": 1.9}}
}
```

### 17.4 Solver profiles per mode (baked into `zone_builder` as mode switches)

| Mode                      | PETSc set (defaults in deck)                                     | Notes                        |
| ------------------------- | ---------------------------------------------------------------- | ---------------------------- |
| serial 1                  | `-ksp_type preonly -pc_type lu` (or MUMPS if installed bigger) | deterministic, tight         |
| probe + parallel small k  | `-ksp_type fgmres -pc_type asm -pc_asm_overlap 1`              | the workhorse default        |
| parallel large (DOF > 1M) | `-pc_type gamg` for thermal; ASM for solid-mechanics           | per-rank DoF floor respected |
| always                    | `-snes_monitor -snes_converged_reason`                         | same v1 discipline           |

- the deck is generated WITH the chosen profile; `run_v2.py --profile <auto|serial|p4|p8|p16>`; auto = suitability+probe path; overrides allowed (no rank > nproc−1 unless `--oversubscribe`).
- `profile.json` chip lands in `report.html` (same front page as audit chip — the user always sees runtime model honesty).

### 17.5 Reproducibility bands (R18) — THE rule that keeps trust intact

- **Serial replay is the deterministic backbone**: suite, gates, golden plots, twin-lane reference runs — ALL serial (CI cost profile).
- **Parallel runs are tolerance-banded**, not deterministic: floating-point summation order across ranks differs; the bands live in the shared appendix-H sheet: same-window frame agreement ΔT ≤ 0.5 K; audit Δinjected/injected ≤ 0.2 % — the audit stays the SCALE-INDEPENDENT truth of arc energy, independent of rank count.
- Suite rule D12: a small scenario with a RECORDED knee and per-rank memory — regression tests against golden numbers catch slow-kernel and partitioner creep (E(4) drop 0.85 → 0.4 turns red).

### 17.6 Gates Z13–Z14 + risks ZR9–ZR10 (see gated tables above) + phase F10 (3–4 d).

---

## 18. Meshing-kernel options (R19) and the native-mesher question (R20)

### 18.1 Explicit answer to "can we build a native mesher?"

**A general 3D solid mesher (robust surface recovery + Delaunay refinement + quality optimization from arbitrary geometry) is person-years** at the level of Netgen/TetGen/gmsh — nobody builds it inside an application. What CAN be built, and is a genuine strategic WIN here, is a **narrow-domain native lane**, because WAAM deposition geometry is honest prisms: the wall is LAYER CAKES built from slices.

**Native layer-cake `WAAMLayercakeMeshGenerator`** (a C++ `MeshGenerator` class INSIDE the MOOSE app — no external mesher):

- input: the *existing* slicer's per-layer polygon outlines (consumed, no second slicing code);
- mesh: per layer, 2D polygon → triangles (flat robust 2D, no Delaunay 3D rabbit hole) → prism stack with per-layer z bands;
- output: per-layer blocks `DEPOSIT_L1…LN`, block per-layer side sets (top/bottom), overlay sidesets from zones.yaml masks;
- superpowers: **layer-only re-mesh** (re-layer 7 grows only L7, others byte-stable — the R2 "region re-mesh without global rebuild" feature in its truest form); deterministic, reproducible, zero mesh-kernel bin-versions; partitioner-friendliness (libMesh METIS default);
- for baseplates: straightforward prismatic/extruded via the existing MOOSE native generators (`CartesianMeshGenerator` + `MeshExtruderGenerator` + `SubdomainGenerator`), zero code and fully reproducible.
- estimate: 10–15 d (F11), validated as Z16; the lane consumes the same zone-ledger contract (`kernel: layercake`).
- honest limitations kept: no curved/complex STL caps in this lane (those stay gmsh-tet: the layer-cake only goes where geometry is prisms).

### 18.2 Alternatives to gmsh ranked for us

| Option                                             | License                              | Quality/class                                                                                      | 3D from geometry | Hex/prism                    | IO to our contract                                                                 | Automation                                                     | Verdict for us                                                                     |
| -------------------------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------- | ---------------- | ---------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| **gmsh 4.15.2 (stay)**                       | GPL                                  | strong general, OCC, robust tets; the Delaunay ladder from this session is verified                | yes              | limited (recombine classes)  | `.msh` direct into MOOSE (measured)                                              | python API                                                     | **PRIMARY**                                                                  |
| **native layer-cake lane (R20)**             | ours                                 | narrow-domain structured prisms                                                                    | prismatic only   | hex/prism by design          | MeshGenerator native                                                               | fully scripted                                                 | **STRATEGIC ADD** (F11)                                                      |
| **Netgen/NGSolve**                           | LGPL                                 | strong tets, curvature-adaptive, OCC geometry, STL ingestion                                       | yes              | mostly tetra                 | exports Gmsh-compatible + m5; needs msh conversion (meshio)                        | python wheels/macOS (verify at Z15)                            | alternate tet kernel; second lane (optional)                                       |
| **Coreform Cubit**                           | commercial (free tier's node-capped) | industrial hex/tet mixed, scripted journals                                                        | yes              | excellent hex                | **native Exodus II writer** (our IO contract free), reachable under journals | .jou scriptable                                                | best "Ansys-like" feel; adopt IF license allows teaching set sizes; otherwise park |
| **snappyHexMesh / cfMesh (OpenFOAM family)** | LGPL/BSD                             | automatic hex-dominant from STL, parallel native, boundary layers                                  | STL              | hex-dominant (polygon class) | conversion chain needed; more CFD-tuned                                            | case-dict driven                                               | pathological-STL salvage lane only; not MVP                                        |
| **TetGen as C++ lib**                        | AGPL 3.x                             | robust quality tets in-memory                                                                      | yes              | tetra                        | same                                                                               | C++ embed (NOT the dead-end python wrapper — measured §23.J) | park: revisit only if gmsh's STL boundary-recovery merits better path              |
| **CGAL Mesh_3**                              | GPL (parts LGPL)                     | very robust predicates, center-exact quality                                                       | yes              | tetra                        | same conversion                                                                    | C++ only                                                       | park same reasons as TetGen                                                        |
| **Salome SMesh**                             | LGPL 2.1                             | full GUI+script workflows; heavy deps                                                              | yes              | hexa via hex-tet trans       | equivalent                                                                         | scriptable                                                     | not MVP (installation bloat on macOS)                                              |
| **MMG3D/MMG5**                               | LGPL                                 | **remesher** (adaptive/aniso), not generator — COMPLEMENTS any lane after                   | (adapt existing) | —                           | mesh in/out                                                                        | bin + lib                                                      | optional quality/comparison (later)                                                |
| **MOOSE-native structured generators**       | LGPL (framework)                     | boxes, lattices, extruders, DIRECT parallel construction (`DistributedRectilinearMeshGenerator`) | structured only  | hex/space by design          | native exodus                                                                      | .i                                                             | baseplate today, zero code (18.1)                                                  |

### 18.3 Mesh-kernel contract (what R19 gates to hold)

For every kernel option: (a) per-zone named blocks with zone-id physical names; (b) sidesets via named masks; (c) conformal shared interfaces (or planar-interface-only when crossing kernels — ZR11); (d) deterministic output (byte-stable for golden files). `mesh_plan` carries `kernel:` per zone; omission = `gmsh` default. `zone_builder.py` stays kernel-blind: it consumes the same .msh contract whatever produced it — that's the whole point (Z15's test: same ledgers → the same deck, whichever kernel produced the mesh).

### 18.4 Parallel mesh generation? Not a problem to solve.

Mesh generation is a tiny fraction of total wall time (v1 measure: <2 % on the 10-layer case) and gmsh is single-process by design; do NOT chase parallel meshing. libMesh's partitioner (METIS default) plus per-rank DoF floors covers solve scaling. Only exotic lanes like parallel-parallel snappy even care; that's not our default workflow. (Structured native lanes can construct in parallel via `DistributedRectilinearMeshGenerator` if it ever matters.)
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## Appendix A — full `zones.yaml` draft rich-example (schema waam_zone_ledger/1)

```yaml
schema: waam_zone_ledger/1
parts:
  - id: baseplate
    kind: box
    params: {L: 60.0, W: 60.0, H: 6.0}
    zones: [base]
  - id: wall
    kind: extrusion
    params: {stack: {toolpath: {nlayers: runtime}}}
    zones: [deposit]
zones:
  - id: base
    kinds: [volume]
    faces:
      bot:  {kind: tag_range, from: 1, to: 6, name: BASE_BOTS}
      side: {kind: tag_range, from: 7, to: 12, name: BASE_SIDES}
  - id: deposit
    kinds: [volume, deposition_target]
    faces:
      bot_layers: {kind: layers, auto: true}
      wall_sides: {kind: parametric_rough, name: WALL_SIDES}
fixtures:
  - id: clamp_nw
    mask: {kind: cylinder, at: [15.0, 15.0], r: 6.0, action: z_face_clip}
    behavior: spring {kx: 1.0e6, ky: 1.0e6, kz: 1.0e5}
  - id: clamp_ne
    mask: {kind: box, at: [54.0, 6.0], size: [8.0, 8.0, clip]}
    behavior: rigid
  - id: thermal_clamp_bot
    mask: {kind: face, name: BASE_BOTS}
    behavior: thermal {T: 25.0}
torches:
  - id: torch_main
    kind: goldak
    path_ref: toolpath/1
    params: {b_band: 3.0, c_band: 2.0, R_activate: 0.6}
  - id: torch_tandem_b
    kind: goldak
    path_ref: toolpath/1
    offset: {along_tangent: +3.0}
    composition: {merge_pool_with: torch_main}
  - id: torch_coax_ring
    kind: gaussian_volumetric
    shape: {ring: {r_inner: 1.0, r_outer: 3.4}}
    path_ref: toolpath/2
mesh_plan:
  base:     {element: hex,   algo: transfinite_prism, size: 0.8, kernel: layercake}
  deposit:  {element: tet,   algo: hxt,               size: 0.8, layers: {kind: boundary, n: 2}, kernel: gmsh}
solve_plan:
  stages:
    - name: thermal
      windows: {ref: toolpath, dt_policy: adaptive_like_v1}
    - name: mech
      after: thermal
  checkpoint: {policy: window, dir: checkpoints, node_covers: [G1, G2]}
```

## Appendix B — generated `.i` sketch (zone-driven)

```
[Mesh]
  [fmg]   type = FileMeshGenerator            file = ../wall.msh
[]

[Modules]
  [HeatConduction]
    [td]  temperature = T
    []      block = 'base deposit'
    ...   # conductivity per-zone from ledgers
  []    # v1 READMEs retained: activation material per-zone
[ ]
# TORCHES
[Kernels]
  [goldak_main]
    type = WAAMGoldakKernel
    block = 'deposit'
    torch_id = 'torch_main'
    ...   # no baked positions — the UO follows path_ref at runtime
  []
[]  # etc per torch: merge_pool, ring shapes, etc.

[Materials]
  [activ_base]
    type = WAAMActivationMaterial
    block = 'base'
    zone_id = 'base'                            # never a tag, never a coordinate
  []
[]

[UserObjects]
  [toolpath]
    type = WAAMToolpathUserObject
    ledger_file = ../assignments.yaml           # UO reads the torches section directly
  []
  [audit]
    type = WAAMEnergyAuditUserObject
    columns = 'torch_main torch_tandem_b torch_coax_ring'   # per-torch bookkeeping
  []
[]
[Outputs]
  [exodus]   type = Exodus    sequence = checkpointed
  [csv]      type = CSV       columns = 'audit_ledger_*, window_*, per_zone_min_T_*'
[]
```

## Appendix C — geometry/mesh kernel sketch (gmsh python)

```python
def build_parts(parts):                                 # OCC primitives → volumes with names
    for p in parts:
        tag = OCC.by_kind(p)                            # box/extrude/cylinder → boolean ops against neighbors
        OCC.name(tag, p["zones"])                       # physical_name == zone id  (bands stable)

def conformal_assembly():                               # shared faces guarantee single zones interfaces
    OCC.fuse(part_a, part_b)  # or ambientized cut: LOT only if separate_disconnected_by_user == True

def per_zone_mesh(zone_id, plan):                       # R2 per-zone; each zone meshed independently
    if plan["element"] == "hex":
        gmsh.model.mesh.setRecombine(2, tag); gmsh.set algo(3, tag, ALGO_*);   #  transfinite_prism via extrude
    else:
        gmsh.set algo; # hxt default (v1's verified ladder reused)
    boundaries via addPhysicalGroup(2, …, name=…)     # Z4-verified naming contract
```

## Appendix D — gates checklist (copy-in)

```


NOTE : * Write ROBUST and EXTENSIVE COMMENTS in all FILES CREATED
* CREATE VERSIONING AND UPDATES based tracking too.
READ MOOSE DOCS extensively

[ ] Z1  single-zone v1 geometry reproduces v1 within tolerance
[ ] Z3  mixed blocks + audit passes + mesh_report
[ ] Z4  deck lint zero raw-tag keywords
[ ] Z5  2 fixtures arbitrary + springs; no label-1 remnant
[ ] Z6  baseplate absent → runs cleanly
[ ] Z7  DAG resume equal-totals
[ ] Z8  file parity (ledgers only)
[ ] Z9  ParaView criterion (no hex colors / no styles / no GUI-only state)
[ ] Z10 perf budget ≤ 1.4× v1 per layer
[ ] Z11 legacy importer
[ ] Z12 suite ≥ 460; twin hooks intact
[ ] Z13 probe reproducibility ≤ 3 %; probe_report.json chip
[ ] Z14 parallel-vs-serial bands (ΔT ≤ 0.5 K; Δinjected ≤ 0.2 %)
[ ] Z15 kernel-swap: same ledgers → same deck
[ ] Z16 layer-cake: per-layer blocks; layer-only re-mesh byte-stable
```

## Appendix E — vocabulary delta

| Term               | Meaning in v2                                                                          |
| ------------------ | -------------------------------------------------------------------------------------- |
| part               | parametric geometry feature (box/extrude/cylinder) or STL input; may be absent         |
| zone               | named region: a volume or a face mask; the ONLY addressable identity in `.i`/physics |
| assignment         | torch/fixture/material/initial-T entry bound to a zone or mask                         |
| mesh plan          | zone→element+algo+size mapping; not machinery, data                                   |
| solve plan         | stage DAG (thermal/mech), checkpoint rules, solvers                                    |
| DAG node           | resumable pipeline stage (G0–G4)                                                      |
| deck lint          | fails the deck if physics keywords carry raw tags/coords (R6)                          |
| ParaView criterion | zero theming slop rules for gui_v2, suite-enforced (§10)                              |
| file parity        | GUI can never own hidden state; ledgers are the single source of truth                 |
