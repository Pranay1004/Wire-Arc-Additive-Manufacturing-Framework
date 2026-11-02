"""
Core FreeFEM .edp script builder combining modular physics mixins.
"""

import difflib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.multimaterial.alloy_metallurgy import get_alloy_category, get_alloy_scheme
from .defaults import EDPDefaultsMixin
from .validation import EDPValidationMixin
from .materials import EDPMaterialsMixin
from .heat_sources import EDPHeatSourceMixin
from .mesh_setup import EDPMeshMixin
from .mechanical import EDPMechanicalMixin
from .stages import EDPStagesMixin


class EDPBuilder(
    EDPDefaultsMixin,
    EDPValidationMixin,
    EDPMaterialsMixin,
    EDPHeatSourceMixin,
    EDPMeshMixin,
    EDPMechanicalMixin,
    EDPStagesMixin,
):
    """Builds a complete FreeFEM .edp script from parameters."""

    def __init__(self, params: dict):
        """
        Args:
            params: Dictionary of all simulation parameters.
                    See `default_params()` for the full schema.
        """
        defaults = self.default_params()
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        # Drop Nones on known boolean switches so the framework default applies.
        for key in self._BOOL_KEYS:
            if clean_params.get(key) is None:
                clean_params.pop(key, None)
        self.p = {**defaults, **clean_params}
        self._validate()
        # Unknown keys used to be silently ignored: a typo ('n_layer' for
        # 'n_layers') ran the case on the 26-layer DEFAULTS with no error and no
        # warning (measured: a whole smoke run silently used default geometry
        # and power). Warn loudly, and name the nearest real key when one is
        # close enough to be the obvious intent.
        known = set(defaults) | self._EXTRA_KEYS
        for key in (params or {}):
            if key in known:
                continue
            close = difflib.get_close_matches(key, known, n=1, cutoff=0.75)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            self.warnings.append(
                f"Unknown parameter '{key}' ignored.{hint} "
                f"See EDPBuilder.default_params() for the schema."
            )


    def build(self) -> str:
        """Generate the complete .edp script."""
        p = self.p
        # The mesh must exist (and the CAD layer stack be synced to it) BEFORE
        # any parameter below is consumed: _mesh_block auto-meshes a missing
        # CAD mesh and corrects hz_base / lx / ly_base / n_layers against
        # the meshed domain, which the template reads throughout.
        mesh_block_str = self._mesh_block()
        Pweld = p["I_weld"] * p["U_weld"] * p["eta_arc"]
        h_bead_first = float(p.get("h_bead_first", p.get("h_bead", 0.004)))
        remelt_ratio = float(p.get("remelt_ratio", 0.80))
        is_cad = bool(
            p.get("mesh_source") == "cad_file" or p.get("stl_file")
            or (p.get("mesh_file") and str(p.get("mesh_file")).lower().endswith((".mesh", ".mesh3", ".msh"))
                and p.get("mesh_source") != "parametric"))
        default_h_sub = h_bead_first if is_cad else (h_bead_first * remelt_ratio)
        h_bead_subseq = float(p.get("h_bead_subseq") or default_h_sub)
        n_layers = int(p.get("n_layers", 10))
        hz_dep = h_bead_first if n_layers <= 1 else (h_bead_first + (n_layers - 1) * h_bead_subseq)
        hz_tot = p["hz_base"] + hz_dep
        y_centre = p["ly_base"] / 2.0
        y_left = y_centre - p["ty_dep"] / 2.0
        y_right = y_centre + p["ty_dep"] / 2.0
        t_pass = p["lx"] / p["v_scan"]

        mat_funcs = self._material_functions()
        source_block = self._heat_source_block()
        uva_thermal_block = self._ultrasonic_thermal_block()
        mech_order = int(p.get("mechanics_order", 1))
        if mech_order not in (1, 2):
            raise ValueError(f"mechanics_order must be 1 or 2, got {mech_order}")
        mech_fe = "P2" if mech_order == 2 else "P1"
        n_thermal_corr = max(1, int(p.get("thermal_correctors", 3)))
        r_activate = float(p.get("R_activate", 10.0e-3))
        # Torch-advance cap: dt <= (source width / N) / v_scan. N=8 is the
        # validated default (torch advances <= 1/8 source width per step);
        # larger N trades moving-source resolution for runtime.
        src_travel_frac_fmt = ("%.1f" % float(p.get("src_travel_fraction", 8.0)))
        is_prescribed = 1 if str(p.get("heat_source", "goldak")).lower() == "prescribed" else 0
        corr_tol = float(p.get("thermal_corr_tol_C", 0.5))
        mpi_rank_dirs = ""
        if bool(p.get("mpi_safe", False)):
            # MPI multi-rank safety: every rank writes into its own
            # subdirectory, so N ranks can never corrupt each other's VTU/PVD/
            # CSV/JSON/checkpoint files. Rank 0's tree is the canonical result;
            # the mesh and all inputs are replicated (read-only sharing is
            # safe), only WRITES are partitioned. This is Phase 1 of MPI
            # support (safe, not yet fast): true distributed solve via Dmesh
            # partitioning is Phase 2. One localized change covers every
            # current and future write site, and restart stays symmetric
            # because each rank resumes from its own directory.
            mpi_rank_dirs = (
                '// MPI Phase 1: per-rank output tree (rank 0 is canonical).\n'
                'outdir = outdir + "rank" + mpirank + "/";\n'
            )

        is_cad = bool(
            p.get("mesh_source") == "cad_file" or
            p.get("stl_file") or
            (p.get("mesh_file") and str(p.get("mesh_file")).lower().endswith((".mesh", ".mesh3", ".msh")))
        )
        self.is_cad = is_cad
        # Element-birth mask rule. P0 assignment of a P1 field evaluates the
        # centroid mean of the four nodal values, so `> 0.999` is true only when
        # ALL nodes are active. That is the correct rule for the structured
        # parametric mesh, where activation is a slab and whole elements are
        # born at once. On a CAD/tet mesh the torch footprint (radius r_act) is
        # a fraction of the element size, so almost no element ever has all
        # four nodes inside it: the mask stayed ~0 and the arc injected ZERO
        # energy for the whole build (measured: injected_arc = 0 J against
        # 6400 J intended). There the rule is "any node active".
        if is_cad:
            srcmask_init = (
                "// CAD mesh: an element is born once MOST of its nodes are\n"
                "// active (P0 centroid evaluation of P1 psiActive > 0.5 means a\n"
                "// majority vote; see the birth-mask note in the builder: the\n"
                "// all-nodes rule never fires when r_act < element size).\n"
                "srcMask = (psiActive > 0.5);")
        else:
            srcmask_init = (
                "// Structured mesh: an element is born only when ALL four nodes\n"
                "// are active, which is what stops P1 assembly smearing arc\n"
                "// energy onto quiet vertices at the deposition front.\n"
                "srcMask = (psiActive > 0.999);")
        # The in-loop recompute sites use the same rule as the initial one.
        self._srcmask_step = srcmask_init
        srcmask_step = srcmask_init
        # Activation footprint (CAD path): an ellipse matched to the SOURCE
        # footprint, not a fixed small circle. The previous circle
        # (r = 0.5*max(af,bG)) was tuned for a collapsed sub-mm source; once the
        # source spans the bead it masks away the energy deposited outside the
        # core (measured: 45.8 % injection fidelity, the rest of the Gaussian
        # falling on never-born elements). The ellipse ((x/a)^2+(y/b)^2 <= 1)
        # births exactly where the source is significant (98 % of each axis)
        # and nothing beyond it, so the old "too large" concern
        # (r = max(af,bG) + 4 mm disc) does not return.
        _af = p.get("af") or 0.008
        _bG = p.get("bG") or 0.007
        _cG = p.get("cG") or 0.004
        _w_dep = p.get("ty_dep") or 0.008
        r_act_x = max(_af, _w_dep * 0.5)
        r_act_y = max(_bG, _w_dep * 0.5)
        r_act_z = max(_cG, p.get("h_bead", 0.004) * 0.85)

        # Progressive 3D spatial activation:
        # Deposit nodes (zv > HzBase) are activated strictly when the moving torch
        # passes over them with the arc ON (pState > 0). Once active, nodes remain
        # active for all subsequent time-steps. Nodes ahead of the torch in the
        # layer or on other toolpath segments remain inactive until the torch arrives.
        act_cond = (
            f"((zv > HzBase + 1.e-6) ? ("
            f"  (((xv - xTorch)^2 / {r_act_x**2:.6e} + (yv - yTorch)^2 / {r_act_y**2:.6e} <= 1.0) && "
            f"   abs(zv - zTorch) <= max({_cG:.6e}, zLayH * 0.85) && (pState > 0.0))"
            f") : 0)"
        )

        # Build radiation block
        rad_update = ""
        if p["enable_radiation"]:
            rad_update = f"""
            real TvK = Tv + 273.15;
            real TaK = {p['T_amb']} + 273.15;
            real hRad = {p['emissivity']}*5.67e-8*(TvK*TvK + TaK*TaK)*(TvK + TaK);
            hSurf[][iv] = {p['h_conv']} + hRad;"""
        else:
            rad_update = f"""
            hSurf[][iv] = {p['h_conv']};"""

        # Multi-material properties for base plate vs deposited beads
        mat_base = p.get("material_base", p.get("material", "ER70S-6"))
        mat_dep = p.get("material_dep", p.get("material", "ER70S-6"))
        db_path = Path(__file__).resolve().parents[2] / "core" / "multimaterial" / "material_database.json"
        db = {}
        if db_path.exists():
            with open(db_path) as f:
                db = json.load(f).get("alloys", {})
        rho_base = db.get(mat_base, {}).get("density", p.get("rho", 7850.0))
        rho_dep = db.get(mat_dep, {}).get("density", p.get("rho", 7900.0))

        # Build mechanical stage
        mech_stage = ""
        if p["enable_mechanical"]:
            mech_stage = self._mechanical_stage_setup()
        else:
            # The summary/JSON block reports the equilibrium convergence state
            # unconditionally, so these symbols must exist even in a thermal-only
            # run. Without them `enable_mechanical=False` fails to COMPILE with
            # "The Identifier newtonDone does not exist".
            mech_stage = f"""
// --- Mechanics disabled: convergence state is trivially satisfied ---
int newtonDone = 1;      // no structural solve requested -> nothing to converge
int mechOrderCur = {mech_order};
int lastNewtonIts = 0;
real lastNewtonResid = 0.;
real lastNewtonDres = 0.;
int FinalSolidConverged = 1;
real warpageClampedFinal = 0.;
real dispMaxClampedFinal = 0.;
real sigMMaxClampedFinal = 0.;
real residFrozen = 0., dresFrozen = 0.;
int itsFrozen = 0;
"""

        # In-weld-loop mechanics increment, gated by the solve cadence. The
        # legacy "interpass" cadence emits nothing here, so the default run
        # behaves exactly as before; "layer_n"/"weld" add Abaqus-like
        # increments during deposition so plastic strain from the current pass
        # feeds the next increment (previously only inter-pass snapshots
        # contributed, so residual stress from later passes was never seen
        # mechanically).
        cadence = str(p.get("mech_solve_cadence", "interpass")).lower()
        inweld_mech = ""
        if p["enable_mechanical"] and cadence in ("layer_n", "weld"):
            if cadence == "weld":
                mech_mod = 1
            else:
                mech_mod = max(1, int(p.get("mech_solve_every_n_weld", 5)))
            inweld_mech = f"""
        // --- Incremental mechanics during deposition (cadence={cadence}, every {mech_mod} weld step(s)) ---
        if(ws % {mech_mod} == 0){{
            {self._mechanical_stage_increment()}
            dispM = sqrt(ux^2+uy^2+uz^2);
            cout << "  [MECH L" << iL+1 << " ws=" << ws << "] uz_max=" << uz[].max*1000.
                 << " mm  sigM_max=" << sigM[].max/1.e6 << " MPa  iters=" << lastNewtonIts
                 << (newtonDone ? "" : " [NOT CONVERGED]") << endl;
        }}
"""

        # Build microstructure stage (hardness/phase CSVs + z profile products)
        micro_stage = self._microstructure_stage() if p.get("enable_microstructure", True) else ""

        # --- Inter-pass cooling control ---
        # "time"   : legacy fixed dwell.
        # "target" : iterative cooldown to a peak-temperature target (Ansys
        #            "Iterative Cooldown"), which makes inter-pass temperature a
        #            controlled process variable instead of an emergent one.
        _ipmode = str(p.get("interpass_cooling_mode", "time")).lower()
        ipass_target_mode = 1 if _ipmode in ("target", "iterative", "temperature") else 0
        ipass_target = float(p.get("interpass_target_temp_C", 400.0))
        ipass_dt = max(0.1, float(p.get("interpass_time_step", 10.0)))
        ipass_tol_pct = float(p.get("interpass_converge_pct", 0.1))
        # Auto cap: derive from the time budget so a thin hot build gets enough
        # iterations to reach the target instead of silently giving up.
        _ipcap = int(p.get("interpass_max_iters", 0) or 0)
        if _ipcap <= 0:
            _ipcap = max(5, int(round(float(p.get("interpass_max_cool_s", 900.0)) / ipass_dt)))
        ipass_max_iters = max(1, _ipcap)

        # Springback (unclamping) stage. "dynamic_clamping" declared this
        # behaviour but nothing ever set clampActive=0, so the advertised
        # springback measurement did not exist. Emit a real unclamp + re-solve
        # when both flags are on.
        springback_stage = ""
        if (p["enable_mechanical"]
                and p.get("dynamic_clamping", True)
                and p.get("springback_solve", False)):
            springback_stage = self._mechanical_stage_springback()

        # Transverse size of the selected heat source. Used only by the adaptive
        # time-step controller to keep the moving arc from advancing more than a
        # fraction of the source width per step (which would smear the deposited
        # energy and show up as a collapse in the energy-audit fidelity).
        _hs = str(p.get("heat_source", "goldak")).lower()
        _i_weld = float(p.get("I_weld", 180.0))
        _p48_sig = 6.205e-4 * (max(_i_weld, 10.0) ** 0.28)
        _src_map = {
            "goldak": float(p.get("bG") or 7.0e-3),
            "p48_surface": _p48_sig,
            "p48_gmaw": _p48_sig,
            "p48": _p48_sig,
            "gaussian_vol": float(p.get("R_beam", 5.0e-3)),
            "gaussian_surf": float(p.get("R_spot", 3.0e-3)),
            "conical": float(p.get("rt", 3.0e-3)),
            "uniform": float(p.get("b_band", 5.0e-3)),
            "prescribed": float(p.get("R_activate", 10.0e-3)),
        }
        src_width = _src_map.get(_hs, 7.0e-3)


        # Heat Input Calculations
        I_weld = float(p.get("I_weld", 180.0))
        U_weld = float(p.get("U_weld", 20.0))
        eta_arc = float(p.get("eta_arc", 0.8))
        v_scan = float(p.get("v_scan", 0.008)) # m/s
        v_scan_mm_s = v_scan * 1000.0          # mm/s
        p_gross = U_weld * I_weld              # W
        p_net = eta_arc * p_gross              # W
        h_net_j_mm = p_net / v_scan_mm_s if v_scan_mm_s > 0 else 0.0
        h_gross_j_mm = p_gross / v_scan_mm_s if v_scan_mm_s > 0 else 0.0
        w_bead_mm = float(p.get("ty_dep", 0.008)) * 1000.0
        h_bead_mm = float(p.get("h_bead", 0.003)) * 1000.0
        bead_area = w_bead_mm * h_bead_mm
        e_vol = h_net_j_mm / bead_area if bead_area > 0 else 0.0

        # Wire Feedstock & Mass Deposition Calculations
        v_wire_m_min = float(p.get("v_wire", p.get("wire_feed_speed_m_min", p.get("wire_feed_speed", 5.0))))
        v_wire_m_s = v_wire_m_min / 60.0
        d_wire_raw = float(p.get("d_wire", p.get("wire_diameter_mm", p.get("wire_diameter", 1.2e-3))))
        d_wire_m = d_wire_raw / 1000.0 if d_wire_raw > 0.05 else d_wire_raw
        d_wire_mm = d_wire_m * 1000.0
        a_wire_m2 = (math.pi * (d_wire_m ** 2)) / 4.0
        a_wire_mm2 = a_wire_m2 * 1e6
        q_wire_vol_m3_s = a_wire_m2 * v_wire_m_s
        q_wire_cm3_s = q_wire_vol_m3_s * 1e6
        q_wire_mm3_min = a_wire_mm2 * (v_wire_m_min * 1000.0)
        rho_dep_val = float(rho_dep) if rho_dep else 7850.0
        m_dep_rate_kg_s = rho_dep_val * q_wire_vol_m3_s
        m_dep_kg_h = m_dep_rate_kg_s * 3600.0
        m_dep_g_s = m_dep_rate_kg_s * 1000.0
        a_bead_theo_m2 = (q_wire_vol_m3_s / v_scan) if v_scan > 0 else 0.0
        a_bead_theo_mm2 = a_bead_theo_m2 * 1e6

        # Physical Boiling / Vaporization Cutoff (Thermodynamic temperature governor)
        def get_tboil(mat_name):
            # ORDER IS LOAD-BEARING. The old ordering tested the aluminium
            # substring first, so "Ti-6Al-4V".lower() == "ti-6al-4v" matched
            # "al" and returned the aluminium boiling point (2519 C) instead of
            # titanium's (3287 C). Titanium must be disambiguated before any
            # "al" substring test.
            mat_low = str(mat_name).lower()
            if "ti-" in mat_low or "ti6" in mat_low or "titanium" in mat_low or "6al" in mat_low:
                return 3287.0  # Ti-6Al-4V
            if "al" in mat_low or "1xx" in mat_low:
                return 2519.0  # Pure Al / AlSi10Mg (Al bp 2519 C)
            if "625" in mat_low or "in6" in mat_low or mat_low.startswith("ni"):
                return 2913.0  # IN625 / Ni-base (Ni bp 2913 C)
            return 2862.0  # Carbon / austenitic steels (Fe bp 2862 C)

        def get_yield_strength(mat_name, default_val=380.0e6):
            mat_obj = db.get(mat_name, {})
            ys_list = mat_obj.get("yield_strength", {}).get("sigma_y", [])
            return float(ys_list[0]) if ys_list else default_val

        t_boil = get_tboil(mat_dep)
        sig_yield_base = get_yield_strength(mat_base, 290.0e6)
        sig_yield_dep = get_yield_strength(mat_dep, 380.0e6)

        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _outdir_raw = str(p['output_dir'])
        _outdir_posix = _outdir_raw.replace('\\', '/')
        try:
            from core.platform_adapter import to_solver_path
            outdir_norm = to_solver_path(_outdir_raw).replace('\\', '/').rstrip('/') + '/'
        except Exception:
            outdir_norm = _outdir_posix.rstrip('/') + '/'
        visdir_norm = outdir_norm + 'visual_outputs/'
        # Create dirs using the POSIX path (Python runs on the host OS);
        # outdir_norm may be a Windows-style path under WSL interop.
        os.makedirs(_outdir_posix.rstrip('/'), exist_ok=True)
        os.makedirs(_outdir_posix.rstrip('/') + '/visual_outputs', exist_ok=True)
        try:
            from core.platform_adapter import HOST_ARCH
            _is_win = HOST_ARCH.is_windows or HOST_ARCH.is_wsl
        except Exception:
            _is_win = False
        # Directories are already created by Python (os.makedirs) above; the
        # EDP's mkdir is only defensive. Keep a POSIX mkdir -p on Mac/Linux
        # (harmless) and a no-op on Windows/WSL where `mkdir -p` is invalid.
        if _is_win:
            _mkdir_cmd = '// (directories created by the host; mkdir skipped on Windows/WSL)'
        else:
            _mkdir_cmd = ('system("mkdir -p " + outdir);\n'
                          '    system("mkdir -p " + visdir);')
        for _dummy_f in ("toolpath.txt", "layer_pass_times.txt"):
            _d_path = os.path.join(outdir_norm, _dummy_f)
            if not os.path.exists(_d_path):
                try:
                    with open(_d_path, "w", encoding="utf-8") as _df:
                        _df.write("0\n")
                except Exception:
                    pass
            elif not p.get("toolpath_provided", False):
                # A pre-existing file in a REUSED output directory silently
                # overrides the requested schedule: the .edp consumes any
                # non-empty toolpath.txt and never falls back to the linear
                # scan, so a case whose parameters changed ran the OLD torch
                # path (measured: a 30-point stale path replaced the intended
                # 2-layer scan, cutting injected energy from 95.0 to 63.4 kJ).
                # run.py / validate_j2 set toolpath_provided=True after writing
                # the file intentionally; for everyone else, say it out loud.
                try:
                    _txt = open(_d_path, encoding="utf-8").read().strip()
                except Exception:
                    _txt = ""
                if _txt and _txt.splitlines()[0].strip() not in ("", "0"):
                    self.warnings.append(
                        f"Existing {_dummy_f} in {outdir_norm} will be CONSUMED "
                        f"by the solver instead of the requested scan (delete "
                        f"it or set toolpath_provided=True if this is intended).")

        cat_dep = get_alloy_category(mat_dep)
        dep_entry = self._resolve_material_entry(mat_dep, db)
        dep_hard = dep_entry.get("hardness_coefficients", {})
        dep_comp = dep_entry.get("composition", {})
        if cat_dep == "Austenitic Stainless Steel":
            # Display formula mirrors the kinetics FN blend (WRC-1992 Cr_eq/Ni_eq)
            cr_eq = dep_comp.get("Cr", 0.0) + dep_comp.get("Mo", 0.0) + 1.5 * dep_comp.get("Si", 0.0)
            ni_eq = dep_comp.get("Ni", 0.0) + 30.0 * dep_comp.get("C", 0.0) + 0.5 * dep_comp.get("Mn", 0.0)
            fn_disp = min(12.0, max(3.0, 4.0 + 10.0 * (cr_eq / max(ni_eq, 1e-9) - 1.4)))
            hv_g = float(dep_hard.get("HV_austenite", 185))
            hv_d = float(dep_hard.get("HV_delta_ferrite", 210))
            hv_blend = (1.0 - fn_disp / 100.0) * hv_g + (fn_disp / 100.0) * hv_d
            hv_formula_code = f"{hv_blend:.2f}"
        elif cat_dep == "Carbon Steel":
            hv_formula_code = (f"(fM*{float(dep_hard.get('HV_martensite', 400)):.1f}"
                               f" + fB*{float(dep_hard.get('HV_bainite', 280)):.1f}"
                               f" + fP*{float(dep_hard.get('HV_pearlite', 175)):.1f}"
                               f" + fF*{float(dep_hard.get('HV_ferrite', 140)):.1f})")
        elif cat_dep == "Nickel Superalloy":
            hv_formula_code = f"{float(dep_hard.get('HV_gamma_matrix', 230)):.1f}"
        elif cat_dep == "Titanium Alloy":
            hv_formula_code = (f"(Tpeak(xMidSamp, yMidSamp, zMidSamp) > Tsol) ?"
                               f" (fM*{float(dep_hard.get('HV_martensite_alpha_prime', 420)):.1f}"
                               f" + (fB+fF)*{float(dep_hard.get('HV_alpha_beta', 340)):.1f}"
                               f" + fP*{float(dep_hard.get('HV_beta', 300)):.1f})"
                               f" : {float(dep_hard.get('HV_alpha_beta', 340)):.1f}")
        elif "Aluminium" in cat_dep:
            hv_disp = float(dep_hard.get("HV_as_built", dep_hard.get("HV_annealed", 28)))
            hv_formula_code = f"{hv_disp:.1f}"
        else:  # unknown -> austenitic stainless blend
            hv_formula_code = "185.0"

        hs_type = p.get('heat_source', 'goldak')
        if hs_type == 'goldak':
            hs_details = f"//    - Model Type:                   Goldak Double Ellipsoid\n//    - Front Semi-Axis (af):         {p.get('af', 0.008)*1000.0:.2f} mm  ({p.get('af', 0.008)} m)\n//    - Rear Semi-Axis (ar):          {p.get('ar', 0.020)*1000.0:.2f} mm  ({p.get('ar', 0.020)} m)\n//    - Semi-Width (bG):              {p.get('bG', 0.007)*1000.0:.2f} mm  ({p.get('bG', 0.007)} m)\n//    - Depth Penetration (cG):       {p.get('cG', 0.003)*1000.0:.2f} mm  ({p.get('cG', 0.003)} m)\n//    - Energy Fractions:             ff={p.get('ff', 0.6):.2f}, fr={p.get('fr', 1.4):.2f}"
        elif hs_type in ('p48_surface', 'p48_gmaw', 'p48'):
            i_w = float(p.get("I_weld", 150.0))
            eta_d = float(p.get("eta_drop", 0.25))
            sig_q = 6.205e-4 * (max(i_w, 10.0) ** 0.28)
            hs_details = (
                f"//    - Model Type:                   P48 Coupled Surface Flux & Droplet Impingement\n"
                f"//    - Arc Gaussian Radius (sigma_q): {sig_q*1000.0:.2f} mm\n"
                f"//    - Droplet Transfer Fraction:    {eta_d*100:.1f}%\n"
                f"//    - Direct Arc Surface Flux:      {(1.0-eta_d)*100:.1f}%\n"
                f"//    - Droplet Transfer Temp:        {float(p.get('T_drop', 1627.0)):.1f} degC"
            )
        elif hs_type == 'gaussian_vol':
            hs_details = f"//    - Model Type:                   3D Gaussian Volumetric\n//    - Effective Radius (R_beam):    {p.get('R_beam', 0.005)*1000.0:.2f} mm"
        elif hs_type == 'conical':
            hs_details = f"//    - Model Type:                   Conical Frustum\n//    - Top Radius (rt):              {p.get('rt', 0.003)*1000.0:.2f} mm\n//    - Bottom Radius (rb):           {p.get('rb', 0.001)*1000.0:.2f} mm\n//    - Penetration Depth (d_pen):    {p.get('d_pen', 0.005)*1000.0:.2f} mm"
        else:
            hs_details = f"//    - Model Type:                   {hs_type.upper()}"

        # The Tboil cap is now applied in H-SPACE inside the generated loops
        # (exact stock accounting, flag or no flag) -- no boilerplate segment.

        is_cad_mesh = (p.get("mesh_source") == "cad_file")
        if is_cad_mesh:
            sub_mesh_str = "CONFORMAL CAD SUBSTRATE TETRAHEDRA"
            dep_mesh_str = f"UNSTRUCTURED CAD VOLUME TETRAHEDRA ({p.get('n_layers', 1)} layers)"
        else:
            sub_mesh_str = f"({p['nx_base']}, {p['ny_base']}, {p['nz_base']})"
            dep_mesh_str = f"({p['nx_dep']}, {p['ny_dep']}, {p['nz_dep']})"

        script = f"""// ================================================================================
// WAAM MULTI-PHYSICS SIMULATION — AUTO-GENERATED FREEFEM++ SCRIPT
// Framework: WAAM-Framework (Wire Arc Additive Manufacturing Multi-Physics)
// Generated: {now_ts}
// Output Run Directory: {outdir_norm}
// Visual Outputs (VTU): {visdir_norm}
// Native Terminal Log:  {outdir_norm}sim.log
// ================================================================================
//
/* === COMPLETE SIMULATION PARAMETER SPECIFICATION === (block comment: FreeFEM counts this whole span as one lexer unit)
//
// 1. GEOMETRY & BUILD ENVELOPE:
//    - Substrate Length (X):          {p['lx']*1000.0:.2f} mm  ({p['lx']:.4f} m)
//    - Substrate Width (Y):           {p['ly_base']*1000.0:.2f} mm  ({p['ly_base']:.4f} m)
//    - Substrate Thickness (Z):       {p['hz_base']*1000.0:.2f} mm  ({p['hz_base']:.4f} m)
//    - Deposited Bead Width:          {p['ty_dep']*1000.0:.2f} mm  ({p['ty_dep']:.4f} m)
//    - First Layer Height (h1):       {h_bead_first*1000.0:.2f} mm  ({h_bead_first:.4f} m)
//    - Remelt / Fusion Ratio:         {remelt_ratio*100.0:.1f} %
//    - Subsequent Layer Height:       {h_bead_subseq*1000.0:.2f} mm  ({h_bead_subseq:.4f} m)
//    - Total Deposition Layers:       {p['n_layers']}
//    - Deposited Wall Height:         {hz_dep*1000.0:.2f} mm  ({hz_dep:.4f} m)
//    - H_build Target (GUI driver):   {p.get('H_build_target_mm', hz_dep*1000.0):.2f} mm (ceil-rounded to Nlayers above; solver and display agree)
//    - Total Model Height (Z):        {hz_tot*1000.0:.2f} mm  ({hz_tot:.4f} m)
//    - Wall Centerline Y:             {y_centre*1000.0:.2f} mm
//    - Wall Y Span:                   [{y_left*1000.0:.2f}, {y_right*1000.0:.2f}] mm
//
// 2. PROCESS & ARC HEAT INPUT:
//    - Welding Arc Current:           {I_weld:.1f} A
//    - Welding Arc Voltage:           {U_weld:.1f} V
//    - Arc Thermal Efficiency (eta):  {eta_arc:.2f} ({eta_arc*100.0:.0f}%)
//    - Wire Feed Speed (WFS):         {v_wire_m_min:.2f} m/min  ({v_wire_m_s:.4f} m/s)
//    - Torch Travel Speed (TS):       {v_scan*1000.0*60.0:.1f} mm/min  ({v_scan*1000.0:.2f} mm/s, {v_scan:.5f} m/s)
//    - Wire Diameter:                 {d_wire_mm:.2f} mm  ({d_wire_m:.6f} m)
//    - Wire Cross-Sectional Area:     {a_wire_mm2:.3f} mm^2
//    - Feedstock Mass Deposition:     {m_dep_kg_h:.2f} kg/h  ({m_dep_g_s:.2f} g/s)
//    - Theoretical Bead Area:         {a_bead_theo_mm2:.2f} mm^2  (CAD Nominal: {bead_area:.2f} mm^2)
//    - Gross Electrical Power:        {p_gross:.1f} W  ({p_gross/1000.0:.2f} kW)
//    - Net Thermal Arc Power:         {p_net:.1f} W  ({p_net/1000.0:.2f} kW)
//    - Net Linear Heat Input (H_net): {h_net_j_mm:.2f} J/mm  ({h_net_j_mm/1000.0:.3f} kJ/mm, {h_net_j_mm:.0f} kJ/m)
//    - Gross Linear Heat Input:       {h_gross_j_mm:.2f} J/mm  ({h_gross_j_mm/1000.0:.3f} kJ/mm)
//    - Volumetric Energy Density:     {e_vol:.2f} J/mm^3  ({e_vol*1000.0:.1f} MJ/m^3)
//    - Single Pass Deposition Time:   {t_pass:.2f} s
//    - Inter-Pass Cooling Dwell:      {p['t_wait']:.2f} s

// 3. HEAT SOURCE MODEL:
{hs_details}
//
// 4. ALLOYS & THERMOPHYSICAL PROPERTIES:
//    - Substrate Base Alloy:          {mat_base}
//      * Base Density (rhoBase):      {rho_base:.1f} kg/m^3
//      * Base Yield Strength (RT):    {sig_yield_base/1e6:.1f} MPa
//    - Deposited Bead Alloy:          {mat_dep}
//      * Deposit Density (rhoDep):    {rho_dep:.1f} kg/m^3
//      * Deposit Yield Strength (RT): {sig_yield_dep/1e6:.1f} MPa
//    - Melting Solidus Temp (Tsol):   {p['T_sol']:.1f} deg C
//    - Melting Liquidus Temp (Tliq):  {p['T_liq']:.1f} deg C
//    - Boiling / Vaporization (Tboil): {t_boil:.1f} deg C
//    - Stress Annealing Temp (Tmech): {p['T_mech']:.1f} deg C
//    - Latent Heat of Fusion:         {p['latent_heat']:.1f} J/kg
//    - Ambient Room Temp (Tamb):      {p['T_amb']:.1f} deg C
//    - Surface Convection (hConv):    {p['h_conv']:.2f} W/(m^2 K)
//    - Baseplate Clamp (hBot):        {p['h_bot']:.2f} W/(m^2 K)
//    - Surface Radiation Emissivity:  {p.get('emissivity', 0.7):.2f}
//    - Poisson's Ratio (nu):          {p['nu']:.2f}

// 4b. ULTRASONIC VIBRATION ASSISTANCE (UVA-WAAM):
//    - UVA Enabled:                   {'YES' if p.get('enable_ultrasonic', False) else 'NO'}
//    - Frequency:                     {p.get('ultrasonic_frequency', 0.0):.0f} Hz
//    - Amplitude:                     {p.get('ultrasonic_amplitude', 15.0e-6)*1e6:.1f} um
//    - Acoustic Streaming:            {'ON (kStream=' + format(p.get('ultrasonic_k_stream', 45.0), '.1f') + ' W/m/K)' if p.get('ultrasonic_streaming', False) else 'OFF'}
//    - Acoustic Heat Generation:      {'ON (eta=' + format(p.get('ultrasonic_coupling_eff', 0.15), '.2f') + ')' if p.get('ultrasonic_heat_gen', False) else 'OFF'}
//    - Acoustic Cavitation:           {'ON (threshold=' + format(p.get('ultrasonic_cav_threshold', 1.0e6)/1e6, '.1f') + ' MPa)' if p.get('ultrasonic_cavitation', False) else 'OFF'}
//    - Acoustic Momentum Transfer:    {'ON' if p.get('ultrasonic_momentum', False) else 'OFF'}
//    - Blaha Softening Factor:        {1.0 - min(0.3, p.get('ultrasonic_frequency', 0.0)/100000.0):.2f} (yield stress multiplier)
//
// 5. DISCRETIZATION & SOLVER:
//    - Mesh Mode:                     {p.get('mesh_source', 'parametric')}
//    - Substrate Elements (Nx,Ny,Nz): {sub_mesh_str}
//    - Deposit Elements (Nx,Ny,Nz):   {dep_mesh_str}
//    - Linear Solver Backend:         {p.get('solver', 'UMFPACK')}
//    - Time Integration Scheme:       theta = {p.get('theta', 1.0)} (Backward Euler Implicit)
//    - Welding Time-Step (dtWeld):    {p['dt_weld']:.4f} s
//    - Inter-Pass Time-Step (dtWait): {p['dt_wait']:.4f} s
//    - Final Cooling Step (dtCool):   {p.get('dt_cool', 120.0):.2f} s ({p.get('n_cool_steps', 20)} steps)
//
// 6. MULTI-PHYSICS MODULES & GOVERNING TOGGLES:
//    - Surface Radiation Heat Loss:   {'ENABLED' if p.get('enable_radiation', True) else 'DISABLED'}
//    - Mechanical Model:              {'J2 THERMO-ELASTO-PLASTICITY (radial return)' if p.get('enable_j2_plasticity', True) else 'ELASTIC (no plasticity)'}
//    - Mechanics FESpace:             {'P2 (BETA with J2 -- see validation warning)' if int(p.get('mechanics_order', 1)) == 2 else 'P1 (validated)'}
//    - Equilibrium Solver:            {'INCREMENTAL NEWTON-RAPHSON' if p.get('mech_max_newton_iter', 12) > 1 else 'SINGLE DIRECT SOLVE (staggered)'}
//    - Tangent Stiffness:             {'CONSISTENT (elastic predictor + plastic tangent)' if p.get('mech_use_consistent_tangent', True) else 'ELASTIC (modified Newton)'}
//    - Solve Cadence:                 {p.get('mech_solve_cadence', 'interpass').upper()} ({p.get('mech_solve_every_n_weld', 5)} weld steps)
//    - Springback (unclamp) Solve:    {'ENABLED (dynamic_clamping + springback_solve)' if p.get('springback_solve', False) and p.get('dynamic_clamping', True) else 'DISABLED'}
//    - Support Boundary Condition:    {p.get('mechanical_bc', 'isostatic').upper()}
//    - Boiling Temp Clamping:         {'ENABLED' if p.get('enable_boiling_cap', False) else 'DISABLED (Raw Unclamped Physics)'}
//    - Cauchy Equilibrium Stresses:  DIRECT CAUCHY EQUILIBRIUM SOLVE (div sigma = 0 enforced weakly)
//
// 7. ARTIFACT DESTINATIONS:
//    - Visual VTU / PVD Results:      {visdir_norm}
//    - Tabular Data & Metrics:        {outdir_norm}
//    - Native Console Log:            {outdir_norm}sim.log
// ================================================================================
   === END PARAMETER SPECIFICATION (block closes here) === */

{self.solver_load}
load "iovtk"

string outdir = "{outdir_norm}";
{mpi_rank_dirs}string visdir = outdir + "visual_outputs/";
{_mkdir_cmd}

// === GEOMETRY & LAYER REMELTING FUSION ===
real LxW        = {p['lx']};
real LyBase     = {p['ly_base']};
real HzBase     = {p['hz_base']};
real TyDep      = {p['ty_dep']};
real hBead1     = {h_bead_first};
real remeltRatio= {remelt_ratio};
real hBeadSub   = {h_bead_subseq};
int  Nlayers    = {p['n_layers']};
real HzDep      = (Nlayers <= 1) ? (Nlayers * hBead1) : (hBead1 + (Nlayers - 1) * hBeadSub);
real HzTot      = HzBase + HzDep;
real yDepCentre = LyBase/2.;
real yDepLeft   = yDepCentre - TyDep/2.;
real yDepRight  = yDepCentre + TyDep/2.;

// === PROCESS & HEAT INPUT ===
real Pweld  = {Pweld};
real vscan  = {p['v_scan']};
real tPass  = LxW/vscan;
real tWait  = {p['t_wait']};
// Inter-pass cooling control: 0 = fixed dwell (t_wait), 1 = iterative cooldown
// to interpass_target_temp_C.
int ipassTargetMode = {ipass_target_mode};
// Net Linear Heat Input:   {h_net_j_mm:.2f} J/mm ({h_net_j_mm/1000.0:.3f} kJ/mm)
// Gross Linear Heat Input: {h_gross_j_mm:.2f} J/mm ({h_gross_j_mm/1000.0:.3f} kJ/mm)
// Net Thermal Arc Power:   {p_net:.1f} W ({p_net/1000.0:.2f} kW)
// Volumetric Energy Density: {e_vol:.2f} J/mm^3

// === WIRE FEEDSTOCK & MASS CONSERVATION ===
real dWire       = {d_wire_m:.6e}; // Wire diameter [m] ({d_wire_mm:.2f} mm)
real vWire       = {v_wire_m_s:.6e}; // Wire feed speed [m/s] ({v_wire_m_min:.2f} m/min)
real aWire       = {a_wire_m2:.6e};  // Wire cross-sectional area [m^2] ({a_wire_mm2:.3f} mm^2)
real QwireVol    = {q_wire_vol_m3_s:.6e}; // Volumetric feed rate [m^3/s]
real mDepRate    = {m_dep_rate_kg_s:.6e}; // Mass deposition rate [kg/s] ({m_dep_kg_h:.2f} kg/h)
real aBeadTheo   = {a_bead_theo_m2:.6e};  // Theoretical bead area [m^2] ({a_bead_theo_mm2:.2f} mm^2)

// === MATERIAL CONSTANTS & PHYSICAL LIMITS ===
real Tsol   = {p['T_sol']};
real Tliq   = {p['T_liq']};
real Tboil  = {t_boil};
real Tamb   = {p['T_amb']};
real rhoBase= {rho_base};
real rhoDep = {rho_dep};
real hConv  = {p['h_conv']};
real hBot   = {p['h_bot']};
real nuS    = {p['nu']};
real Tmech  = {p['T_mech']};
real sigYieldBase = {sig_yield_base};
real sigYieldDep  = {sig_yield_dep};

// === TIMESTEP ===
real dtWeld = {p['dt_weld']};
real dtWait = {p['dt_wait']};

// === G-CODE TOOLPATH READER ===
int nPts = 0;
real[int] tpT(1), tpX(1), tpY(1), tpZ(1), tpP(1);
bool tpZMatchWarned = false;
// Per-layer point windows inside the toolpath (index of first/last point whose
// z equals the layer mid-plane). -1 = no point matched that layer.
int[int] laySta(max(Nlayers, 1)), layEnd(max(Nlayers, 1));
{{
    string tpFile = outdir + "toolpath.txt";
    int tpRc = system("test -f '" + tpFile + "' 2>/dev/null");
    if(tpRc == 0){{
        ifstream fgcode(tpFile);
        if(fgcode.good()){{
            fgcode >> nPts;
            if(nPts > 0) {{
                tpT.resize(nPts); tpX.resize(nPts); tpY.resize(nPts); tpZ.resize(nPts); tpP.resize(nPts);
                for(int i=0; i<nPts; ++i){{
                    fgcode >> tpT[i] >> tpX[i] >> tpY[i] >> tpZ[i] >> tpP[i];
                }}
                cout << " [G-CODE] Successfully loaded toolpath array with " << nPts << " coordinates." << endl;
            }} else {{
                cout << " [G-CODE] toolpath.txt present but empty (nPts=0). Falling back to linear scan assumption." << endl;
            }}
        }}
    }} else {{
        cout << " [G-CODE] No toolpath.txt found. Falling back to linear scan assumption." << endl;
    }}
}}

// === LAYER-BUCKETED TOOLPATH WINDOWS ===
// The toolpath points carry the slicer's layer z (= plate top + (k+0.5)*h for
// a part placed by the mesher/slicer placement rule). Bucket them per layer by
// matching z to this run's layer mid-plane. The weld loop then maps tLocal
// (0..tPassLayer) onto THAT layer's own window, so the torch lookup no longer
// rides a global clock: the previous global-clock version drifted by
// (t_wait - slicer_dwell) per layer. Measured on a 10-layer letter-Z build:
// the solver clock exited the program at layer 6, layers 6-10 ran their whole
// pass with pState=0 (zero arc power), and layers 1-5 only partially aligned.
{{
    for(int l=0; l<Nlayers; ++l){{
        laySta[l] = -1; layEnd[l] = -1;
        real zc = (l == 0) ? (HzBase + 0.5*hBead1)
                           : (HzBase + hBead1 + (l-1)*hBeadSub + 0.5*hBeadSub);
        real hL = (l == 0) ? hBead1 : hBeadSub;
        real tolL = 0.45 * max(1.e-9, hL);
        for(int j=0; j<nPts; ++j){{
            if(abs(tpZ[j] - zc) <= tolL){{
                if(laySta[l] < 0) laySta[l] = j;
                layEnd[l] = j;
            }}
        }}
    }}
    int nLayMatched = 0;
    for(int l=0; l<Nlayers; ++l) if(laySta[l] >= 0) nLayMatched++;
    if(nPts > 0){{
        cout << " [G-CODE] Layer-bucketed toolpath windows: " << nLayMatched
             << " of " << Nlayers << " layers matched by z." << endl;
        if(nLayMatched < Nlayers){{
            cout << " [WARN] " << (Nlayers - nLayMatched)
                 << " layer(s) have no toolpath points at their mid-plane z -- "
                 << "those layers fall back to the global clock. Usually a frame "
                 << "mismatch: re-slice with the current slicer (part must be "
                 << "placed on the plate at z=hz_base)." << endl;
        }}
    }}
}}

// === PER-LAYER PASS TIME READER ===
int nLayerTimes = 0;
real[int] layerPassTimes(1);
{{
    string ltFile = outdir + "layer_pass_times.txt";
    int ltRc = system("test -f '" + ltFile + "' 2>/dev/null");
    if(ltRc == 0){{
        ifstream flt(ltFile);
        if(flt.good()){{
            flt >> nLayerTimes;
            if(nLayerTimes > 0) {{
                layerPassTimes.resize(nLayerTimes);
                for(int i=0; i<nLayerTimes; ++i){{
                    int layIdx;
                    flt >> layIdx >> layerPassTimes[i];
                }}
                cout << " [G-CODE] Loaded " << nLayerTimes << " per-layer pass times." << endl;
            }}
        }}
    }} else {{
        cout << " [G-CODE] No layer_pass_times.txt found. Using constant pass time." << endl;
    }}
}}


cout << "==========================================" << endl;
cout << " T-JOINT AS WAAM PROCESS (LAYER REMELTING FUSION)" << endl;
cout << " Substrate: " << LxW*1000. << "x" << LyBase*1000. << "x" << HzBase*1000. << "mm" << endl;
cout << " Deposit: " << Nlayers << " layers | Layer 1: " << hBead1*1000. << "mm, Subseq: " << hBeadSub*1000. << "mm (" << remeltRatio*100. << "% fusion)" << endl;
cout << " Total Build Height: " << HzDep*1000. << "mm" << endl;
cout << " Width: " << TyDep*1000. << "mm  centred at y=" << yDepCentre*1000. << "mm" << endl;
cout << " Wire Feedstock: d=" << dWire*1000. << "mm | WFS=" << vWire*60. << "m/min | Deposition=" << mDepRate*3600. << "kg/h" << endl;
cout << " P=" << Pweld << "W  v=" << vscan*1000. << "mm/s" << endl;
cout << " tPass=" << tPass << "s  tWait=" << tWait << "s  Total=" << Nlayers*(tPass+tWait) << "s" << endl;
cout << "==========================================" << endl;

// === MATERIAL FUNCTIONS ===
{mat_funcs}
// Hcp(T, zv) is emitted with the material functions above: an EXACT
// trapezoid integral of the same piecewise-linear Cp tables the solver
// uses (HmatBase/HmatZ*). The previous numeric midpoint quadrature (Hseg)
// aliased the near-vertical latent-spike edges by bin alignment; it is
// gone. Energy audit and the solver's secant-Cp mass term now share this
// one function, so the discrete balance and the true-enthalpy accounting
// cannot disagree except by solver tolerance.

// === MESH ===
{"// Using external mesh file" if p['mesh_source'] != 'parametric' else ""}
{mesh_block_str}

// === ADAPTIVE TIME-STEP CONTROLLER ===
// The explicit stability/accuracy limit for a diffusion problem is the diffusion
// (Fourier) number Fo = alpha*dt/dx^2, where alpha = k/(rho*Cp). Limiting Fo is
// how an Abaqus-like *HEAT TRANSFER step with automatic time incrementation
// behaves: dt is derived from the material diffusivity and the mesh, so accuracy
// no longer depends on the user guessing dt_weld correctly.
int useAdaptiveDt = {1 if str(p.get('adaptive_dt','off')).lower() not in ('off','0','false','none') else 0};
real foTarget = {float(p.get('adaptive_fo_target', 0.45))};
real dtMinA = {float(p.get('adaptive_dt_min', 1.0e-4))};
real dtMaxA = {float(p.get('adaptive_dt_max', 5.0))};

// Smallest characteristic element length, measured over all six edges of every
// tetrahedron. This is the real h that limits diffusion accuracy, and measuring
// it (rather than assuming a value from the parametric Nx/Ny/Nz) keeps the
// limiter correct for imported CAD meshes too. For a structured box mesh the
// minimum edge equals the smallest cell dimension, which is the expected answer.
real hMinMesh = 1.e9;
for(int ie=0; ie<Th.nt; ie++){{
    // Element vertices via the mesh connectivity table Th[ie][a]. (An earlier
    // revision used ie+a*Th.nv, which is vector-fespace dof arithmetic, not
    // mesh connectivity: it measured edges between unrelated vertices, found a
    // phantom h_min of 3e-9 m, and pinned the adaptive dt at its floor, so the
    // runaway guard tripped after 800 steps having simulated 0.08 s while
    // reporting success. Element birth for the source mask had nothing to do
    // with it; the ruler was broken, not the mesh.)
    real hloc = 1.e9;
    for(int a=0; a<4; a++)
        for(int b=a+1; b<4; b++){{
            real dv = Th(Th[ie][a]).z - Th(Th[ie][b]).z;
            real dh = Th(Th[ie][a]).y - Th(Th[ie][b]).y;
            real dd = Th(Th[ie][a]).x - Th(Th[ie][b]).x;
            real elen = sqrt(dv*dv + dh*dh + dd*dd);
            if(elen > 1.e-12 && elen < hloc) hloc = elen;
        }}
    if(hloc < hMinMesh) hMinMesh = hloc;
}}
real hGlobMesh = max(hMinMesh, 1.e-9);
real RpoolAct = {r_activate};
int hSrcIsPrescribed = {is_prescribed};
// Resolution gate for prescribed-T pools: the cosine-squared profile is only
// sampled correctly when several nodes fall inside R_activate. On a coarse
// mesh the torch path threads between nodes (hit-or-miss imposition) and the
// hard-ball alternative Gibbs-rings instead. Both failure modes are silent
// energy errors, so under-resolution aborts loudly rather than reporting.
if(hSrcIsPrescribed && RpoolAct < 2.*hGlobMesh){{
    cout << "  [FATAL] R_activate (" << RpoolAct*1000. << " mm) < 2x min cell ("
         << hGlobMesh*1000. << " mm). The pool profile cannot be sampled: "
         << "refine the mesh or widen R_activate. Aborting rather than "
         << "depositing hit-or-miss energy." << endl;
    exit(1);
}}
if(useAdaptiveDt == 1)
    cout << " [ADAPTIVE DT] enabled | h_min=" << hGlobMesh*1000. << " mm | Fo_target=" << foTarget
         << " | dt in [" << dtMinA << ", " << dtMaxA << "] s" << endl;
else
    cout << " [ADAPTIVE DT] off (fixed dt schedules)" << endl;

// Stable/accurate dt for the current thermal state: dt = Fo*dx^2/alpha, using
// the WORST (smallest diffusivity, i.e. lowest k and highest heat capacity) that
// is actually present, so the limit is conservative everywhere on the mesh.
// NOTE: defined further below, after the thermal fields are declared, because it
// reads psiActive / kEff / CpEff / Temp0.

// === FE SPACES ===
fespace Sh(Th, P1);
fespace Vh(Th, [{mech_fe},{mech_fe},{mech_fe}]);
// Mechanical state space: P1 normally, P2 with mechanics_order=2 (C3D10-like:
// warpage-grade bending without P1-tet locking). Thermal fields stay P1 under
// both orders -- heat is smooth and the P1 audit closes to <1% -- so every
// Th.nv-indexed thermal loop is untouched by the order switch. Only the
// mechanical loops below use dof-indexed (order-agnostic) access.
fespace Mh(Th, {mech_fe});
fespace Ph(Th, P0);

Sh Temp, Temp0, dTemp;
Sh TempCorrPrev; // corrector scratch (previous pass); never a physics state
// === ENTHALPY-FORM THERMAL STATE ===
// The thermal unknown is H (true volumetric enthalpy above Tamb, J/m^3),
// not T. The mass term is rho*(H-H0)/dt -- EXACT for any dt -- and T is
// recovered with the exact inverse TfromH(H). The old temperature form used
// Cp(T_start) as the mass coefficient, which silently skips the fusion
// latent whenever one step crosses the Cp spike: each hot node here carries
// ~460 mm^3 of material, so ~20 nodes crossing the band hid ~20 kJ of
// latent heat as a "numerical residual" (-8% audit on the 2-layer case,
// -40% at dt/4: the error GROWS with finer dt, the signature of a lagged
// latent). Enthalpy form closes the audit at ANY dt by construction.
Sh Hfield, H0, Hiter;
Sh CpLin;        // local dH/dT slope used to linearize T(H) in conduction/Robin
Sh invCpLin;     // 1/CpLin as a FIELD: T(H) linearization uses multiplication,
                 // never field division (FreeFEM-safe in varfs)
Sh TbF;          // Temp - Hiter*invCpLin: the known part of the T(H) split
                 // (FreeFEM varfs cannot differentiate dx(trial*field))
Sh HboilN;       // Hcp(Tboil, z): enthalpy at the boiling cap (per material)
Sh kEff, CpEff, rhoEff, Tsource;
Sh QacouField;    // UVA acoustic dissipation field
Sh sigUVA;        // UVA stress-relief field
Sh reliefFrac;    // UVA relief fraction field
// Lumped nodal volumes (row sums of the P1 mass matrix). The mesh never changes,
// so these are computed once and reused wherever a nodal quantity must be
// summed as an energy. Forgetting the volume weights energy density as energy:
// the prescribed-T audit once reported 5.9e8 kJ imposed for a 60 kJ process.
varf vMassLump(u, v) = int3d(Th)(u*v);
Sh psiActive, Tpeak, hSurf, TempVis;
// Element-birth mask for the heat source (see below). P0, i.e. one value per
// element: an element contributes source energy only when ALL of its nodes are
// active. Nodal `* psiActive` in the source formulae is not enough, because the
// load vector integrates over whole elements and P1 assembly smears an active
// node's source onto the quiet vertices of every tet it touches; the quiet
// clamp then destroys that energy (measured: 82% of injected on the CAS case).
Ph srcMask, bornMask;
matrix MmassLump = vMassLump(Sh, Sh);
real[int] onesLump(Th.nv); onesLump = 1.;
real[int] lumpVol = MmassLump*onesLump;
Sh dTdt;        // Instantaneous cooling rate field [C/s]
Sh TdotCool;    // Maximum transient cooling rate at solidification front [C/s]
Sh dt85Track;   // Elapsed continuous cooling time between 800C and 500C [s]
Sh tEnter800;   // Entry timestamp for 800C boundary [s]
Sh nReheat;     // Multi-pass thermal reheat cycle counter
Sh SDAS, dt85;
Sh fFerrite, fBainite, fMartensite, fPearlite, HVmap;

Vh [ux,uy,uz];
Vh [vx,vy,vz];
Mh dispM, sigM, sigXX;

{mech_stage}

// === INITIAL CONDITIONS ===
Temp  = Tamb;
Temp0 = Tamb;
Hfield = 0.;   // H is measured from Tamb: zero == ambient
H0 = 0.;
Hiter = 0.;
CpLin = 1.;
invCpLin = 1.;
for(int iv=0; iv<Th.nv; iv++) HboilN[][iv] = Hcp(Tboil, Th(iv).z);
Tpeak = Tamb;
TdotCool  = 0.;
dt85Track = 0.;
tEnter800 = -1.;
nReheat   = 0.;
ux[]  = 0.;

for(int iv=0; iv<Th.nv; iv++){{
    real zv = Th(iv).z;
    if(zv <= HzBase+1.e-6){{
        psiActive[][iv] = 1.;
        rhoEff[][iv] = rhoBase;
        kEff[][iv]  = kMat(Tamb, zv);
        CpEff[][iv] = CpMat(Tamb, zv);
    }} else {{
        psiActive[][iv] = 0.;
        rhoEff[][iv] = rhoDep;
        // Quiet elements: insulate (k x 1e-4) but KEEP full thermal mass.
        // The old version scaled Cp too, which left diffusivity alpha=k/rhoCp
        // unchanged (still conducting) while making the mass 1e-4x, so any
        // psi-interpolation leak spiked the temperature and only the Tboil
        // cap kept the run alive.
        kEff[][iv]  = kMat(Tamb, zv)*1.e-4;
        CpEff[][iv] = CpMat(Tamb, zv);
    }}
    hSurf[][iv] = hConv;
}}
// Element-birth mask, initial state. P0 assignment evaluates the P1 field at
// the element centroid, i.e. the mean of its four nodal values; for a binary
// field `> 0.999` is true iff ALL four nodes are active. Front-straddling
// elements therefore contribute no source until their last node activates.
{srcmask_init}
real bornFloor = 1.e-5;
bornMask = max(srcMask, bornFloor);

// Boiling-cap energy accounting [J]: excess enthalpy deleted by the Tboil clip
real EcapJ = 0.;

// UVA global state
real PacouSeenMax = 0.;
real betaUS = 0.22;
real maxBaselineStress = 0.;
real maxBaselineDisp = 0.;
// Energy-balance audit accumulators [J] (printed in SIMULATION SUMMARY)
real EarcJ = 0.;   // arc energy ACTUALLY injected: sum(int Tsource dV * dt)
bool srcFidelityWarned = false;
// Tolerance for the discrete-injection fidelity check: the assembled source
// load vector must reproduce Pweld within (1 - source_fidelity_floor). The
// rescale below is exact either way; the warning is about MESH QUALITY (an
// under-resolved spot is the signature of a quadrature-dependent deposit).
real srcFidTol = {round(max(1.e-6, 1.0 - float(p.get('source_fidelity_floor', 0.90))), 6)};
real EintJ = 0.;   // intended arc energy: sum(Pweld * pState * dt)
real ElossJ = 0.;  // surface losses: clamp (label 1) + convection/radiation (labels 2,3)
real EquietJ = 0.;
                   // reaches quiet nodes, the Tamb clamp is removed, and conducted
                   // preheat stays in the stored enthalpy. Kept (as zero) so the
                   // audit schema and checkpoints stay stable.
real EprescJ = 0.; // enthalpy imposed by prescribed-T activation (nodal, exact).
real ErectJ = 0.; // energy added by the Tamb floor (Gibbs-undershoot rectifier).
                   // Counted as a source in the audit so the balance closes honestly.
// Per-step rectifier trace. Off by default; enable to see which steps undershoot.
bool rectDebug = {str(bool(p.get("thermal_rect_debug", False))).lower()};


// === VARIATIONAL FORMS ===
real thetaT = {p['theta']};
real kLiqF = {float(p.get('k_liq_factor', 1.0))}; // liquid-state k enhancement (1.0 = off; 2-5 mimics convective pool transport)
real dt     = dtWeld;
int nThermalCorr = {n_thermal_corr};
real corrTol = {corr_tol};

// Linearized temperature about the current iterate:
//   Tlin(H) = TbF + H*invCpLin,  TbF = Temp - Hiter*invCpLin (a known FIELD)
// At the fixed point H == Hiter this equals TfromH(H) exactly, so the
// converged equation is the true enthalpy balance, not an approximation.
// CpLin = max(CpMat(Temp),1) is the local dH/dT, so the flat latent plateau
// (Cp ~ 4500) correctly damps T against H changes instead of oscillating.
// NOTE: the gradient term is split by the product rule -- theta*div(invCpLin*
// Hfield)*dTemp expands into (a) invCpLin*dx(Hfield)*dx(dTemp) and (b)
// Hfield*dx(invCpLin)*dx(dTemp) -- because this FreeFEM version cannot
// differentiate dx(Hfield*field) (product of trial and field) inside a varf
// ("EvaluableWithOutStack" assertion). Both split terms assemble fine.

varf aThermal(Hfield, dTemp) =
    // FULLY LUMPED operator (volume mass + boundary Robin): every consistent
    // P1 mass matrix in this system has positive off-diagonals -- the volume
    // mass between hot/quiet nodes and, worse, the boundary convection/
    // radiation mass across the sharp psiActive activation front (measured on
    // the 2-layer benchmark: +1.4e-05 coupling from a quiet node to its hot
    // active neighbor, comparable to the whole row diagonal). M/dt + K then
    // stops being an M-matrix: the discrete maximum principle fails and the
    // implicit step undershoots. Measured with consistent matrices: Tmin =
    // -1927 C and -30087 C during weld steps, and the Temp=max(Temp,Tamb)
    // floor rectifier re-injected 24.9 kJ -- 39% of the 63.4 kJ arc input --
    // while stored enthalpy read 114% of energy in. With qfV1lump (volume)
    // and qf1pTlump (boundary faces) the operator is an M-matrix by
    // construction: T stays between min(Tamb, T_old) and the source-driven
    // maximum. Row sums are preserved exactly (verified on the production tet
    // mesh), so the energy audit quadrature is unchanged.
    //
    // ENTHALPY FORM: the unknown is Hfield (true volumetric enthalpy above
    // Tamb), so the mass term rho*(H-H0)/dt is exact at any dt. Conduction
    // and Robin act on the LINEARIZED T(H) (macro above), implicit in H via
    // 1/CpLin -- at convergence TlinEx == TfromH(Hfield) exactly.
    // MASS: no bornMask here, deliberately. The mask changes per step as the
    // front advances; masking the mass gives front nodes a partial volume on
    // early steps while the final stored-enthalpy audit counts their full
    // volume, so the per-step balance cannot telescope to the final state
    // (measured: +770..1030 W phantom storage per step, -24 kJ = -17% audit
    // residual on the 2-layer case). Quiet nodes keep H == 0 exactly (no
    // source -- srcMask; no conduction -- bornMask on k; no Robin -- psiActive),
    // so their full mass contributes nothing; front nodes get their true full
    // inertia and the balance telescopes exactly.
    int3d(Th, qfV=qfV1lump)(
        rhoEff/dt * Hfield*dTemp
    )
    + int3d(Th)(
        thetaT*(kEff*bornMask)*(
            invCpLin*(dx(Hfield)*dx(dTemp)+dy(Hfield)*dy(dTemp)+dz(Hfield)*dz(dTemp))
          + Hfield*(dx(invCpLin)*dx(dTemp)+dy(invCpLin)*dy(dTemp)+dz(invCpLin)*dz(dTemp))
        )
    )
    + int2d(Th,1,qft=qf1pTlump)( hBot  * psiActive * invCpLin * Hfield*dTemp )
    + int2d(Th,2,qft=qf1pTlump)( hSurf * psiActive * invCpLin * Hfield*dTemp )
    + int2d(Th,3,qft=qf1pTlump)( hSurf * psiActive * invCpLin * Hfield*dTemp )
    + int2d(Th,4,qft=qf1pTlump)( hSurf * psiActive * invCpLin * Hfield*dTemp )
    + int2d(Th,5,qft=qf1pTlump)( hSurf * psiActive * invCpLin * Hfield*dTemp )
    + int2d(Th,6,qft=qf1pTlump)( hSurf * psiActive * invCpLin * Hfield*dTemp )
    ;

varf lThermal(Hfield, dTemp) =
    // Lumped with the SAME quadratures as aThermal (volume + boundary faces):
    // with a lumped left-hand side the right-hand side must be the lumped
    // start-of-step enthalpy, or the step does not conserve energy. The
    // explicit theta-scheme conduction term uses the EXACT start-of-step
    // temperature Temp0 (no linearization needed on a known field).
    int3d(Th, qfV=qfV1lump)(
        rhoEff/dt * H0*dTemp
    )
    + int3d(Th)(
        - thetaT*(kEff*bornMask)*(dx(TbF)*dx(dTemp)+dy(TbF)*dy(dTemp)+dz(TbF)*dz(dTemp))
        - (1.-thetaT)*(kEff*bornMask)*(
            dx(Temp0)*dx(dTemp)+dy(Temp0)*dy(dTemp)+dz(Temp0)*dz(dTemp))
      + Tsource*srcMask*dTemp
      + QacouField*dTemp
    )
    + int2d(Th,1,qft=qf1pTlump)( hBot  * psiActive * (Tamb - TbF)*dTemp )
    + int2d(Th,2,qft=qf1pTlump)( hSurf * psiActive * (Tamb - TbF)*dTemp )
    + int2d(Th,3,qft=qf1pTlump)( hSurf * psiActive * (Tamb - TbF)*dTemp )
    + int2d(Th,4,qft=qf1pTlump)( hSurf * psiActive * (Tamb - TbF)*dTemp )
    + int2d(Th,5,qft=qf1pTlump)( hSurf * psiActive * (Tamb - TbF)*dTemp )
    + int2d(Th,6,qft=qf1pTlump)( hSurf * psiActive * (Tamb - TbF)*dTemp )
    ;
// Source-only load, assembled with the SAME quadrature as lThermal. Summing it
// measures EXACTLY what the matrix deposits: sum over dofs of the load vector
// equals the volume integral under the assembly rule (partition of unity), so
// no quadrature mismatch can open between "injected" and what the solution
// actually received. Auditing int3d(Tsource*srcMask) instead disagrees with
// the assembly whenever the P0 mask jumps inside an element, which reads as
// phantom stored energy. (Measured: 15 kJ gap on the 1-layer benchmark.)
varf vSrcAudit(u, v) = int3d(Th)(Tsource*srcMask*v);

// === ADAPTIVE dt HELPER (needs the thermal fields declared above) ===
// dt = Fo*dx^2/alpha, evaluated with the WORST (smallest) diffusivity actually
// present so the limit is conservative across the whole mesh.
func real stableThermalDt(real dtCap){{
    if(useAdaptiveDt == 0) return dtCap;
    real alphaWorst = 1.e9;
    for(int iv=0; iv<Th.nv; iv++){{
        if(psiActive[][iv] < 0.5) continue;
        real zv = Th(iv).z;
        real rhoLoc = (zv <= HzBase + 1.e-6) ? rhoBase : rhoDep;
        real alphaLoc = kEff[][iv] / max(rhoLoc * CpEff[][iv], 1.e-6);
        if(alphaLoc < alphaWorst) alphaWorst = alphaLoc;
    }}
    if(alphaWorst > 1.e8) alphaWorst = 1.e-8;   // guard: no active material
    real dtStable = foTarget * hGlobMesh*hGlobMesh / alphaWorst;
    return min(max(dtStable, dtMinA), min(dtMaxA, dtCap));
}}

{self._probe_setup()}

// === OUTPUT SETUP ===
int maxPvdEntries = 30000;
real[int] pvdTimes(maxPvdEntries);
string[int] pvdFiles(maxPvdEntries);
int nPvdEntries = 0;

func int recordPvd(real curTime, string curFile) {{
    if (nPvdEntries < maxPvdEntries) {{
        pvdTimes[nPvdEntries] = curTime;
        pvdFiles[nPvdEntries] = curFile;
        nPvdEntries++;
    }}
    ofstream pv(visdir + "waam.pvd");
    pv << "<?xml version='1.0'?>" << endl;
    pv << "<VTKFile type='Collection' version='0.1'>" << endl;
    pv << "  <Collection>" << endl;
    for(int ip = 0; ip < nPvdEntries; ip++) {{
        pv << "    <DataSet timestep='" << pvdTimes[ip] << "' file='" << pvdFiles[ip] << "'/>" << endl;
    }}
    pv << "  </Collection>" << endl;
    pv << "</VTKFile>" << endl;
    return 0;
}}
{{
    ofstream f(outdir+"waam_data.csv");
    f<<"time_s,layer,phase,xTorch_mm,yTorch_mm,zTorch_mm,Tmax_C,Tpeak_max_C,HV_layer"<<endl;
}}

int frame = 0;

// === RESTART / CHECKPOINT ===
{self._restart_block()}

// === DEPOSITION LOOP ===
cout << " === WAAM DEPOSITION ===" << endl;
real t = 0.;
int histCounter = 0;   // drives probe_interval; monotonic across all phases
// Apply a resumed checkpoint to the loop counters (fields are already restored).
if(resumeOk == 1){{
    t = ckptTime;
    frame = ckptFrame;
    histCounter = ckptHist;
    EarcJ = ckptEarc; EintJ = ckptEint; ElossJ = ckptEloss;
    EquietJ = ckptEquiet; EcapJ = ckptEcap; EprescJ = ckptEpresc;
}}

for(int iL=0; iL<Nlayers; iL++){{
    // Skip layers already completed in a previous (interrupted) run.
    if(resumeOk == 1 && iL < resumeFromLayer) continue;
    real zLayBot = (iL == 0) ? HzBase : (HzBase + hBead1 + (iL-1)*hBeadSub);
    real zLayH   = (iL == 0) ? hBead1 : hBeadSub;
    real zLayTop = zLayBot + zLayH;
    real zLayMid = zLayBot + zLayH/2.;

    cout << endl;
    cout << "--------------------------------------------------------------------------------" << endl;
    cout << "--- Layer " << iL+1 << "/" << Nlayers
         << "  z=[" << zLayBot*1000. << "," << zLayTop*1000. << "]mm (dz=" << zLayH*1000. << "mm) ---" << endl;
    cout << "--------------------------------------------------------------------------------" << endl;

    // WELDING PASS
    // Use per-layer pass time from toolpath data when available (accounts for
    // varying layer perimeters). Fall back to constant tPass for linear scan.
    real tPassLayer = (nPts > 0 && nLayerTimes > 0 && iL < nLayerTimes) ? layerPassTimes[iL] : tPass;
    real dtMaxTravel = max(0.01, 0.5 * max({_af}, 1.e-3) / max(vscan, 1.e-4));
    int minSteps = max(15, int(tPassLayer / dtMaxTravel + 0.5));
    int NweldSteps = max(minSteps, int(tPassLayer/dtWeld + 0.5));
    dt = tPassLayer / real(NweldSteps);

    // With adaptive_dt on, dt is re-derived from the stability limit every step
    // and the loop advances by accumulating tLocal; with it off, dt stays
    // tPassLayer/NweldSteps and tLocal = ws*dt exactly as before, so the default
    // run is bit-identical to the fixed-step implementation.
    real tLocal = 0.;
    int ws = 0;
    int maxWeldAcc = 20*max(NweldSteps, 1) + 200;   // runaway guard
    bool isBidi = {str(p.get("deposition_pattern", "bidirectional").lower() == "bidirectional").lower()};
    real xTorch = (isBidi && (iL % 2 == 1)) ? LxW : 0.0;
    real yTorch = yDepCentre;
    real zTorch = zLayMid;
    real pState = 1.0;
    real uDirX = (isBidi && (iL % 2 == 1)) ? -1.0 : 1.0;
    real uDirY = 0.0;
    real uDirZ = 0.0;

    while(tLocal < tPassLayer - 1.e-9 && ws < maxWeldAcc){{
        ws++;
        if(useAdaptiveDt == 1){{
            real dtLeft = tPassLayer - tLocal;
            // Two independent CAPS on dt, take the smaller:
            //  (1) diffusion accuracy: dt <= Fo*h^2/alpha  (stableThermalDt)
            //  (2) moving-source resolution: the torch must not advance more than
            //      ~1/8 of the source width per step, otherwise the arc energy is
            //      smeared over far less travel than intended and the energy-audit
            //      fidelity collapses (measured: 49.9 kJ -> 20.6 kJ injected).
            // srcWidth is the transverse size of the selected heat source.
            real dtDiff = stableThermalDt(dtLeft);
            real wSrc = min(max({src_width}, 1.e-4), LxW/4.);
            real dtSrc = min(wSrc / max({src_travel_frac_fmt}*vscan, 1.e-9), dtLeft);
            dt = min(dtDiff, dtSrc);
            if(dt < 1.e-9) dt = dtLeft;
            tLocal += dt;
        }} else {{
            tLocal = real(ws)*dt;
        }}
        if(dt < 1.e-12) dt = max(tPassLayer - tLocal, 1.e-12);
        xTorch = (isBidi && (iL % 2 == 1)) ? max(0., min(LxW, LxW - vscan*tLocal)) : max(0., min(LxW, vscan*tLocal));
        yTorch = yDepCentre;
        zTorch = zLayMid;
        pState = 1.0;
        uDirX = (isBidi && (iL % 2 == 1)) ? -1.0 : 1.0;
        uDirY = 0.0;
        uDirZ = 0.0;
        
        // G-Code Override: drive the torch from the sliced toolpath.
        if(nPts > 0){{
            if(iL < Nlayers && laySta[iL] >= 0){{
                // Layer-bucketed lookup: this layer's OWN window is
                // [tpT[j0], tpT[j1]]. tLocal (0..tPassLayer) maps onto it 1:1
                // because layer_pass_times holds exactly the within-layer
                // weld+rapid time the toolpath clock accumulated. Interpass
                // dwell/t_wait differences can no longer drift the phase.
                int j0 = laySta[iL]; int j1 = layEnd[iL];
                real tWin = tpT[j1] - tpT[j0];
                real tGcode = tpT[j0] + min(tLocal, max(tWin, 0.));
                bool inWindow = (tLocal <= tWin + 1.e-9);
                int idx1 = j0; int idx2 = min(j0+1, j1);
                for(int i=j0; i<j1; ++i){{
                    if(tGcode >= tpT[i] && tGcode <= tpT[i+1]){{ idx1=i; idx2=i+1; break; }}
                }}
                real dtG = tpT[idx2] - tpT[idx1];
                real wG = (dtG > 1e-9) ? (tGcode - tpT[idx1]) / dtG : 0.0;
                xTorch = tpX[idx1] * (1.-wG) + tpX[idx2] * wG;
                yTorch = tpY[idx1] * (1.-wG) + tpY[idx2] * wG;
                zTorch = tpZ[idx1] * (1.-wG) + tpZ[idx2] * wG;
                real dxM = tpX[idx2] - tpX[idx1];
                real dyM = tpY[idx2] - tpY[idx1];
                real dzM = tpZ[idx2] - tpZ[idx1];
                real lenM = sqrt(dxM*dxM + dyM*dyM + dzM*dzM);
                if(lenM > 1e-9){{ uDirX = dxM/lenM; uDirY = dyM/lenM; uDirZ = dzM/lenM; }}
                // Arc state of the move ENDING at idx2: the file stores every
                // point with the state of the move that produced it, so the
                // segment [tpT[idx2-1], tpT[idx2]] is a weld iff tpP[idx2] > 0.
                pState = inWindow ? ((tpP[idx2] > 0) ? 1.0 : 0.0) : 0.0;
            }} else {{
                // Legacy fallback: toolpath z doesn't match this run's layer
                // mid-plane (pre-placement files). Keep the old global-clock
                // lookup and say so loudly once.
                if(!tpZMatchWarned){{
                    tpZMatchWarned = true;
                    cout << " [WARN] toolpath z matches no layer mid-plane; "
                         << "layer " << (iL+1) << " uses the legacy global-clock "
                         << "lookup (expect phase drift). Re-slice with the "
                         << "current slicer to place the part on the plate." << endl;
                }}
                real tGcode = t + tLocal;
                bool afterProgram = (tGcode > tpT[nPts-1] + 1.e-9);
                bool beforeProgram = (tGcode < tpT[0] - 1.e-9);
                tGcode = min(max(tGcode, tpT[0]), tpT[nPts-1]);
                int idx1 = 0; int idx2 = 0;
                for(int i=0; i<nPts-1; ++i){{
                    if(tGcode >= tpT[i] && tGcode <= tpT[i+1]){{
                        idx1 = i; idx2 = i+1; break;
                    }}
                }}
                if(idx1 == idx2 && idx1 == 0) idx2 = 1;

                real dtG = tpT[idx2] - tpT[idx1];
                real wG = (dtG > 1e-9) ? (tGcode - tpT[idx1]) / dtG : 0.0;
                xTorch = tpX[idx1] * (1.-wG) + tpX[idx2] * wG;
                yTorch = tpY[idx1] * (1.-wG) + tpY[idx2] * wG;
                zTorch = tpZ[idx1] * (1.-wG) + tpZ[idx2] * wG;
                real dxM = tpX[idx2] - tpX[idx1];
                real dyM = tpY[idx2] - tpY[idx1];
                real dzM = tpZ[idx2] - tpZ[idx1];
                real lenM = sqrt(dxM*dxM + dyM*dyM + dzM*dzM);
                if(lenM > 1e-9){{ uDirX = dxM/lenM; uDirY = dyM/lenM; uDirZ = dzM/lenM; }}
                pState = (afterProgram || beforeProgram) ? 0.0
                       : ((tpP[idx2] > 0) ? 1.0 : 0.0);
            }}
        }}

        // Progressive activation
        for(int iv=0; iv<Th.nv; iv++){{
            real xv=Th(iv).x; real zv=Th(iv).z; real yv=Th(iv).y;
            if({act_cond})
                psiActive[][iv] = 1.;
        }}
        // Recompute the element-birth mask after every activation update. The
        // source and its audit below must see the same front position.
        {srcmask_step}
        bornMask = max(srcMask, bornFloor);

        // Update properties
        for(int iv=0; iv<Th.nv; iv++){{
            real Tv = Temp0[][iv];
            real zv = Th(iv).z;
            real psiEff = max(psiActive[][iv], 1.e-4);
            kEff[][iv]  = kMat(Tv, zv)*psiEff*(Tv > TliqMat(zv) ? kLiqF : 1.);
            CpEff[][iv] = CpMat(Tv, zv);
            CpLin[][iv] = max(CpEff[][iv], 1.);
            invCpLin[][iv] = 1./CpLin[][iv];{rad_update}
        }}

        EintJ += Pweld * pState * dt;
        // Heat source
{source_block}
        // UVA acoustic thermal physics (heat generation, streaming, cavitation)
        {uva_thermal_block}
        // Actual energy entering the PDE this step. The P0 birth mask travels
        // with the source: front-straddling elements contribute nothing, so
        // P1 assembly cannot smear active-node energy onto quiet vertices.
        // (EintJ is the intended Pweld*dt; their ratio now honestly reports
        // birth-clipping of the source leading edge instead of quadrature
        // overshoot plus clamp destruction.)
        // Audit-by-assembly: sum the source load vector itself, so the
        // audited number uses the assembly quadrature by construction.
        // (This FreeFEM build has no .sum on real[int]; accumulate by hand.)
        real[int] fSrcAudit = vSrcAudit(0, Sh);
        real srcAuditSum = 0.;
        for(int iSrcA=0; iSrcA<fSrcAudit.n; iSrcA++) srcAuditSum += fSrcAudit[iSrcA];
        if (srcAuditSum > 1.e-6 && abs(srcAuditSum - Pweld) > Pweld * srcFidTol) {{
            // Symmetric rescale: force the DISCRETE injected energy to Pweld.
            // Under-shoot (birth-clipping) was already corrected; over-shoot
            // (assembly quadrature of an under-resolved spot, e.g. a fixed
            // 5 mm Gaussian on a ~9 mm cell mesh) is corrected the same way so
            // the arc never injects more than the intended Pweld.
            if (!srcFidelityWarned) {{
                srcFidelityWarned = true;
                cout << " [WARN] Heat-source injection quadrature deviates "
                     << (srcAuditSum / Pweld - 1.) * 100.
                     << "% from Pweld on this mesh; rescaling to exactly Pweld. "
                     << "Refine the mesh or use auto-sized goldak for a "
                     << "mesh-independent spot." << endl;
            }}
            real qScale = Pweld / srcAuditSum;
            Tsource = Tsource * qScale;
            srcAuditSum = Pweld;
        }}
        EarcJ += dt * srcAuditSum;

        // Solve, with iterate-to-convergence corrector passes. kEff/CpEff/hrad
        // are evaluated from the START-of-step temperature, so when a step jumps
        // hundreds of K (arc birth, pool-hold imposition) the lagged properties
        // -- above all the lagged radiation coefficient on a T^4 law --
        // systematically under-count losses and overheat (measured +35% missing
        // energy on an aluminium pool-hold case with a single pass). Each
        // corrector re-evaluates properties at the latest Temp and re-solves,
        // stopping when the max nodal change falls under corrTol or after
        // nThermalCorr total passes. The source, audit and all downstream
        // bookkeeping run once, on the converged field.
        // thermal_correctors=1 preserves the legacy single-pass behaviour.
        Hiter[] = Hfield[];
        for(int iv=0; iv<Th.nv; iv++) TbF[][iv] = Temp[][iv] - Hiter[][iv]*invCpLin[][iv];
        matrix MT = aThermal(Sh,Sh);
        real[int] fT = lThermal(0,Sh);
        set(MT, solver={self.solver_kw});
        Hfield[] = MT^-1*fT;
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
        for(int corrPass=1; corrPass<nThermalCorr; corrPass++){{
            for(int iv=0; iv<Th.nv; iv++){{
                real Tv = Temp[][iv];
                real zv = Th(iv).z;
                real psiEff = max(psiActive[][iv], 1.e-4);
                kEff[][iv]  = kMat(Tv, zv)*psiEff*(Tv > TliqMat(zv) ? kLiqF : 1.);
                CpEff[][iv] = CpMat(Tv, zv);
                CpLin[][iv] = max(CpEff[][iv], 1.);
                invCpLin[][iv] = 1./CpLin[][iv];{rad_update}
            }}
            Hiter[] = Hfield[];
            for(int iv=0; iv<Th.nv; iv++) TbF[][iv] = Temp[][iv] - Hiter[][iv]*invCpLin[][iv];
            MT = aThermal(Sh,Sh);
            fT = lThermal(0,Sh);
            set(MT, solver={self.solver_kw});
            TempCorrPrev[] = Temp[];
            Hfield[] = MT^-1*fT;
            for(int iv=0; iv<Th.nv; iv++)
                Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
            // Max nodal change vs the previous pass: convergence measure.
            // (Temp0 is the step's anchor and must not be touched here.)
            real corrMax = 0.;
            for(int iv=0; iv<Th.nv; iv++){{
                real dTc = abs(Temp[][iv] - TempCorrPrev[][iv]);
                if(dTc > corrMax) corrMax = dTc;
            }}
            if(corrMax < corrTol) break;
        }}
        // The floor always applies, so its energy is always counted; rectDebug
        // only controls the per-step print. Counting it conditionally while
        // applying it unconditionally once hid 8.8 kJ on a prescribed-T run.
        // Lumped-nodal sum, NOT int3d: the floor acts exactly where the field
        // oscillates (Gibbs undershoot = high-frequency), and consistent vs
        // lumped quadrature disagree most there. Every other nodal term
        // (EprescJ) is lumped; mixing them opens a phantom gap.
        // Lumped-nodal sum (same quadrature basis as EprescJ; see the
        // weld-loop site for the rationale).
        {{
            real eRectStep = 0.;
            for(int iv=0; iv<Th.nv; iv++){{
                real Hr = Hfield[][iv];
                if(Hr < 0.) eRectStep += lumpVol[iv]*rhoEff[][iv]*(-Hr);
            }}
            ErectJ += eRectStep;
        }}
        if(rectDebug && ErectJ > 0.)
            cout << "    [RECT] dt=" << dt << " ErectJ=" << ErectJ
                 << " Tmin=" << Temp[].min << endl;
        Hfield = max(Hfield, 0.);
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
        // Quiet (not-yet-deposited) nodes held at ambient: P1 source
        // interpolation smears arc energy across shared interface elements,
        // which otherwise superheats quiet nodes to 3000+ C.
        // Enthalpy the smeared P1 source has just parked on not-yet-deposited
        // (quiet) nodes, BEFORE they are clamped back to Tamb. This is an
        // energy FLOW: it must be multiplied by dt like every other per-step
        // term. It used to be accumulated unweighted, so the same stored
        // enthalpy was re-counted on every timestep. Measured: EquietJ reached
        // 121.7 kJ while the arc only ever injected 79.4 kJ, which is
        // impossible for a quantity that is supposed to be a subset of the
        // injected energy, and it turned the audit residual into -142%.
        // Enthalpy sitting on not-yet-deposited (quiet) nodes, BEFORE they are
        // clamped back to Tamb, i.e. the energy the clamp is about to destroy.
        // This is a STOCK, not a flow -- exactly like the boiling-cap term
        // EcapJ, which likewise accumulates without dt -- so it carries no dt.
        // (An earlier revision multiplied it by dt, which is dimensionally
        // Joule-seconds and wrong; fluxes carry dt, destroyed stocks do not.)
        //
        // With the P0 birth mask on the source this term should stay near zero:
        // front-straddling elements receive no source energy, so P1 assembly
        // can no longer smear it onto quiet vertices. Before the mask existed
        // it reached 121.7 kJ against 79.4 kJ injected -- more destroyed than
        // ever put in, the signature of assembly smear plus conducted-in heat
        // being counted as source energy. What remains is genuinely conducted
        // heat plus numerical noise at the front, both legitimately destroyed
        // by the clamp and legitimately counted here.
        // No Tamb clamp on quiet nodes. The clamp existed to suppress the
        // 3000 C superheat that P1 assembly smeared onto quiet vertices; the P0
        // birth mask (srcMask) stops that smear at the element level, so the
        // clamp's only remaining effect was destroying legitimate conducted
        // preheat ahead of the torch. Conducted preheat is physical -- it is
        // the heat-affected zone -- and stays in the stored enthalpy, where
        // the audit counts it. (An earlier revision measured a "quiet stock"
        // with int3d(...*(1-psiActive)); that integral is a P1 ramp inside
        // front-straddling elements, so it counted a fraction of the HOT bead
        // as quiet and reported more destroyed than injected. The nodal clamp
        // destroys only nodal values, which a field-product integral cannot
        // represent. Both the clamp and that measurement are gone.)
        ElossJ += dt * (int2d(Th,1,qft=qf1pTlump)(hBot*psiActive*(Temp - Tamb))
                      + int2d(Th,2,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,3,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,4,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,5,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,6,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb)));
        // Boiling cap in H-SPACE (exact): clip the enthalpy at H(Tboil) and
        // count exactly the destroyed stock. The old T-space clip ran
        // UNCONDITIONALLY but only counted its energy when enable_boiling_cap
        // was on -- with the flag off the cap silently destroyed energy and
        // the audit read it as a numerical residual. Clipping H makes the cap
        // (and its accounting) exact at any dt, flag or no flag.
        {{
            real eCapStep = 0.;
            for(int iv=0; iv<Th.nv; iv++){{
                real Hc = Hfield[][iv] - HboilN[][iv];
                if(Hc > 0.) eCapStep += lumpVol[iv]*rhoEff[][iv]*Hc;
            }}
            EcapJ += eCapStep;
        }}
        Hfield = min(Hfield, HboilN);
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);

        // Cooling rate and thermal history tracking: dT/dt [C/s], dt85, and reheat cycles
        for(int iv=0; iv<Th.nv; iv++){{
            real Tnew = Temp[][iv];
            real Told = Temp0[][iv];
            real zv   = Th(iv).z;
            real crInst = (Told - Tnew) / max(dt, 1.e-12);
            dTdt[][iv] = -crInst;

            // 1. Solidification cooling rate [C/s] at solidification front
            if (Told >= TsolMat(zv) - 120. && Tnew <= TsolMat(zv) + 60. && crInst > 0.) {{
                if (crInst > TdotCool[][iv]) TdotCool[][iv] = crInst;
            }}
            // 2. Continuous cooling time dt85 tracking (800C -> 500C)
            if (Told >= 800. && Tnew < 800. && tEnter800[][iv] < 0.) {{
                tEnter800[][iv] = t + tLocal;
            }}
            if (tEnter800[][iv] > 0. && Told >= 500. && Tnew < 500.) {{
                real elapsed85 = (t + tLocal) - tEnter800[][iv];
                if (elapsed85 > 0.01 && (dt85Track[][iv] < 1.e-4 || elapsed85 < dt85Track[][iv])) {{
                    dt85Track[][iv] = elapsed85;
                }}
                tEnter800[][iv] = -1.;
            }}
            // 3. Multi-pass reheat cycles above transformation boundary
            if (Told < 720. && Tnew >= 720. && psiActive[][iv] > 0.5) {{
                nReheat[][iv] += 1.0;
            }}
        }}

{self._prescribed_T_override() if p['heat_source'] == 'prescribed' else ''}
        // Track Tpeak on active nodes only
        for(int iv=0; iv<Th.nv; iv++){{
            if(psiActive[][iv] > 0.5){{
                Tpeak[][iv] = max(Tpeak[][iv], Temp[][iv]);
            }} else {{
                Tpeak[][iv] = Tamb;
            }}
        }}
        Temp0 = Temp;
        H0 = Hfield;
        histCounter++; writeHistory(t+tLocal, 1, iL+1, histCounter);

{self._checkpoint_call(indent=8)}

        // Save
        if(ws%{p['save_every_n_weld']}==0){{
            string num;
            if      (frame<   10) num="000"+frame;
            else if (frame<  100) num="00" +frame;
            else if (frame< 1000) num="0"  +frame;
            else                  num=""   +frame;
            for(int iv=0;iv<Th.nv;iv++)
                TempVis[][iv] = (psiActive[][iv]>0.5) ? Temp[][iv] : -1.;
            int[int] ord=[1,1,1,1,1];
            savevtk(visdir+"T_"+num+".vtu", Th,
                Temp, TempVis, psiActive, Tpeak, dTdt,
                dataname="Temperature TempC Activation Tpeak CoolingRate_C_per_s", order=ord);
            real xMidSamp = LxW / 2.0;
            real yMidSamp = yDepCentre;
            real zMidSamp = zLayMid;
            real crCur = max(abs(dTdt(xMidSamp, yMidSamp, zMidSamp)), 0.1);
            real dtC = (800.0 - 500.0) / max(crCur, 1.0);
            real fM = 0., fB = 0., fF = 1., fP = 0.;
            if(dtC < 5.0) {{ fM = 1.0; fF = 0.; }}
            else if(dtC < 20.0) {{ fB = (dtC-5.0)/15.0; fM = 1.0 - fB; fF = 0.; }}
            else {{ fP = min(0.4, 0.1 + 0.005*(dtC-20.0)); fF = 1.0 - fP; }}
            real hvCur = {hv_formula_code};

            recordPvd(t+tLocal, "T_"+num+".vtu");
            {{
                ofstream cv(outdir+"waam_data.csv",append);
                cv<<t+tLocal<<","<<iL+1<<",WELDING,"
                  <<xTorch*1000.<<","<<yTorch*1000.<<","<<zTorch*1000.<<","
                  <<Temp[].max<<","<<Tpeak[].max<<","<<hvCur<<endl;
            }}
            cout<<"  L"<<iL+1<<" ws="<<ws
                <<"  t="<<t+tLocal<<"s"
                <<"  x="<<xTorch*1000.<<"mm"
                <<"  y="<<yTorch*1000.<<"mm"
                <<"  z="<<zTorch*1000.<<"mm"
                <<"  Tmax="<<Temp[].max<<"C"<<endl;
            frame++;
        }}
{inweld_mech}
    }}
    // The runaway guard (ws < maxWeldAcc) must never trip silently: tripping
    // means the pass did not finish, usually because dt collapsed to its floor
    // (a broken h_min once did exactly this: 800 steps simulated 0.08 s while
    // the run reported success and deposited ~0.1 kJ). Fail loudly instead.
    if(ws >= maxWeldAcc && tLocal < tPassLayer - 1.e-9){{
        cout << "  [FATAL] weld-step runaway guard tripped on layer " << iL+1
             << ": " << ws << " steps covered only " << tLocal << " s of "
             << tPassLayer << " s. dt has collapsed (check h_min and the "
             << "adaptive controller). The pass did NOT finish; aborting rather "
             << "than reporting a partial deposition as a result." << endl;
        exit(1);
    }}
    // Consolidate full layer: all nodes in the deposited layer are activated.
    // The plate below is already permanently active (see the initial
    // conditions), so sweeping everything up to zLayTop is correct and also
    // re-affirms the substrate.
    real zConsol = (nPts > 0) ? max(zLayTop, zTorch + zLayH/2.) : zLayTop;
    for(int iv=0; iv<Th.nv; iv++){{
        if(Th(iv).z <= zConsol + 1.e-5)
            psiActive[][iv] = 1.;
    }}
    {srcmask_step}
    bornMask = max(srcMask, bornFloor);
    t += tPassLayer;

    // INTER-PASS COOLING
    // The first seconds after arc extinction carry the entire post-peak
    // transient (Fo = alpha*dt/dx^2 ~ 1.3 for a flat 10 s step). A geometric
    // ramp 0.5/1/2/5 s resolves it, then coarse dtWait finishes the dwell.
    //
    // Two modes:
    //   time   - cool for exactly t_wait (legacy; the dwell is whatever the user
    //            guessed, so inter-pass temperature is uncontrolled).
    //   target - cool until the part's peak temperature falls to
    //            interpass_target_temp_C, then stop. This is the Ansys
    //            "Iterative Cooldown" idea and is what makes inter-pass
    //            temperature a controlled process variable rather than an
    //            emergent one.
    Tsource = 0.;
    real[int] dtRampW = [0.5, 1., 2., 5.];
    real tWaitRem = tWait;
    real iPassTarget = {ipass_target};
    int iw = 0;
    real ipassPrevPeak = Temp[].max;
    int ipassIters = 0;
    int ipassConverged = 0;
    while(tWaitRem > 1.e-9 || (ipassTargetMode == 1 && ipassConverged == 0)){{
        real dtStep;
        if(ipassTargetMode == 1 && ipassIters > 0){{
            // Steady part of target mode: uniform step, so the iteration count
            // maps cleanly onto cooling time.
            dtStep = {ipass_dt};
        }} else {{
            dtStep = (iw < dtRampW.n) ? min(dtRampW[iw], tWaitRem) : min(dtWait, tWaitRem);
        }}
        if(ipassTargetMode == 1 && tWaitRem <= 1.e-9) dtStep = min({ipass_dt}, 1.e12);
        dt = dtStep;
        for(int iv=0; iv<Th.nv; iv++){{
            real Tv = Temp0[][iv];
            real zv = Th(iv).z;
            real psiEff = max(psiActive[][iv], 1.e-4);
            kEff[][iv]  = kMat(Tv, zv)*psiEff*(Tv > TliqMat(zv) ? kLiqF : 1.);
            CpEff[][iv] = CpMat(Tv, zv);
            CpLin[][iv] = max(CpEff[][iv], 1.);
            invCpLin[][iv] = 1./CpLin[][iv];{rad_update}
        }}
        Hiter[] = Hfield[];
        for(int iv=0; iv<Th.nv; iv++) TbF[][iv] = Temp[][iv] - Hiter[][iv]*invCpLin[][iv];
        matrix MT = aThermal(Sh,Sh);
        real[int] fT = lThermal(0,Sh);
        set(MT, solver={self.solver_kw});
        Hfield[] = MT^-1*fT;
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
        // The floor always applies, so its energy is always counted; rectDebug
        // only controls the per-step print. Counting it conditionally while
        // applying it unconditionally once hid 8.8 kJ on a prescribed-T run.
        // Lumped-nodal sum, NOT int3d: the floor acts exactly where the field
        // oscillates (Gibbs undershoot = high-frequency), and consistent vs
        // lumped quadrature disagree most there. Every other nodal term
        // (EprescJ) is lumped; mixing them opens a phantom gap.
        // Lumped-nodal sum (same quadrature basis as EprescJ; see the
        // weld-loop site for the rationale).
        {{
            real eRectStep = 0.;
            for(int iv=0; iv<Th.nv; iv++){{
                real Hr = Hfield[][iv];
                if(Hr < 0.) eRectStep += lumpVol[iv]*rhoEff[][iv]*(-Hr);
            }}
            ErectJ += eRectStep;
        }}
        if(rectDebug && ErectJ > 0.)
            cout << "    [RECT] dt=" << dt << " ErectJ=" << ErectJ
                 << " Tmin=" << Temp[].min << endl;
        Hfield = max(Hfield, 0.);
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
        // Boiling cap in H-space, exact (see the weld-loop site).
        {{
            real eCapStep = 0.;
            for(int iv=0; iv<Th.nv; iv++){{
                real Hc = Hfield[][iv] - HboilN[][iv];
                if(Hc > 0.) eCapStep += lumpVol[iv]*rhoEff[][iv]*Hc;
            }}
            EcapJ += eCapStep;
        }}
        Hfield = min(Hfield, HboilN);
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);

        ElossJ += dt * (int2d(Th,1,qft=qf1pTlump)(hBot*psiActive*(Temp - Tamb))
                      + int2d(Th,2,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,3,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,4,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,5,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,6,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb)));
        for(int iv=0; iv<Th.nv; iv++){{
            real Tnew = Temp[][iv];
            real Told = Temp0[][iv];
            real crInst = (Told - Tnew) / max(dt, 1.e-12);
            dTdt[][iv] = -crInst;
            if (Told >= 800. && Tnew < 800. && tEnter800[][iv] < 0.) {{
                tEnter800[][iv] = t;
            }}
            if (tEnter800[][iv] > 0. && Told >= 500. && Tnew < 500.) {{
                real elapsed85 = t - tEnter800[][iv];
                if (elapsed85 > 0.01 && (dt85Track[][iv] < 1.e-4 || elapsed85 < dt85Track[][iv])) {{
                    dt85Track[][iv] = elapsed85;
                }}
                tEnter800[][iv] = -1.;
            }}
            if(psiActive[][iv] > 0.5){{
                Tpeak[][iv] = max(Tpeak[][iv], Temp[][iv]);
            }} else {{
                Tpeak[][iv] = Tamb;
            }}
        }}
        Temp0 = Temp;
        H0 = Hfield;
        histCounter++; writeHistory(t+dt, 2, iL+1, histCounter);

        // Save each dwell step to VTU and PVD
        {{
            string num;
            if      (frame<   10) num="000"+frame;
            else if (frame<  100) num="00" +frame;
            else if (frame< 1000) num="0"  +frame;
            else                  num=""   +frame;
            for(int iv=0;iv<Th.nv;iv++)
                TempVis[][iv] = (psiActive[][iv]>0.5) ? Temp[][iv] : -1.;
            int[int] ord=[1,1,1,1,1];
            savevtk(visdir+"T_"+num+".vtu", Th,
                Temp, TempVis, psiActive, Tpeak, dTdt,
                dataname="Temperature TempC Activation Tpeak CoolingRate_C_per_s", order=ord);
            recordPvd(t, "T_"+num+".vtu");
            frame++;
        }}

        t += dt;
        tWaitRem -= dt;
        iw++;
        ipassIters++;

        // Target-mode convergence: stop once the peak falls under the target, or
        // once the peak stops changing appreciably (matching the Ansys
        // "Convergence Threshold" idea), or when the iteration cap is reached.
        if(ipassTargetMode == 1){{
            real ipassPeak = Temp[].max;
            real ipassRel = 100.*abs(ipassPeak - ipassPrevPeak)/max(abs(ipassPrevPeak), 1.);
            ipassPrevPeak = ipassPeak;
            if(ipassPeak <= iPassTarget){{
                ipassConverged = 1;
                cout << "  [INTERPASS] layer " << iL+1 << ": reached target "
                     << iPassTarget << " C (peak " << ipassPeak << " C) after "
                     << ipassIters << " steps, " << t << " s total" << endl;
            }} else if(ipassRel < {ipass_tol_pct} && ipassIters > 1){{
                ipassConverged = 1;
                cout << "  [INTERPASS] layer " << iL+1 << ": converged, peak change "
                     << ipassRel << "% < " << {ipass_tol_pct}
                     << "% at peak " << ipassPeak << " C" << endl;
            }} else if(ipassIters >= {ipass_max_iters}){{
                cout << "  [WARN] Inter-pass cooling hit the iteration cap ("
                     << ipassIters << ") with peak " << ipassPeak
                     << " C still above target " << iPassTarget << " C." << endl;
                ipassConverged = 1;
            }}
        }}
    }}

    // Inter-pass mechanical equilibrium solve
    {{
        real xMidSamp = LxW / 2.0;
        real yMidSamp = yDepCentre;
        real zMidSamp = zLayMid;
        real crCur = max(abs(dTdt(xMidSamp, yMidSamp, zMidSamp)), 0.1);
        real dtC = (800.0 - 500.0) / max(crCur, 1.0);
        real fM = 0., fB = 0., fF = 1., fP = 0.;
        if(dtC < 5.0) {{ fM = 1.0; fF = 0.; }}
        else if(dtC < 20.0) {{ fB = (dtC-5.0)/15.0; fM = 1.0 - fB; fF = 0.; }}
        else {{ fP = min(0.4, 0.1 + 0.005*(dtC-20.0)); fF = 1.0 - fP; }}
        real hvCur = {hv_formula_code};

        {self._mechanical_stage_solve() if p.get('enable_mechanical', True) else ''}
        cout << "  -> Inter-pass cool:            Tmax=" << Temp[].max << "C  t=" << t << "s" << endl;
        cout << endl;
        frame++;
    }}

{self._checkpoint_call_layer()}
}}

// === FINAL COOLING ===
cout << endl;
cout << "================================================================================" << endl;
cout << " === FINAL COOLING STAGE ===" << endl;
cout << "================================================================================" << endl;
{{
    real dtCool = {p['dt_cool']};
    int nCoolSave = {p['save_every_n_cool']};
    // Ramped final cooling: the first post-build seconds decide the last
    // layer's dt85; a flat 120 s step steps straight over them.
    real[int] dtRampC = [1., 2., 5., 10., 30., 60.];
    real tCoolRem = dtCool * {p['n_cool_steps']};
    Tsource = 0.;
    int ic = 0;
    while(tCoolRem > 1.e-9){{
        dt = (ic < dtRampC.n) ? min(dtRampC[ic], tCoolRem) : min(dtCool, tCoolRem);
        for(int iv=0; iv<Th.nv; iv++){{
            real Tv = Temp0[][iv];
            real zv = Th(iv).z;
            real psiEff = max(psiActive[][iv], 1.e-4);
            kEff[][iv]  = kMat(Tv, zv)*psiEff*(Tv > TliqMat(zv) ? kLiqF : 1.);
            CpEff[][iv] = CpMat(Tv, zv);
            CpLin[][iv] = max(CpEff[][iv], 1.);
            invCpLin[][iv] = 1./CpLin[][iv];{rad_update}
        }}
        Hiter[] = Hfield[];
        for(int iv=0; iv<Th.nv; iv++) TbF[][iv] = Temp[][iv] - Hiter[][iv]*invCpLin[][iv];
        matrix MT = aThermal(Sh,Sh);
        real[int] fT = lThermal(0,Sh);
        set(MT, solver={self.solver_kw});
        Hfield[] = MT^-1*fT;
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
        // The floor always applies, so its energy is always counted; rectDebug
        // only controls the per-step print. Counting it conditionally while
        // applying it unconditionally once hid 8.8 kJ on a prescribed-T run.
        // Lumped-nodal sum, NOT int3d: the floor acts exactly where the field
        // oscillates (Gibbs undershoot = high-frequency), and consistent vs
        // lumped quadrature disagree most there. Every other nodal term
        // (EprescJ) is lumped; mixing them opens a phantom gap.
        // Lumped-nodal sum (same quadrature basis as EprescJ; see the
        // weld-loop site for the rationale).
        {{
            real eRectStep = 0.;
            for(int iv=0; iv<Th.nv; iv++){{
                real Hr = Hfield[][iv];
                if(Hr < 0.) eRectStep += lumpVol[iv]*rhoEff[][iv]*(-Hr);
            }}
            ErectJ += eRectStep;
        }}
        if(rectDebug && ErectJ > 0.)
            cout << "    [RECT] dt=" << dt << " ErectJ=" << ErectJ
                 << " Tmin=" << Temp[].min << endl;
        Hfield = max(Hfield, 0.);
        for(int iv=0; iv<Th.nv; iv++)
            Temp[][iv] = TfromH(Hfield[][iv], Th(iv).z);
        // Quiet (not-yet-deposited) nodes held at ambient: P1 source
        // interpolation smears arc energy across shared interface elements,
        // which otherwise superheats quiet nodes to 3000+ C.
        // Enthalpy the smeared P1 source has just parked on not-yet-deposited
        // (quiet) nodes, BEFORE they are clamped back to Tamb. This is an
        // energy FLOW: it must be multiplied by dt like every other per-step
        // term. It used to be accumulated unweighted, so the same stored
        // enthalpy was re-counted on every timestep. Measured: EquietJ reached
        // 121.7 kJ while the arc only ever injected 79.4 kJ, which is
        // impossible for a quantity that is supposed to be a subset of the
        // injected energy, and it turned the audit residual into -142%.
        // Enthalpy sitting on not-yet-deposited (quiet) nodes, BEFORE they are
        // clamped back to Tamb, i.e. the energy the clamp is about to destroy.
        // This is a STOCK, not a flow -- exactly like the boiling-cap term
        // EcapJ, which likewise accumulates without dt -- so it carries no dt.
        // (An earlier revision multiplied it by dt, which is dimensionally
        // Joule-seconds and wrong; fluxes carry dt, destroyed stocks do not.)
        //
        // With the P0 birth mask on the source this term should stay near zero:
        // front-straddling elements receive no source energy, so P1 assembly
        // can no longer smear it onto quiet vertices. Before the mask existed
        // it reached 121.7 kJ against 79.4 kJ injected -- more destroyed than
        // ever put in, the signature of assembly smear plus conducted-in heat
        // being counted as source energy. What remains is genuinely conducted
        // heat plus numerical noise at the front, both legitimately destroyed
        // by the clamp and legitimately counted here.
        // No Tamb clamp on quiet nodes. The clamp existed to suppress the
        // 3000 C superheat that P1 assembly smeared onto quiet vertices; the P0
        // birth mask (srcMask) stops that smear at the element level, so the
        // clamp's only remaining effect was destroying legitimate conducted
        // preheat ahead of the torch. Conducted preheat is physical -- it is
        // the heat-affected zone -- and stays in the stored enthalpy, where
        // the audit counts it. (An earlier revision measured a "quiet stock"
        // with int3d(...*(1-psiActive)); that integral is a P1 ramp inside
        // front-straddling elements, so it counted a fraction of the HOT bead
        // as quiet and reported more destroyed than injected. The nodal clamp
        // destroys only nodal values, which a field-product integral cannot
        // represent. Both the clamp and that measurement are gone.)
        ElossJ += dt * (int2d(Th,1,qft=qf1pTlump)(hBot*psiActive*(Temp - Tamb))
                      + int2d(Th,2,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,3,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,4,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,5,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb))
                      + int2d(Th,6,qft=qf1pTlump)(hSurf*psiActive*(Temp - Tamb)));
        for(int iv=0; iv<Th.nv; iv++){{
            real Tnew = Temp[][iv];
            real Told = Temp0[][iv];
            real crInst = (Told - Tnew) / max(dt, 1.e-12);
            dTdt[][iv] = -crInst;
            if (Told >= 800. && Tnew < 800. && tEnter800[][iv] < 0.) {{
                tEnter800[][iv] = t;
            }}
            if (tEnter800[][iv] > 0. && Told >= 500. && Tnew < 500.) {{
                real elapsed85 = t - tEnter800[][iv];
                if (elapsed85 > 0.01 && (dt85Track[][iv] < 1.e-4 || elapsed85 < dt85Track[][iv])) {{
                    dt85Track[][iv] = elapsed85;
                }}
                tEnter800[][iv] = -1.;
            }}
            Tpeak[][iv] = max(Tpeak[][iv], Temp[][iv]);
        }}
        Temp0 = Temp;
        H0 = Hfield;
        histCounter++; writeHistory(t+dt, 3, Nlayers, histCounter);
        t += dt;
        tCoolRem -= dt;
        if(ic%nCoolSave==0){{
            string num;
            if      (frame<   10) num="000"+frame;
            else if (frame<  100) num="00" +frame;
            else if (frame< 1000) num="0"  +frame;
            else                  num=""   +frame;
            int[int] ord=[1,1,1,1,1];
            savevtk(visdir+"T_"+num+".vtu", Th,
                Temp, Temp, psiActive, Tpeak, dTdt,
                dataname="Temperature TempC Activation Tpeak CoolingRate_C_per_s", order=ord);
            recordPvd(t, "T_"+num+".vtu");
            cout<<"COOL t="<<t<<"s  Tmax="<<Temp[].max<<"C"<<endl;
            frame++;
        }}
        if(ic >= dtRampC.n && Temp[].max <= Tamb + 5.0){{
            cout << "  [COOLING] Part fully cooled to ambient room temperature (Tmax = " << Temp[].max << " C <= Tamb + 5 C). Dynamic cooldown complete at t=" << t << " s." << endl;
            break;
        }}
        ic++;
    }}
    // Honest label: the cooldown length is dt_cool * n_cool_steps by contract
    // (validate_cas_ded_dimeen26 compares it against the reference 300 s), and
    // it may be too short to reach ambient for a given part. The final
    // mechanical stage below is labelled "Room Temperature"; say so here when
    // that label is not true, instead of publishing warm-state stress as
    // cold-state residual stress.
    if(Temp[].max > Tamb + 5.0){{
        cout << "  [WARN] Final cooldown ended at Tmax=" << Temp[].max
             << " C > Tamb+5 C after " << t << " s total. The 'cold-state' "
             << "residual stress and warpage below are evaluated on a WARM "
             << "part; increase dt_cool * n_cool_steps for a true "
             << "room-temperature state." << endl;
    }}
}}

// --- Final Mechanical Solve (Post Final Cooling at Room Temperature) ---
cout << endl;
cout << "================================================================================" << endl;
cout << " === FINAL MECHANICAL STAGE (Room Temperature Residual Stress & Distortion) ===" << endl;
cout << "================================================================================" << endl;
{self._mechanical_stage_solve() if p.get('enable_mechanical', True) else ''}
{springback_stage}
cout << endl;



cout << endl;
cout << "================================================================================" << endl;
{micro_stage}
cout << " SIMULATION SUMMARY" << endl;
cout << "================================================================================" << endl;
cout << " Thermal frames saved:          " << frame << endl;
cout << " Simulated time:                " << t << " s" << endl;
cout << " Energy removed by boiling cap: " << EcapJ/1000. << " kJ"
     << " (excess enthalpy clamped at Tboil)" << endl;
cout << endl;
cout << " === ENERGY BALANCE AUDIT ===" << endl;
// EXACT discrete stored enthalpy: the solver's own lumped nodal mass weight
// (lumpVol * rhoEff -- the row sums of its mass functional, incl. porosity)
// times the H unknown it evolved. Lumped nodal sum, NOT int3d: the solver's
// mass uses qfV1lump, and the consistent quadrature of the rho*H field
// product disagrees with the lumped functional by an O(h^2) term that would
// show up as a phantom residual (the same reason ErectJ/EprescJ are nodal).
real EstoredJ = 0.;
for(int iv=0; iv<Th.nv; iv++)
    EstoredJ += lumpVol[iv] * rhoEff[][iv] * Hfield[][iv];
// The Tamb floor rectifies Gibbs undershoots (consistent mass matrix + sharp
// source) into real energy. That energy is IN the stored enthalpy, so the audit
// must count it as a source, or the balance reads phantom. It is reported as
// its own line -- not hidden inside the residual -- so a mesh or dt change that
// makes undershoots worse shows up as a number instead of a mystery.
real EresJ = EarcJ + EprescJ + ErectJ - EcapJ - ElossJ - EquietJ - EstoredJ;
cout << " Intended arc input (Pweld*dt): " << EintJ/1000. << " kJ" << endl;
cout << " Injected arc heat (int Q dV):  " << EarcJ/1000. << " kJ (100 %)"
     << "  [fidelity: " << 100.*EarcJ/max(EintJ, 1.) << " % of intended]" << endl;
cout << " Prescribed-T imposed enthalpy:" << EprescJ/1000. << " kJ" << endl;
real EauditBase = max(EarcJ + EprescJ, 1.);
cout << " Stored enthalpy (final T):    " << EstoredJ/1000. << " kJ  ("
     << 100.*EstoredJ/EauditBase << " % of energy in)" << endl;
cout << " Boiling-cap removed:          " << EcapJ/1000. << " kJ  ("
     << 100.*EcapJ/EauditBase << " %)" << endl;
cout << " Surface losses (conv+rad):    " << ElossJ/1000. << " kJ  ("
     << 100.*ElossJ/EauditBase << " %)" << endl;
cout << " Quiet-node discarded:         " << EquietJ/1000. << " kJ  ("
     << 100.*EquietJ/EauditBase << " %)" << endl;
cout << " Tamb-floor added (rectifier): " << ErectJ/1000. << " kJ  ("
     << 100.*ErectJ/EauditBase << " %)" << endl;
cout << " Residual (numerical):         " << EresJ/1000. << " kJ  ("
     << 100.*EresJ/EauditBase << " %)" << endl;

// --- Structural result validity gate ---
// The reported warpage and residual stress are only meaningful if the final
// equilibrium iteration converged. Emitting them anyway is how an unconverged
// solve silently becomes a "result" (observed: a near-rigid fixture produced a
// bogus 3.2 mm warpage and a fictitious 2.25 mm springback that still parsed
// cleanly downstream). So gate the numbers and say plainly what went wrong.
if(FinalSolidConverged == 1){{
    cout << " Final cold-state residual warpage (Uz): " << warpageClampedFinal << " mm" << endl;
    cout << " Final cold-state peak von Mises stress: " << sigMMaxClampedFinal << " MPa" << endl;
}} else {{
    cout << " Final cold-state residual warpage (Uz):   NOT REPORTED - mechanical" << endl;
    cout << "     equilibrium did NOT converge (Fresid=" << residFrozen
         << ", Dresid=" << dresFrozen << " after " << itsFrozen
         << " iterations)." << endl;
    cout << " Final cold-state peak von Mises stress: NOT REPORTED - same reason." << endl;
    cout << "     DO NOT use these fields for design decisions. Likely causes:" << endl;
    cout << "       * fixture too stiff (lower fixture_stiffness_ratio_z/xy)" << endl;
    cout << "       * insufficient iterations (raise mech_max_newton_iter)" << endl;
    cout << "       * loose tolerances (tighten mech_newton_tol / _tol_force)" << endl;
}}
cout << " ParaView PVD file:             " << visdir << "waam.pvd" << endl;
cout << " Mechanical VTU file:           " << visdir << "waam_mech.vtu" << endl;
cout << "================================================================================" << endl;

// --- MACHINE-READABLE RESULTS ---
// The post-processor must never parse the human-readable banner above. Doing so
// is how an unconverged solve still ends up in run_summary.json: the banner
// wording changed once and every extracted distortion/stress silently became
// 0.0, while an unconverged run kept matching an intermediate line and reported
// iteration error as a result. This file is the authoritative record; the
// `converged` flag travels WITH the numbers so consumers cannot miss it.
{{
    ofstream rf(outdir+"solver_results.json");
    rf << "{{";
    rf << "\\n  \\"schema\\": \\"waam-solver-results/1\\",";
    rf << "\\n  \\"mechanics_converged\\": " << (FinalSolidConverged == 1 ? "true" : "false") << ",";
    rf << "\\n  \\"newton_iterations\\": " << itsFrozen << ",";
    rf << "\\n  \\"newton_force_residual\\": " << residFrozen << ",";
    rf << "\\n  \\"newton_disp_residual\\": " << dresFrozen << ",";
    rf << "\\n  \\"sim_time_s\\": " << t << ",";
    rf << "\\n  \\"thermal_frames\\": " << frame << ",";
    rf << "\\n  \\"nlayers\\": " << Nlayers << ",";
    // Structural quantities are emitted as JSON null when unconverged, so a
    // consumer that reads the number without checking the flag still cannot
    // obtain a fabricated value.
    if(FinalSolidConverged == 1){{
        rf << "\\n  \\"peak_von_mises_MPa\\": " << sigMMaxClampedFinal << ",";
        rf << "\\n  \\"max_uz_mm\\": " << warpageClampedFinal << ",";
        rf << "\\n  \\"max_disp_mm\\": " << dispMaxClampedFinal << ",";
    }} else {{
        rf << "\\n  \\"peak_von_mises_MPa\\": null,";
        rf << "\\n  \\"max_uz_mm\\": null,";
        rf << "\\n  \\"max_disp_mm\\": null,";
    }}
    rf << "\\n  \\"energy_audit_J\\": {{";
    rf << "\\n    \\"intended_arc\\": " << EintJ << ",";
    rf << "\\n    \\"injected_arc\\": " << EarcJ << ",";
    rf << "\\n    \\"stored_enthalpy\\": " << EstoredJ << ",";
    rf << "\\n    \\"boiling_cap_removed\\": " << EcapJ << ",";
    rf << "\\n    \\"surface_losses\\": " << ElossJ << ",";
    rf << "\\n    \\"quiet_node_discarded\\": " << EquietJ << ",";
    rf << "\\n    \\"tamb_floor_added\\": " << ErectJ << ",";
    rf << "\\n    \\"prescribed_imposed\\": " << EprescJ << ",";
    rf << "\\n    \\"numerical_residual\\": " << EresJ;
    rf << "\\n  }},";
    rf << "\\n  \\"max_peak_temp_C\\": " << Tpeak[].max;
    rf << "\\n}}\\n";
}}
cout << " Machine-readable results:      " << outdir << "solver_results.json" << endl;
cout << endl;
"""
        # Lexer guard: FreeFEM 4.15 aborts (bare lex.cpp assertion) when
        # 100 '//'-opening lines pass with no intervening real code -- blank
        # lines do NOT reset the count, only code tokens do (measured: 99
        # parses, 100 aborts; 60+50blank+60 aborts; a 120-line /* */ span
        # parses as one unit). The header therefore carries its parameter spec
        # as a /* */ block. This fails the BUILD loudly instead of shipping a
        # script that dies on its first lines. Ceiling 90 for margin.
        _run = 0
        _in_block = False
        for _ln in script.split("\n"):
            _s = _ln.strip()
            if "/*" in _s:
                _in_block = True
            if _in_block:
                if "*/" in _s:
                    _in_block = False
                continue
            if _s.startswith("//"):
                _run += 1
            elif _s == "":
                pass
            else:
                _run = 0
            if _run >= 90:
                raise ValueError(
                    "emitted script has %d '//' lines with no intervening "
                    "code (FreeFEM lexer limit is <100): wrap the span in "
                    "/* */ or hoist code above it" % _run)
        return sanitize_freefem_script(script)

    def save(self, filepath: str):
        """Generate and save the .edp script to disk."""
        script = self.build()
        script = sanitize_freefem_script(script)
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='ascii', errors='ignore') as f:
            f.write(script)
        return filepath


