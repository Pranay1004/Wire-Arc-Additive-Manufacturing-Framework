"""
Material database and alloy kinetics mixin for EDPBuilder.
"""

import json
from pathlib import Path

from core.multimaterial.alloy_metallurgy import get_alloy_category, get_alloy_scheme
from .enthalpy import smooth_cp_spike, make_enthalpy_func, make_inverse_enthalpy_func


class EDPMaterialsMixin:
    """Handles alloy thermophysical properties and phase transformation kinetics."""

    def _load_db(self) -> dict:
        """Load the material database JSON, returning {} if unavailable.

        The file stores {"alloys": {...}}, so the wrapper is stripped here.
        Returning the wrapper made every _resolve_material_entry() lookup miss
        (the alloy keys live one level down), which silently degraded the
        fixture-stiffness derivation and every yield-strength lookup to the
        generic steel fallback.
        """
        try:
            db_path = Path(__file__).resolve().parents[2] / "core" / "multimaterial" / "material_database.json"
            with open(db_path) as f:
                raw = json.load(f)
            return raw.get("alloys", {}) if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _resolve_material_entry(self, mat_name: str, db: dict) -> dict:
        """Resolve alloy name against material database with alias matching.

        Returns {} when the alloy is genuinely unknown so callers fall back to
        the analytic default functions -- NEVER silently substitutes another
        alloy (the old fallback returned SS308L for ER70S-6/IN625/etc.).
        """
        if not mat_name:
            return {}
        if mat_name in db:
            return db[mat_name]

        m = str(mat_name).strip().upper()
        # Explicit alias table (upper-case keys)
        alias = {
            "ER70S-6": "ER70S-6", "ER70S6": "ER70S-6", "ER70S": "ER70S-6",
            "SG2": "ER70S-6", "E71T-1": "ER70S-6", "S355JR": "ER70S-6",
            "308L": "SS308L", "SS308L": "SS308L", "ER308L": "SS308L",
            "316L": "SS316L", "SS316L": "SS316L", "ER316L": "SS316L",
            "304": "SS304", "SS304": "SS304", "304L": "SS304", "AISI304": "SS304",
            "TI64": "Ti-6Al-4V", "TI-6AL-4V": "Ti-6Al-4V", "GRADE 5": "Ti-6Al-4V",
            "GRADE 23": "Ti-6Al-4V", "TA6V": "Ti-6Al-4V",
            "IN625": "IN625", "INCONEL 625": "IN625", "ALLOY 625": "IN625",
            "ALSI10MG": "AlSi10Mg", "AL-SI10MG": "AlSi10Mg",
            "AL1100": "Pure Al (Al1xxx)", "1100": "Pure Al (Al1xxx)",
            "PURE AL": "Pure Al (Al1xxx)",
        }
        target = alias.get(m)
        if target and target in db:
            return db[target]

        if "308" in m:
            return db.get("SS308L", {})
        if "304" in m:
            return db.get("SS304", {})
        if "316" in m:
            return db.get("SS316L", {})
        if any(k in m for k in ("TI-", "TI64", "TITANIUM", "GRADE 5", "GRADE 23", "6AL")):
            return db.get("Ti-6Al-4V", {})
        if any(k in m for k in ("IN625", "INCONEL", "HASTELLOY", "MONEL")):
            return db.get("IN625", {})
        if "ALSI10" in m:
            return db.get("AlSi10Mg", {})
        if any(k in m for k in ("AL1", "1100", "PURE AL", "ALUMIN")):
            return db.get("Pure Al (Al1xxx)", {})
        # Unknown alloy: fall back to analytic defaults (they carry the
        # correct fusion-latent Cp band), do not mislabel as 308L.
        return {}

    def _generate_interp_functions(self, mat_dict: dict, suffix: str = "") -> str:
        """Generate FreeFEM++ piecewise linear interpolation functions for an alloy."""
        if not mat_dict:
            return self._generate_default_functions(suffix=suffix)

        name = mat_dict.get("name", suffix)
        tsol = float(mat_dict.get("solidus", 1450.0))
        tliq = float(mat_dict.get("liquidus", 1520.0))
        latent = float(mat_dict.get("latent_heat", 270000.0))

        def make_pw_func(func_name: str, t_list: list, val_list: list, min_val: float = None) -> str:
            if not t_list or not val_list or len(t_list) != len(val_list):
                return ""
            out = [f"func real {func_name}(real T) {{"]
            n = len(t_list)
            for i in range(n - 1):
                t0, t1 = float(t_list[i]), float(t_list[i+1])
                v0, v1 = float(val_list[i]), float(val_list[i+1])
                if i == 0:
                    out.append(f"    if (T <= {t0:.1f}) return {v0:.6e};")
                dt = t1 - t0
                if abs(dt) < 1e-9:
                    continue
                out.append(f"    if (T <= {t1:.1f}) return {v0:.6e} + ({v1:.6e} - {v0:.6e}) * (T - {t0:.1f}) / ({dt:.6e});")
            v_last = float(val_list[-1])
            if min_val is not None:
                out.append(f"    return max({v_last:.6e}, {min_val:.6e});")
            else:
                out.append(f"    return {v_last:.6e};")
            out.append("}")
            return "\n".join(out)

        # Conductivity
        k_data = mat_dict.get("conductivity", {})
        k_func = make_pw_func(f"kMat{suffix}", k_data.get("T", []), k_data.get("k", []))
        if not k_func:
            k_func = f"""func real kMat{suffix}(real T) {{
    if (T <= 800.) return 30.0;
    return 27.0;
}}"""

        # Specific Heat. Tables encode fusion latent as a near-vertical box;
        # smooth its edges into area-preserving ramps so Picard correctors can
        # converge across the band (see smooth_cp_spike).
        cp_data = mat_dict.get("specific_heat", {})
        cp_T = list(cp_data.get("T", []))
        cp_V = list(cp_data.get("Cp", []))
        if cp_T and cp_V:
            cp_T, cp_V = smooth_cp_spike(
                cp_T, cp_V,
                delta=float(self.p.get("cp_spike_smooth_K", 2.0)))
        cp_func = make_pw_func(f"CpMat{suffix}", cp_T, cp_V)
        tamb = float(self.p.get("T_amb", 25.0))
        if not cp_func:
            # Fallback box spike with smoothed edges: ramps of width spD inside
            # the band, flat top raised so total latent is preserved exactly:
            # H*(W-d) = latent. Same regularization as smooth_cp_spike applies
            # to tabulated boxes; duplicated here because this fallback emits
            # FreeFEM directly from scalars rather than from a table.
            cp_func = f"""func real CpMat{suffix}(real T) {{
    real spD_{suffix} = min({float(self.p.get('cp_spike_smooth_K', 2.0)):.1f}, ({tliq:.1f}-{tsol:.1f})/4.);
    real spH_{suffix} = {latent:.1f}/(({tliq:.1f}-{tsol:.1f})-spD_{suffix});
    if (T <= {tsol:.1f}) return 500.0 + (650.0 - 500.0)*T/{tsol:.1f};
    if (T <= {tsol:.1f}+spD_{suffix}) return 650.0 + spH_{suffix}*(T-{tsol:.1f})/spD_{suffix};
    if (T <= {tliq:.1f}-spD_{suffix}) return 650.0 + spH_{suffix};
    if (T <= {tliq:.1f}) return 650.0 + spH_{suffix}*({tliq:.1f}-T)/spD_{suffix};
    return 800.0;
}}"""
            _spd = min(float(self.p.get("cp_spike_smooth_K", 2.0)), max((tliq - tsol) / 4.0, 1e-6))
            _sph = latent / max((tliq - tsol) - _spd, 1e-6)
            _ht, _hv = ([0.0, tsol, tsol + _spd, tliq - _spd, tliq, 3000.0],
                        [500.0, 650.0, 650.0 + _sph, 650.0 + _sph, 650.0, 800.0])
        else:
            _ht, _hv = cp_T, cp_V
        # Exact enthalpy of the SAME (smoothed) Cp table the solver uses, and
        # its exact inverse (T from H) for the enthalpy-form thermal solve.
        h_func = make_enthalpy_func(f"Hmat{suffix}", _ht, _hv, t_ref=tamb)
        ti_func = make_inverse_enthalpy_func(f"Tinv{suffix}", _ht, _hv, t_ref=tamb)

        # Thermal Expansion
        alpha_data = mat_dict.get("thermal_expansion", {})
        alpha_func = make_pw_func(f"alphaMat{suffix}", alpha_data.get("T", []), alpha_data.get("alpha", []))
        if not alpha_func:
            alpha_func = f"""func real alphaMat{suffix}(real T) {{
    if (T <= 800.) return 1.2e-5 + 0.4e-5*T/800.;
    return 1.5e-5;
}}"""

        # Young's Modulus
        e_data = mat_dict.get("youngs_modulus", {})
        e_func = make_pw_func(f"EMat{suffix}", e_data.get("T", []), e_data.get("E", []), min_val=1.0e8)
        if not e_func:
            e_func = f"""func real EMat{suffix}(real T) {{
    real ET = 200.e9;
    if (T > 600.) ET = 200.e9 - (200. - 30.)*1.e9*(T - 600.)/({tsol:.1f} - 600.);
    return max(ET, 1.e8);
}}"""

        return f"// Property functions for {name} ({suffix})\n" + "\n\n".join([k_func, cp_func, h_func, ti_func, alpha_func, e_func])

    def _material_functions(self) -> str:
        """Generate temperature-dependent material property functions for substrate and arbitrary N deposition zones."""
        p = self.p
        mat_base_name = p.get("material_base", p.get("material", "ER70S-6"))
        
        # Load database
        db_path = Path(__file__).resolve().parents[2] / "core" / "multimaterial" / "material_database.json"
        db = {}
        if db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as ff:
                    db = json.load(ff).get("alloys", {})
            except Exception:
                db = {}

        # Resolve zones list
        raw_zones = p.get("zones")
        if not raw_zones or not isinstance(raw_zones, list):
            # Fallback to legacy zonea / zoneb or single material
            za_layers = int(p.get("zonea_layers", p.get("n_layers", 10)))
            mat_za = p.get("zonea_material", p.get("material_dep", "SS308L"))
            mat_zb = p.get("zoneb_material", p.get("material_dep", "SS316L"))
            total_l = int(p.get("n_layers", 10))
            zb_layers = max(total_l - za_layers, 0)
            raw_zones = [{"layers": za_layers, "material": mat_za}]
            if zb_layers > 0:
                raw_zones.append({"layers": zb_layers, "material": mat_zb})

        # Sanitize zones
        zones = []
        for i, z in enumerate(raw_zones):
            try:
                l_count = int(z.get("layers", 1))
            except Exception:
                l_count = 1
            m_name = str(z.get("material", "ER70S-6")).strip()
            if l_count > 0:
                zones.append({"zone_idx": len(zones) + 1, "layers": l_count, "material": m_name})
        
        if not zones:
            zones = [{"zone_idx": 1, "layers": int(p.get("n_layers", 10)), "material": mat_base_name}]

        h_bead_first = float(p.get("h_bead_first", p.get("h_bead", 0.004)))
        remelt_ratio = float(p.get("remelt_ratio", 0.80))
        h_bead_subseq = float(p.get("h_bead_subseq", h_bead_first * remelt_ratio))

        lines = []
        lines.append("// ============================================================")
        lines.append("// ULTRASONIC & MULTI-MATERIAL THERMOPHYSICAL MODEL")
        zone_desc = " | ".join([f"Zone {z['zone_idx']}: {z['material']} ({z['layers']}L)" for z in zones])
        lines.append(f"// Substrate: {mat_base_name} | {zone_desc}")
        lines.append(f"// Layer 1: {h_bead_first*1000.0:.2f} mm | Subseq: {h_bead_subseq*1000.0:.2f} mm ({remelt_ratio*100.0:.0f}% fusion)")
        lines.append("// ============================================================\n")

        # 1. Generate Substrate material functions
        mat_base_data = self._resolve_material_entry(mat_base_name, db)
        if mat_base_name == "ER70S-6" and not mat_base_data:
            lines.append(self._generate_default_functions(suffix="Base"))
        else:
            lines.append(self._generate_interp_functions(mat_base_data, suffix="Base"))
        lines.append("")

        # 2. Generate Material functions for each zone
        for z in zones:
            z_idx = z["zone_idx"]
            m_name = z["material"]
            m_data = self._resolve_material_entry(m_name, db)
            lines.append(self._generate_interp_functions(m_data, suffix=f"Z{z_idx}"))
            lines.append("")

        # 3. Dynamic Dispatchers for kMat, CpMat, EMat, alphaMat, TsolMat, TliqMat
        base_tsol = float(mat_base_data.get("solidus", p.get("T_sol", 1450.0)))
        base_tliq = float(mat_base_data.get("liquidus", p.get("T_liq", 1520.0)))
        cum_layers = 0
        dispatch_k = ["func real kMat(real T, real zv) {", "    if (zv <= HzBase + 1.e-6) return kMatBase(T);"]
        dispatch_cp = ["func real CpMat(real T, real zv) {", "    if (zv <= HzBase + 1.e-6) return CpMatBase(T);"]
        # Hcp: EXACT enthalpy integral of the same Cp tables (see
        # make_enthalpy_func). Used by the energy audit AND by the solver's
        # secant-Cp mass term, so stored/imposed energy and the discrete
        # balance use one identical function -- no quadrature aliasing at the
        # latent-spike edges, no audit/solver mismatch.
        dispatch_h = ["func real Hcp(real T, real zv) {", "    if (zv <= HzBase + 1.e-6) return HmatBase(T);"]
        # TfromH: exact T(H) inverse, the solver's state recovery function.
        dispatch_ti = ["func real TfromH(real H, real zv) {", "    if (zv <= HzBase + 1.e-6) return TinvBase(H);"]
        dispatch_e = ["func real EMat(real T, real zv) {", "    if (zv <= HzBase + 1.e-6) return EMatBase(T);"]
        dispatch_alpha = ["func real alphaMat(real T, real zv) {", "    if (zv <= HzBase + 1.e-6) return alphaMatBase(T);"]
        dispatch_tsol = ["func real TsolMat(real zv) {", f"    if (zv <= HzBase + 1.e-6) return {base_tsol:.1f};"]
        dispatch_tliq = ["func real TliqMat(real zv) {", f"    if (zv <= HzBase + 1.e-6) return {base_tliq:.1f};"]

        for i, z in enumerate(zones):
            z_idx = z["zone_idx"]
            m_data = self._resolve_material_entry(z["material"], db)
            z_tsol = float(m_data.get("solidus", p.get("T_sol", 1400.0)))
            z_tliq = float(m_data.get("liquidus", p.get("T_liq", 1460.0)))
            cum_layers += z["layers"]
            if cum_layers <= 1:
                z_limit_expr = "HzBase + hBead1 + 1.e-6"
            else:
                z_limit_expr = f"HzBase + hBead1 + {cum_layers - 1}*hBeadSub + 1.e-6"
            
            if i < len(zones) - 1:
                dispatch_k.append(f"    if (zv <= {z_limit_expr}) return kMatZ{z_idx}(T);")
                dispatch_cp.append(f"    if (zv <= {z_limit_expr}) return CpMatZ{z_idx}(T);")
                dispatch_h.append(f"    if (zv <= {z_limit_expr}) return HmatZ{z_idx}(T);")
                dispatch_ti.append(f"    if (zv <= {z_limit_expr}) return TinvZ{z_idx}(H);")
                dispatch_e.append(f"    if (zv <= {z_limit_expr}) return EMatZ{z_idx}(T);")
                dispatch_alpha.append(f"    if (zv <= {z_limit_expr}) return alphaMatZ{z_idx}(T);")
                dispatch_tsol.append(f"    if (zv <= {z_limit_expr}) return {z_tsol:.1f};")
                dispatch_tliq.append(f"    if (zv <= {z_limit_expr}) return {z_tliq:.1f};")
            else:
                # Last zone covers all remaining upper domain
                dispatch_k.append(f"    return kMatZ{z_idx}(T);")
                dispatch_cp.append(f"    return CpMatZ{z_idx}(T);")
                dispatch_h.append(f"    return HmatZ{z_idx}(T);")
                dispatch_ti.append(f"    return TinvZ{z_idx}(H);")
                dispatch_e.append(f"    return EMatZ{z_idx}(T);")
                dispatch_alpha.append(f"    return alphaMatZ{z_idx}(T);")
                dispatch_tsol.append(f"    return {z_tsol:.1f};")
                dispatch_tliq.append(f"    return {z_tliq:.1f};")

        dispatch_k.append("}")
        dispatch_cp.append("}")
        dispatch_h.append("}")
        dispatch_ti.append("}")
        dispatch_e.append("}")
        dispatch_alpha.append("}")
        dispatch_tsol.append("}")
        dispatch_tliq.append("}")

        lines.extend([
            "\n".join(dispatch_k), "",
            "\n".join(dispatch_cp), "",
            "\n".join(dispatch_h), "",
            "\n".join(dispatch_ti), "",
            "\n".join(dispatch_e), "",
            "\n".join(dispatch_alpha), "",
            "\n".join(dispatch_tsol), "",
            "\n".join(dispatch_tliq), ""
        ])
        return "\n".join(lines)

    def _generate_default_functions(self, suffix: str = "") -> str:
        """Generate authentic steel material functions matching DEFAULT.edp.

        Cp carries BOTH energy sinks: the Curie/eutectoid spike (600-800 C) and
        an exact fusion-latent band [Tsol,Tliq] held at 600 + L/dT so the
        trapezoidal integral recovers base*deltaT + 270 kJ/kg exactly. The old
        version returned flat 800 above Tsol and silently dropped the entire
        latent heat of fusion (~0.27 MJ/kg).
        """
        tsol = float(self.p.get("T_sol", 1450.0))
        tliq = float(self.p.get("T_liq", 1520.0))
        spd = min(float(self.p.get("cp_spike_smooth_K", 2.0)), max((tliq - tsol) / 4.0, 1e-6))
        sph = 270000.0 / max((tliq - tsol) - spd, 1e-6)
        _ht = [0.0, 600.0, 720.0, 800.0, tsol, tsol + spd, tliq - spd, tliq, 3000.0]
        _hv = [440.0, 600.0, 5000.0, 650.0, 600.0, 600.0 + sph, 600.0 + sph, 600.0, 800.0]
        _tref = float(self.p.get("T_amb", 25.0))
        h_func = make_enthalpy_func(f"Hmat{suffix}", _ht, _hv, t_ref=_tref)
        ti_func = make_inverse_enthalpy_func(f"Tinv{suffix}", _ht, _hv, t_ref=_tref)
        return f"""// Default steel material functions (Suffix: {suffix})
func real kMat{suffix}(real T) {{
    if (T<=800.)  return 60.-(60.-38.)*T/800.;
    if (T<=Tsol)  return 38.-(38.-27.)*(T-800.)/(Tsol-800.);
    return 27.;
}}
func real CpMat{suffix}(real T) {{
    real spD = min({float(self.p.get('cp_spike_smooth_K', 2.0)):.1f}, (Tliq-Tsol)/4.);
    real spH = 270000./((Tliq-Tsol)-spD);
    if (T<=600.)  return 440.+(600.-440.)*T/600.;
    if (T<=720.)  return 600.+(5000.-600.)*(T-600.)/120.;
    if (T<=800.)  return 5000.-(5000.-650.)*(T-720.)/80.;
    if (T<=Tsol)  return 650.-(650.-600.)*(T-800.)/(Tsol-800.);
    if (T<=Tsol+spD) return 600. + spH*(T-Tsol)/spD;
    if (T<=Tliq-spD) return 600. + spH;
    if (T<=Tliq)  return 600. + spH*(Tliq-T)/spD;
    return 800.;
}}
func real alphaMat{suffix}(real T) {{
    if (T<=800.)  return 1.2e-5 + (1.6e-5-1.2e-5)*T/800.;
    return 1.5e-5;
}}
func real EMat{suffix}(real T) {{
    real ET = 210.e9;
    if(T>600.) ET = 210.e9-(210.-80.)*1.e9*(T-600.)/(Tsol-600.);
    return max(ET, 1.e8);
}}
{h_func}
{ti_func}"""


    def _get_alloy_kinetics_freefem_code(self, mat_name: str) -> str:
        """Generate FreeFEM code for alloy-specific phase transformations and Vickers hardness.

        Constants are read from material_database.json so the kinetics map and
        the per-frame HV formula stay in lock-step. Austenitic delta-ferrite is
        predicted from WRC-1992 Cr_eq/Ni_eq (FN) instead of a hardcoded 7.5-8%,
        so 308L (FN ~8.0) and 316L (FN ~5.5) separate correctly.
        """
        cat = get_alloy_category(mat_name)
        db_path = Path(__file__).resolve().parents[2] / "core" / "multimaterial" / "material_database.json"
        db = {}
        if db_path.exists():
            with open(db_path) as f:
                db = json.load(f).get("alloys", {})
        entry = self._resolve_material_entry(mat_name, db)
        hard = entry.get("hardness_coefficients", {})
        comp = entry.get("composition", {})

        if cat == "Austenitic Stainless Steel":
            # WRC-1992 ferrite number (FN) from Schaeffler-equivalents
            cr_eq = comp.get("Cr", 0.0) + comp.get("Mo", 0.0) + 1.5 * comp.get("Si", 0.0)
            ni_eq = comp.get("Ni", 0.0) + 30.0 * comp.get("C", 0.0) + 0.5 * comp.get("Mn", 0.0)
            ratio = cr_eq / max(ni_eq, 1e-9)
            fn = min(12.0, max(3.0, 4.0 + 10.0 * (ratio - 1.4)))
            f_delta = fn / 100.0
            hv_g = float(hard.get("HV_austenite", 185))
            hv_d = float(hard.get("HV_delta_ferrite", 210))
            hv_blend = (1.0 - f_delta) * hv_g + f_delta * hv_d
            return f"""
        // {mat_name} kinetics: austenite matrix + retained delta-ferrite (WRC-1992 FN = {fn:.1f})
        fFerrite[][iv]    = {1.0 - f_delta:.4f}; // slot 1: gamma austenite
        fBainite[][iv]    = {f_delta:.4f};       // slot 2: skeletal delta-ferrite
        fMartensite[][iv] = 0.000;               // slot 3: sigma phase (suppressed)
        fPearlite[][iv]   = 0.000;               // slot 4: -
        // Hall-Petch sub-grain cell boundary strengthening on top of the two-phase blend
        HVmap[][iv] = {hv_blend:.2f} + 35.0 / sqrt(max(SDAS[][iv], 1.0));
"""

        elif cat == "Carbon Steel":
            # Low-carbon (ER70S-6 etc.): diffusional partition by dt85 with
            # athermal martensite on the fast side. Slot meanings:
            # 1=ferrite 2=pearlite(shifted to slot 2 marker) ... use slot map:
            #   slot1=ferrite, slot2=bainite, slot3=martensite, slot4=pearlite
            hv_f = float(hard.get("HV_ferrite", 140))
            hv_p = float(hard.get("HV_pearlite", 175))
            hv_b = float(hard.get("HV_bainite", 280))
            hv_m = float(hard.get("HV_martensite", 400))
            return f"""
        // {mat_name} (Carbon Steel) kinetics: dt85-partition ferrite/bainite/martensite
        real fMcs = 0.; real fBcs = 0.; real fFcs = 0.; real fPcs = 0.;
        if(dtC < 1.0)      {{ fMcs = 0.80; fBcs = 0.15; fFcs = 0.03; fPcs = 0.02; }}
        else if(dtC < 5.0) {{ fMcs = 0.25; fBcs = 0.55; fFcs = 0.15; fPcs = 0.05; }}
        else if(dtC < 20.) {{ fMcs = 0.05; fBcs = 0.30; fFcs = 0.45; fPcs = 0.20; }}
        else               {{ fMcs = 0.00; fBcs = 0.05; fFcs = 0.65; fPcs = 0.30; }}
        fFerrite[][iv]    = fFcs; // slot 1: proeutectoid/ACF ferrite
        fBainite[][iv]    = fBcs; // slot 2: bainite
        fMartensite[][iv] = fMcs; // slot 3: martensite (Ms = 475 C, KM athermal)
        fPearlite[][iv]   = fPcs; // slot 4: pearlite
        HVmap[][iv] = fFcs*{hv_f:.1f} + fPcs*{hv_p:.1f} + fBcs*{hv_b:.1f} + fMcs*{hv_m:.1f};
"""

        elif cat == "Nickel Superalloy":
            # IN625: single-phase FCC gamma, no allotropic transformation.
            # Slot map: slot1=gamma matrix, slot4=terminal Laves/NbC eutectic.
            hv_g = float(hard.get("HV_gamma_matrix", 230))
            return f"""
        // {mat_name} (Nickel Superalloy) kinetics: FCC gamma matrix + Laves eutectic
        fFerrite[][iv]    = 0.960; // slot 1: gamma (Ni-Cr-Mo-Nb) matrix
        fBainite[][iv]    = 0.000; // slot 2: -
        fMartensite[][iv] = 0.000; // slot 3: none (no martensite in FCC Ni alloy)
        fPearlite[][iv]   = 0.040; // slot 4: terminal Laves/NbC eutectic (Scheil Nb segregation)
        HVmap[][iv] = {hv_g:.1f} + 40.0 / sqrt(max(SDAS[][iv], 1.0));
"""

        elif cat == "Titanium Alloy":
            # Ti-6Al-4V: beta-transus CCT (BOR). Slot map:
            # slot1=prior-beta/colony-alpha, slot2=basketweave alpha+beta,
            # slot3=acicular alpha-prime, slot4=retained beta.
            hv_ap = float(hard.get("HV_martensite_alpha_prime", 420))
            hv_ab = float(hard.get("HV_alpha_beta", 340))
            hv_b = float(hard.get("HV_beta", 300))
            return f"""
        // {mat_name} kinetics: beta-transus continuous cooling transformation (BOR CCT)
        if(crEff > 410.0){{
            fFerrite[][iv]    = 0.00; // slot 1: prior-beta / colony alpha
            fBainite[][iv]    = 0.00; // slot 2: transformed-alpha basketweave
            fMartensite[][iv] = 0.95; // slot 3: acicular alpha-prime martensite
            fPearlite[][iv]   = 0.05; // slot 4: retained beta
        }} else if(crEff > 20.0){{
            real fWid = (crEff - 20.0) / 390.0;
            fFerrite[][iv]    = 0.00;
            fBainite[][iv]    = 0.90 * (1.0 - fWid);
            fMartensite[][iv] = 0.90 * fWid;
            fPearlite[][iv]   = 0.10;
        }} else {{
            fFerrite[][iv]    = 0.85;
            fBainite[][iv]    = 0.05;
            fMartensite[][iv] = 0.00;
            fPearlite[][iv]   = 0.10;
        }}
        HVmap[][iv] = fMartensite[][iv]*{hv_ap:.1f}
                    + (fFerrite[][iv] + fBainite[][iv])*{hv_ab:.1f}
                    + fPearlite[][iv]*{hv_b:.1f};
"""

        elif "Aluminium" in cat:
            if "AlSi" in mat_name or "10Mg" in mat_name:
                # AlSi10Mg: near-eutectic Al-Si; slot1=alpha-Al, slot2=eutectic Si.
                # SDAS-linked as-built hardness, softened by reheat loops.
                hv_ab = float(hard.get("HV_as_built", 105))
                return f"""
        // {mat_name} kinetics: alpha-Al + eutectic Si network (non-heat-treatable as-built)
        fFerrite[][iv]    = 0.880; // slot 1: primary alpha-Al
        fBainite[][iv]    = 0.120; // slot 2: eutectic Si / Mg2Si
        fMartensite[][iv] = 0.000; // slot 3: -
        fPearlite[][iv]   = 0.000; // slot 4: -
        real annealFactorAS = max(0.70, 1.0 - 0.05 * min(nReheat[][iv], 6.0));
        HVmap[][iv] = ({hv_ab:.1f} + 25.0 / sqrt(max(SDAS[][iv], 1.0))) * annealFactorAS;
"""
            # Commercially pure aluminium (Al1xxx / Al1100): single-phase FCC
            return """
        // Pure Aluminium (Al1xxx / Al1100) Kinetics: Single-phase FCC alpha-Al matrix
        fFerrite[][iv]    = 0.995; // slot 1: primary alpha-Al matrix
        fBainite[][iv]    = 0.005; // slot 2: dispersed FeAl3/AlFeSi intermetallics
        fMartensite[][iv] = 0.000; // slot 3: -
        fPearlite[][iv]   = 0.000; // slot 4: -
        real hvAsBuilt = 26.0 + 15.0 / sqrt(max(SDAS[][iv], 1.0));
        real annealFactor = max(0.85, 1.0 - 0.04 * min(nReheat[][iv], 4.0));
        HVmap[][iv] = max(24.0, min(50.0, hvAsBuilt * annealFactor));
"""

        # Unknown category: austenitic fallback (SS308L/SS316L family)
        return """
        // Default kinetics (austenitic stainless fallback)
        fFerrite[][iv]    = 0.930;
        fBainite[][iv]    = 0.070;
        fMartensite[][iv] = 0.000;
        fPearlite[][iv]   = 0.000;
        HVmap[][iv] = 185.0 + 35.0 / sqrt(max(SDAS[][iv], 1.0));
"""

