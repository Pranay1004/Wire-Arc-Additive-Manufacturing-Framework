"""
Mesh generation, target DoF budgeting, and CAD domain synchronization mixin.
"""

import math
import os
from pathlib import Path


class EDPMeshMixin:
    """Provides structured/CAD meshing, element birth activation, and domain sync."""

    @staticmethod
    def calculate_target_mesh(params: dict, target_nodes: int = 2000, strategy: str = "physics_adaptive") -> dict:
        """Calculate optimal structured divisions (Nx, Ny, Nz) using intelligent rule-based engine."""
        try:
            from mesh.intelligent_mesher import calculate_intelligent_structured_mesh
            return calculate_intelligent_structured_mesh(params, target_nodes=target_nodes, strategy=strategy)
        except Exception:
            # Fallback calculation
            def get_m(key, default):
                v = float(params.get(key, default))
                return v / 1000.0 if v > 1.0 else v

            lx = get_m("lx", 0.2)
            ly_base = get_m("ly_base", 0.1)
            hz_base = get_m("hz_base", 0.01)
            ty_dep = get_m("ty_dep", 0.008)
            h_bead = get_m("h_bead", 0.003)
            n_lay = max(int(float(params.get("n_layers", 10))), 1)

            nz_dep = max(n_lay, 1)
            nz_base = 2 if hz_base < 0.02 else 3
            ny_dep = 3 if ty_dep >= 0.008 else 2

            aspect_y = max(ly_base / max(ty_dep, 1e-4), 1.0)
            ny_base = min(max(int(round(ny_dep * math.sqrt(aspect_y))), 4), 12)

            k = (ny_dep + 1) * (nz_dep + 1) + (ny_base + 1) * (nz_base + 1)
            nx = max(int(round(target_nodes / max(k, 1))) - 1, 4)

            return {
                "nx_dep": nx, "ny_dep": ny_dep, "nz_dep": nz_dep,
                "nx_base": nx, "ny_base": ny_base, "nz_base": nz_base,
                "target_nodes": target_nodes,
                "total_nodes": (nx + 1)*(ny_dep + 1)*(nz_dep + 1) + (nx + 1)*(ny_base + 1)*(nz_base + 1)
            }


    # exp(-3 r^2 / L^2) integrates to 95% inside r = L, so the 95%-footprint
    # radius of a Goldak axis is the axis value itself. A source whose footprint
    # exceeds the bead cross-section is clipped by the deposited volume, and the
    # clipped fraction is LOST HEAT: the arc is on for the same time but the
    # energy audit silently reports a fraction of Pweld*dt. Measured on a 7 x
    # 3.2 mm bead with the old 7/4 mm defaults: 5.1% of the intended energy was
    # actually injected (peak 485 C, no melting, despite an analytical
    # 13.5 J/mm^3 = 4.6x the energy needed to melt through). Any job on a bead
    # smaller than ~10 mm hit this.

    def _sync_cad_layer_stack(self, mesh_file: str) -> None:
        """CAD mode: make the layer stack cover the meshed part (mesh is truth).

        For the parametric wall the mesh is BUILT from (hz_base, n_layers, h),
        so the slabs always match the domain. For an imported mesh the EDP
        params routinely describe a different domain (stale UI entries): layers
        then sit inside the plate or stop halfway up the part, the top never
        activates, and the torch range misses the part entirely. The mesh file
        is therefore the single source of truth here:
          hz_base  <- detected substrate plate thickness,
          lx/ly_base <- detected plate plan (the part is centred on it),
          n_layers <- raised (never lowered) to cover the part height.
        Every correction is reported through self.warnings. No-op for the
        parametric path and when the mesh cannot be read.
        """
        p = self.p
        mesh_src = p.get("mesh_source", "parametric")
        is_cad = bool(
            mesh_src == "cad_file" or p.get("stl_file")
            or (mesh_file and str(mesh_file).lower().endswith((".mesh", ".mesh3", ".msh"))
                and mesh_src != "parametric"))
        if not is_cad:
            return
        if not mesh_file or not os.path.exists(mesh_file):
            return
        try:
            from mesh.intelligent_mesher import detect_mesh_substrate_height
        except Exception:
            return
        sub_hz_mm = detect_mesh_substrate_height(mesh_file)
        if sub_hz_mm is None or sub_hz_mm <= 0:
            return
        # Domain extents of the mesh (part + plate). Pipeline meshes are SI
        # metres; a foreign .mesh in mm is detected by its span, mirroring
        # detect_mesh_substrate_height.
        try:
            xs = []; ys = []; zs = []
            with open(mesh_file, "r", errors="replace") as fh:
                lines = [ln.strip() for ln in fh]
            i = lines.index("Vertices")
            n_vert = int(lines[i + 1].split()[0])
            for ln in lines[i + 2:i + 2 + n_vert]:
                parts = ln.split()
                if len(parts) >= 3:
                    xs.append(float(parts[0])); ys.append(float(parts[1])); zs.append(float(parts[2]))
            if not xs:
                return
            span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
            to_mm = 1000.0 if span < 5.0 else 1.0
            lx_mm = (max(xs) - min(xs)) * to_mm
            ly_mm = (max(ys) - min(ys)) * to_mm
            zmax_mm = max(zs) * to_mm
        except Exception:
            return

        hz_req_mm = float(p.get("hz_base", 0.005) or 0.005) * 1000.0
        if abs(sub_hz_mm - hz_req_mm) > 0.5:
            p["hz_base"] = sub_hz_mm / 1000.0
            self.warnings.append(
                f"CAD stack: hz_base {hz_req_mm:.1f} -> {sub_hz_mm:.1f} mm "
                f"(substrate plate in {os.path.basename(str(mesh_file))}).")
        for key, det_mm in (("lx", lx_mm), ("ly_base", ly_mm)):
            cur_mm = float(p.get(key, 0.150) or 0.150) * 1000.0
            if abs(det_mm - cur_mm) > 1.0:
                p[key] = det_mm / 1000.0
                self.warnings.append(
                    f"CAD stack: {key} {cur_mm:.1f} -> {det_mm:.1f} mm "
                    f"(plate plan in {os.path.basename(str(mesh_file))}; the part "
                    f"is centred on it, so a smaller range would park the torch "
                    f"off the part).")
        part_h_mm = max(zmax_mm - sub_hz_mm, 0.0)
        if part_h_mm > 0:
            h1_mm = float(p.get("h_bead_first", None) or p.get("h_bead", None) or 0.004) * 1000.0
            total_cad_layers = max(1, int(round(part_h_mm / h1_mm))) if h1_mm > 0 else 1
            cur_n = int(p.get("n_layers", 0) or 0)
            if cur_n <= 0:
                cur_n = total_cad_layers

            # The spatial layer height in the CAD mesh must match the physical slicing height.
            # If cur_n is total_cad_layers, each layer has height part_h_mm / total_cad_layers.
            # If cur_n < total_cad_layers (partial layer simulation), each layer retains its
            # nominal slicing height h1_mm so toolpath points and layer mid-planes align perfectly.
            if cur_n < total_cad_layers and h1_mm > 0:
                cad_layer_h_mm = h1_mm
            else:
                cad_layer_h_mm = part_h_mm / float(cur_n)
            cad_layer_h_m = cad_layer_h_mm / 1000.0
            p["n_layers"] = cur_n
            p["nz_dep"] = cur_n
            p["h_bead_first"] = cad_layer_h_m
            p["h_bead_subseq"] = cad_layer_h_m
            p["h_bead"] = cad_layer_h_m
            p["hz_dep"] = (cad_layer_h_mm * cur_n) / 1000.0
            self.warnings.append(
                f"CAD stack: synchronized {cur_n} layers of spatial height {cad_layer_h_mm:.2f} mm "
                f"to match {cad_layer_h_mm * cur_n:.1f} mm active height (nominal part height: {part_h_mm:.1f} mm).")

    def _mesh_block(self) -> str:
        """Generate mesh creation or import block."""
        p = self.p
        mesh_src = p.get("mesh_source", "parametric")
        mesh_file = p.get("mesh_file", "").strip()
        stl_file = p.get("stl_file", "").strip()

        # If stl_file is provided and mesh_file not yet generated, resolve or
        # auto-mesh it. Failures propagate: an unusable mesh must never reach
        # the solver (the old silent fallback produced a surface mesh that made
        # FreeFEM abort with SIGBUS long after the pipeline had been paid for).
        if (not mesh_file or not os.path.exists(mesh_file)) and stl_file and os.path.exists(stl_file):
            from core.platform_adapter import resolve_output_dir
            outdir = resolve_output_dir(p.get("output_dir"))
            os.makedirs(outdir, exist_ok=True)
            candidate_mesh = os.path.join(outdir, Path(stl_file).stem + ".mesh")
            if not os.path.exists(candidate_mesh):
                from mesh.stl_pipeline import stl_to_freefem_mesh
                mesh_res = stl_to_freefem_mesh(
                    stl_file, candidate_mesh,
                    target_nodes=int(p.get("target_nodes", 2000)),
                    layer_height=float(p.get("layer_height_mm", 0.0)) or 3.0,
                    # MUST match the solver's geometry: hz_base marks the
                    # substrate (z <= HzBase) and lx/ly_base are the plate plan
                    # dimensions the torch sweeps across.
                    sub_hz_mm=float(p.get("hz_base", 0.005)) * 1000.0,
                    sub_lx_mm=float(p.get("lx", 0.150)) * 1000.0,
                    sub_ly_mm=float(p.get("ly_base", 0.150)) * 1000.0,
                )
                for w in mesh_res.get("warnings", []) or []:
                    self.warnings.append(f"CAD mesh: {w}")
                if float(mesh_res.get("scale_applied", 1.0)) != 1.0:
                    self.warnings.append(
                        f"CAD geometry was auto-scaled by "
                        f"{mesh_res['scale_applied']:.4f}x to fit the build "
                        f"envelope; verify part geometry and any mass/energy "
                        f"figures quoted downstream.")
            if os.path.exists(candidate_mesh):
                mesh_file = candidate_mesh

        # CAD mode: the mesh is the single source of truth for the layer
        # stack (see _sync_cad_layer_stack). Stale hz_base / n_layers / lx /
        # ly silently parked the torch off the part and left its top cold, so
        # they are corrected here -- before any template line below consumes
        # them -- rather than trusted.
        self._sync_cad_layer_stack(mesh_file if mesh_file and os.path.exists(mesh_file) else "")

        # Check if valid FreeFEM .mesh / .mesh3 file or Gmsh MSH
        if mesh_file and os.path.exists(mesh_file) and mesh_file.lower().endswith((".mesh", ".mesh3", ".msh")):
            from core.platform_adapter import to_solver_path
            mesh_file = to_solver_path(mesh_file)
            if mesh_file.lower().endswith(".msh"):
                load_cmd = 'load "gmsh"\nmesh3 Th = gmshload3("' + mesh_file + '");'
            else:
                load_cmd = 'load "msh3"\nmesh3 Th = readmesh3("' + mesh_file + '");'
            # The CAD/STL mesh produced by mesh/stl_pipeline.py already contains
            # the substrate plate AND the deposited part as ONE conformal
            # tetrahedral volume (fused before meshing), with the boundary
            # labels the forms below expect:
            #     1 = substrate underside (hBot + fixture spring)
            #     5 = top, 2/3/4/6 = remaining surfaces (all convective)
            # A previous revision concatenated it with a separately built plate
            # (`Th = ThBase + ThCad`). FreeFEM's `+` merges NO nodes, so that
            # interface was a zero-width crack: no conduction into the plate
            # and no mechanical bond (measured 19.9 C mean / 92.9 C peak
            # discontinuity across it). The domain is now read as one mesh, so
            # that failure mode is structurally impossible.
            return f"""{load_cmd}
cout << " CAD/conformal domain mesh: " << Th.nv << " nodes  " << Th.nt << " tets" << endl;
// Boundary labels come from the mesh file (see _BOUNDARY_LABEL in
// mesh/structured_conforming.py): 1 = substrate underside, 2..6 = the
// convective/radiative surfaces. The plate inside the file spans z in
// [0, HzBase]; everything below HzBase is substrate."""
        else:
            # ---- Conforming single-mesh parametric domain --------------------
            # Total deposit height must match the free-FEM variable HzDep
            #   HzDep = (Nlayers <= 1) ? Nlayers*hBead1 : hBead1 + (Nlayers-1)*hBeadSub
            # so the generated mesh bounds agree with the layer logic below.
            _nlay = int(p.get("n_layers", 1))
            _hb1 = float(p.get("h_bead_first", p.get("h_bead", 0.004)))
            _hbs = float(p.get("h_bead_subseq", _hb1))
            _hz_dep = (_nlay * _hb1) if _nlay <= 1 else (_hb1 + (_nlay - 1) * _hbs)

            # The previous implementation built two independent cube() meshes and
            # concatenated them (`Th = ThBase + ThDep`). Their Y node spacings
            # differ, so although the faces are coplanar at z = HzBase NOT ONE
            # vertex coincides and FreeFEM does not merge them. The interface was
            # therefore a crack of zero width: measured on a running model, a mean
            # 19.9 C and peak 92.9 C temperature discontinuity across it, no heat
            # conduction from bead to plate, and no mechanical bonding at all.
            #
            # A deposited track is FUSED to the plate, so the interface is now
            # generated as ONE conforming structured mesh with a graded Y
            # direction: fine across the bead width, coarse across the rest of
            # the plate. Shared interface nodes come by construction.
            out_dir_candidate = str(p.get("output_dir", "."))
            # Create the output dir FIRST: a not-yet-existing directory fails
            # os.access(W_OK) and used to silently fall through to the SHARED
            # waam_output/cache mesh. Two builds with different parameters then
            # both read the same cache file -- whichever built last -- and the
            # earlier case ran on the wrong geometry (node count, dimensions,
            # layer stack) with no error. The cache is now only for genuinely
            # unwritable/tmp locations.
            try:
                os.makedirs(out_dir_candidate, exist_ok=True)
            except OSError:
                pass
            if out_dir_candidate.startswith("/tmp") or not os.access(out_dir_candidate, os.W_OK):
                framework_dir = str(Path(__file__).resolve().parents[2])
                fallback_dir = os.path.join(framework_dir, "waam_output", "cache")
                os.makedirs(fallback_dir, exist_ok=True)
                out_dir_candidate = fallback_dir
                self.warnings.append(
                    f"Output directory is not writable; the conforming mesh is "
                    f"written to the shared cache {fallback_dir} -- another "
                    f"case building there will overwrite it.")
            mesh_file_gen = os.path.join(out_dir_candidate, "waam_domain.mesh")
            # nz_dep semantics follow nz_dep_follows_layers (see
            # _auto_size_source): True -> the value is the TOTAL deposit cell
            # count; False -> it is PER LAYER and is scaled up here, so the
            # meshed deposit always has the resolution the source was sized
            # against. (Passing the raw value through in the False case built
            # a one-cell-per-layer mesh while the source assumed more.)
            _nz_total = int(p.get("nz_dep", 1))
            if not bool(p.get("nz_dep_follows_layers", True)):
                _nz_total = _nz_total * max(int(p.get("n_layers", 1)), 1)
            try:
                from mesh.structured_conforming import generate_waam_mesh
                info = generate_waam_mesh(
                    mesh_file_gen,
                    lx=float(p["lx"]), ly_base=float(p["ly_base"]),
                    hz_base=float(p["hz_base"]), ty_dep=float(p["ty_dep"]),
                    hz_dep=_hz_dep,
                    nx_dep=int(p["nx_dep"]), ny_dep=int(p["ny_dep"]),
                    nz_dep=_nz_total,
                    nx_base=int(p["nx_base"]), ny_base=int(p["ny_base"]),
                    nz_base=int(p["nz_base"]),
                )
                self.warnings.append(
                    f"Parametric mesh regenerated as a conforming bonded domain: "
                    f"{info['n_nodes']} nodes, {info['n_tets']} tets "
                    f"(nx={info['n_x']}, ny={info['n_y']}, nz={info['n_z']}); "
                    "deposit/substrate interface shares nodes."
                )
            except Exception as ex:
                raise ValueError(
                    f"conforming mesh generation failed: {ex}") from ex

            try:
                from core.platform_adapter import to_solver_path
                norm_mesh_gen = to_solver_path(mesh_file_gen)
            except Exception:
                norm_mesh_gen = mesh_file_gen.replace('\\', '/')
            return f"""load "msh3"
mesh3 Th = readmesh3("{norm_mesh_gen}");
cout << " Mesh (conforming, bonded interface): " << Th.nv << " nodes  "
     << Th.nt << " tets" << endl;"""

    def _prescribed_T_override(self) -> str:
        """Override temperature for prescribed-T heat source."""
        p = self.p
        return f"""        // Prescribed temperature override: the melt pool. Nodes within
        // R_activate of the torch that are active but below liquidus are
        // brought up to liquidus -- the Ansys prescribed-activation
        // methodology. The gate is Temp < Tliq, NOT coldness: gating on
        // Temp0 < Tamb+10 disqualified every node conduction had preheated,
        // so on aluminium (fast conduction) only ~6% of the bead was ever
        // born and the part never melted. A melt pool holds material AT
        // process temperature; preheated nodes are topped up, cold nodes are
        // born, nothing above Tliq is ever cooled by this block.
        // The imposed enthalpy is REAL energy entering the part, counted as
        // true Hcp differences into EprescJ; otherwise the audit shows stored
        // energy with no source.
        // Hard-ball birth at liquidus: nodes within R_activate of the torch
        // that are active but below liquidus are brought up to Tliq. A smooth
        // (cosine-squared) pool profile was tried and reverted: on coarse
        // meshes the torch threads between nodes so imposition is hit-or-miss,
        // and even resolved it imposes ~3x less energy for the same R, which
        // broke a passing validation (0.17x -> 0.05x). The hard ball's step
        // does Gibbs-ring (bounded by mesh resolution, reported via the
        // rectifier + residual metrics); the smooth ball's under-drive is
        // silent. Audited energy is exact either way (nodal true enthalpy).
        for(int iv=0; iv<Th.nv; iv++){{
            real rPool = sqrt((Th(iv).x-xTorch)^2 + (Th(iv).y-yTorch)^2 + (Th(iv).z-zTorch)^2);
            if(rPool < RpoolAct && psiActive[][iv] > 0.5 && Temp[][iv] < Tliq){{
                real zvP = Th(iv).z;
                real Htgt = Hcp(Tliq, zvP);
                // Impose in H-space: the energy added is the TRUE difference
                // Htgt - H_now (not Hcp(Tliq)-Hcp(T_interp)), weighted by the
                // SAME rhoEff the stored-enthalpy audit uses, so the balance
                // stays exact when porosity is active.
                EprescJ += lumpVol[iv]*rhoEff[][iv]*max(Htgt - Hfield[][iv], 0.);
                Hfield[][iv] = Htgt;
                Temp[][iv] = Tliq;
            }}
        }}
"""