def sanitize_freefem_script(script: str) -> str:
    """Ensure emitted FreeFEM script contains strictly valid ASCII characters."""
    subs = {
        'α': 'alpha',
        'β': 'beta',
        'γ': 'gamma',
        'δ': 'delta',
        'ε': 'epsilon',
        'θ': 'theta',
        'λ': 'lambda',
        'μ': 'u',
        'ρ': 'rho',
        'σ': 'sigma',
        'τ': 'tau',
        'φ': 'phi',
        'ω': 'omega',
        '°': ' deg',
        '±': '+-',
        '²': '^2',
        '³': '^3',
        '×': 'x',
        '·': '*',
        '—': '--',
        '–': '-',
        '’': "'",
        '‘': "'",
        '“': '"',
        '”': '"',
        '…': '...',
        '₹': 'Rs ',
        '→': '->',
        '←': '<-',
        '≤': '<=',
        '≥': '>=',
        '≠': '!=',
        '≈': '~=',
    }
    for k, v in subs.items():
        script = script.replace(k, v)
    return script.encode('ascii', errors='ignore').decode('ascii')


if __name__ == "__main__":
    from core.platform_adapter import framework_path
    params = EDPBuilder.default_params()
    builder = EDPBuilder(params)
    out = builder.save(framework_path("waam_output", "waam_generated.edp"))
    print(f"Generated: {out}")
