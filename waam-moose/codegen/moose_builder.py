#!/usr/bin/env python3
"""moose_builder.py  WAAM MOOSE input builder (the `.i` twin of edp_builder.py).

Same architecture rules as the FreeFEM builder: consumes a run directory
produced by the FreeFEM lane (`FreeFEM/parameters.json`, `FreeFEM/toolpath.txt`,
`FreeFEM/layer_pass_times.txt`, medit mesh), reuses `edp_builder` as the
single source of truth for parameter validation, Goldak auto-sizing, the
latent-cp smoothing (`smooth_cp_spike`) and the split-epsilon rule, then
emits the MOOSE artifact set:

    <run>/moose/waam_moose.i         the MOOSE input (reviewable gold artifact)
    <run>/moose/waam_moose.i.meta    parameter/toolpath/mesh hashes (backend=moose)
    <run>/moose/mesh.exo             mesh converted by mesh/medit_to_exodus.py

The generated `.i` is bit-compatible with the verified app classes:
WAAMToolpathUO (ledger + queries), WAAMActivationAux (psi/fa at timestep_begin),
WAAMGoldakKernel (un-gated source), WAAMBoilingCapKernel + WAAMCapPower (the
FreeFEM Tboil clip as a smooth evaporation sink with audited removal),
WAAMActivationMaterial, WAAMRobinBC, WAAMEnergyAuditUO(+PP),
explicit `TimeSequenceStepper` carrying the FreeFEM step times (weld steps at
`tPass/NweldSteps`, dwell staircase 0.5/1/2/5 then dt_wait, final cooling ramp
1/2/5/10/30/60 then dt_cool) so the energy audit closes on the 714.514 kJ
baseline. Runtime parity items that live in the app, not here, are the
`[MOOSE-BUILDER]` warnings channel's job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import os

_HERE = Path(__file__).resolve().parent          # WAAM-MOOSE/codegen
_MOOSE_ROOT = _HERE.parent                       # WAAM-MOOSE
_MOOSE_HOME = Path(os.environ.get("WAAM_MOOSE_HOME", _MOOSE_ROOT))

if str(_MOOSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOOSE_ROOT))

from codegen.edp_builder import EDPBuilder, smooth_cp_spike  # noqa: E402

SIGMA_SB = 5.67e-8  # Stefan-Boltzmann [W/m^2/K^4] (FreeFEM hardcodes the same)
Z_ACT_FRAC = 0.85   # FreeFEM activation half-height is max(cG, 0.85*h_layer)


def _fmt(v: float) -> str:
    return f"{v:.10g}"


def _fmt_list(values) -> str:
    """Space-separated list of floats for a MOOSE std::vector<Real> parameter."""
    return " ".join(_fmt(float(v)) for v in values)


class BuilderWarn:
    """Warnings channel (`[MOOSE-BUILDER] ...`), mirrors edp_builder style."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def warn(self, msg: str) -> None:
        self.lines.append(f"[MOOSE-BUILDER] {msg}")

    def block(self) -> str:
        return "\n".join("# " + w for w in self.lines) if self.lines else "# none"


def freefem_step_times(p: dict, layer_pass_times: list[float]) -> list[float]:
    """Exact port of the generated program's clock (adaptive_dt OFF, time-mode
    dwell). Weld: per layer N=max(int(tPass/dt_weld+0.5),1), dt=tPass/N, step
    ends at layer_start+k*dt. Dwell: 0.5/1/2/5 then min(dt_wait, rem).
    Final: 1/2/5/10/30/60 then min(dt_cool, rem) for dt_cool*n_cool_steps."""
    times: list[float] = []
    t = 0.0
    for lp in layer_pass_times:
        n = max(int(lp / p["dt_weld"] + 0.5), 1)
        dtl = lp / n
        k = 0
        while k * dtl < lp - 1.0e-9:
            k += 1
            times.append(t + k * dtl)
        t += lp
        rem = float(p["t_wait"])
        iw = 0
        ramp = [0.5, 1.0, 2.0, 5.0]
        while rem > 1.0e-9:
            dt = min(ramp[iw], rem) if iw < len(ramp) else min(p["dt_wait"], rem)
            t += dt
            times.append(t)
            rem -= dt
            iw += 1
    rem = float(p["dt_cool"]) * int(p["n_cool_steps"])
    ic = 0
    rampc = [1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
    while rem > 1.0e-9:
        dt = min(rampc[ic], rem) if ic < len(rampc) else min(p["dt_cool"], rem)
        t += dt
        times.append(t)
        rem -= dt
        ic += 1
    return times


def trap_latent_cp(sT: list[float], sV: list[float]) -> tuple[list[float], list[float]]:
    """Area-preserving C1 smoothing of the latent-cp boxes.

    The database stores the latent block as a sharp box (e.g. SS316L:
    1374.99:640, 1375:4640, 1440:4640, 1440.01:800). FreeFEM's enthalpy-form
    theta solve absorbs the wall; MOOSE Newton stalls on the discontinuity
    (frozen residual / line-search divergence). Replace the box with a
    smooth symmetric ramp low -> peak -> low over the SAME temperature band,
    conservation of integral cp dT (= latent energy) exactly, so the stored
    energy budget and phase fraction remain identical; only the within-band
    temperature profile shape differs (documented in BUILD_NOTES).

    The ramp samples the smoothstep s^2*(3-2s) on a dense knot grid (C1 at
    the peak and at both joins: zero slope everywhere it meets a plateau).
    History note: the first pass used a single-slope segment linear ramp
    (triangle whose peak kink is a slope sign flip at Tmid) — letter-Z
    Newton stalled exactly at DIVERGED_LINE_SEARCH when the melt pool first
    crossed the latent band (failures from t ~ 5 s on the step-15 band
    entry). The dense smoothstep kills the kinks while changing nothing
    outside the latent band.
    """
    outT: list[float] = []
    outV: list[float] = []
    i = 1
    n = len(sT)
    N_RAMP = 16  # knots per half-ramp; slope steps ~ (P-V)/N^2 are Newton-benign
    while i < n - 1:
        dT_prev = sT[i] - sT[i - 1]
        dcp_prev = abs(sV[i] - sV[i - 1])
        if dcp_prev > 1500 and dT_prev < 50:
            T0, V0 = (sT[i - 1], sV[i - 1])
            Vp = sV[i]
            if i + 2 <= n - 1 and sV[i + 1] == Vp:
                Tend, Vn = (sT[i + 2], sV[i + 2])
                if (sV[i + 2] - sV[i] < 0 and sT[i + 2] - sT[i + 1] < 50):
                    i += 2
                    if outT and abs(outT[-1] - T0) < 1e-9:
                        outT[-1] = T0
                        outV[-1] = V0 if abs(outV[-1] - V0) > (abs(outV[-1] - 0)) else outV[-1]
                    else:
                        outT.append(T0); outV.append(V0)
                    h = 0.5 * (Tend - T0)
                    # Same peak as the area-conserving triangle: P chosen so the
                    # ramp's integral over [T0, Tend] equals Vp * (Tend - T0).
                    P = (Vp * (Tend - T0)) / h - 0.5 * (V0 + Vn)
                    Tmid = 0.5 * (T0 + Tend)
                    # Dense smoothstep sampling on both halves; the smoothstep's
                    # cumulative integral equals the linear ramp's, so the
                    # latent budget is preserved knot-for-knot.
                    for k in range(1, N_RAMP + 1):
                        s = k / N_RAMP
                        r = s * s * (3.0 - 2.0 * s)
                        outT.append(T0 + s * h)
                        outV.append(V0 + (P - V0) * r)
                    for k in range(1, N_RAMP + 1):
                        s = k / N_RAMP
                        r = s * s * (3.0 - 2.0 * s)
                        outT.append(Tmid + s * h)
                        outV.append(P + (Vn - P) * r)
                    i += 1
                    continue
        outT.append(sT[i - 1]); outV.append(sV[i - 1])
        i += 1
    for j in range(i - 1, n):
        outT.append(sT[j]); outV.append(sV[j])
    mergedT = [outT[0]]; mergedV = [outV[0]]
    for t_, v_ in zip(outT[1:], outV[1:]):
        if t_ - mergedT[-1] < 1e-9:
            mergedV[-1] = v_
        else:
            mergedT.append(t_); mergedV.append(v_)
    return mergedT, mergedV


def material_tables(p: dict) -> tuple[dict, dict]:
    """Zone tables from the shared database; cp smoothed exactly like the
    FreeFEM builder (`smooth_cp_spike`) latent shape; MOOSE Newton needs a
    finite-dcp/dT latent ramp, so cp is emitted as the area-preserving
    trapezoid (`trap_latent_cp`), k typed as-is (the generated k tables
    already match the database nodes bit-for-bit).

    CALPHAD (codegen/calphad.py) adds the phase-fraction tables for each zone:
    the solidus/liquidus are the database values (the CALPHAD backends honour
    them), and the phase fractions come from the solidification model."""
    db = json.loads((_MOOSE_ROOT / "core" / "multimaterial" / "material_database.json").read_text())
    alloys = db["alloys"]

    calphad_models = _calphad_models(p)

    def zone(name: str) -> dict:
        a = alloys[name]
        kT, kV = list(a["conductivity"]["T"]), list(a["conductivity"]["k"])
        sT, sV = list(a["specific_heat"]["T"]), list(a["specific_heat"]["Cp"])
        cT, cV = trap_latent_cp(sT, sV)
        model = calphad_models.get(name)
        out = {
            "kT": kT, "kV": kV, "cT": cT, "cV": cV,
            "rho": float(a["density"]), "Tliq": float(a["liquidus"]),
            "T_sol": float(a.get("solidus", 1450.0)),
            "emis": float(a["emissivity"]),
            "nu": float(a.get("poisson_ratio", 0.3)),
            "E": float(a.get("youngs_modulus", {}).get("E", [1.93e11])[0]) if a.get("youngs_modulus") else 1.93e11,
            "sigma_y": float(a.get("yield_strength", {}).get("sigma_y", [2.9e8])[0]) if a.get("yield_strength") else 2.9e8,
            "alpha": float(a.get("thermal_expansion", {}).get("alpha", [1.6e-5])[0]) if a.get("thermal_expansion") else 1.6e-5,
            "h_prime": float(a.get("hardening_modulus", 1.0e9)),
        }
        if model is not None:
            slots = model.thermal_slots()
            out["phase_T"] = list(model.T)
            out["phase_slots"] = slots
            out["phase_slot_names"] = model.phase_slot_names()
            out["phase_names"] = list(model.phase_names)
            out["solidus"] = model.solidus
            out["liquidus"] = model.liquidus
            out["ferrite_number"] = model.ferrite_number
            out["calphad_backend"] = model.backend
        return out

    return zone(p["material_base"]), zone(p["material_dep"])


def _meltpool_pp_block(base: dict, dep: dict, phase_slots: list) -> str:
    """Melt-pool phase statistics postprocessors.

    The postprocessor is a NODAL one: at TIMESTEP_END the element-level user
    objects see the pre-solve values of a nonlinear variable (the variable
    cache is only refreshed by the output step, which runs after the
    user-object batch), while the nodal batch recomputes the nodal values
    from the live solution vector. A nodal postprocessor therefore reports
    the solved state.

    The CALPHAD table of the DEPOSIT zone is used: the melt pool lives in the
    deposit, and the substrate is below the solidus for the whole run.
    """
    zone = dep if dep.get("phase_T") else base
    if not zone.get("phase_T"):
        return ""
    out = ""
    for mode, name in (("max_liquid", "max_liquid"),
                       ("molten_volume", "molten_fraction"),
                       ("mean_liquid", "mean_liquid")):
        out += f"""  [{name}]
    type = WAAMMeltPoolPhase
    variable = T
    mode = {mode}
    T_phase = '{_fmt_list(zone['phase_T'])}'
    f_liquid = '{_fmt_list(zone['phase_slots']['liquid'])}'
    f_primary = '{_fmt_list(zone['phase_slots']['primary'])}'
    f_secondary = '{_fmt_list(zone['phase_slots']['secondary'])}'
    execute_on = 'initial timestep_end'
  []
"""
    return out


def _calphad_payload(p: dict) -> dict:
    """The CALPHAD solidification model for the two zones, as a JSON artifact."""
    models = _calphad_models(p)
    if not models:
        return {}
    payload = {}
    for name, model in models.items():
        payload[name] = model.to_dict()
        payload[name]["thermal_slots"] = model.phase_slot_names()
    return payload


def _calphad_models(p: dict) -> dict:
    """Solidification models for the two zones (empty when CALPHAD is off)."""
    if not p.get("enable_calphad", True):
        return {}
    try:
        try:
            from .calphad import (  # type: ignore
                compute_alloy,
                load_database,
                select_backend,
            )
        except ImportError:
            from calphad import (  # type: ignore
                compute_alloy,
                load_database,
                select_backend,
            )
    except Exception as exc:  # pragma: no cover - import guard
        print("[MOOSE-BUILDER] CALPHAD unavailable (%s); phase fractions disabled" % exc)
        return {}

    backend_name = str(p.get("calphad_backend", "auto"))
    tdb = p.get("calphad_tdb", "") or None
    try:
        backend = select_backend(backend_name, tdb)
    except SystemExit as exc:
        print("[MOOSE-BUILDER] CALPHAD backend unavailable (%s); phase fractions disabled" % exc)
        return {}

    alloys = load_database()
    models = {}
    for name in (p["material_base"], p["material_dep"]):
        if name not in alloys:
            continue
        try:
            models[name] = compute_alloy(name, backend)
        except Exception as exc:
            print("[MOOSE-BUILDER] CALPHAD failed for %s: %s" % (name, exc))
    return models


def convert_mesh(mesh_in: Path, exo_out: Path, warn: BuilderWarn) -> None:
    if mesh_in.suffix.lower() == ".exo":
        if mesh_in.resolve() != exo_out.resolve():
            shutil.copy2(mesh_in, exo_out)
        return
    conv = _MOOSE_HOME / "mesh" / "medit_to_exodus.py"
    if not conv.exists():
        warn.warn(f"converter missing: {conv}")
        raise SystemExit(2)
    cmd = [sys.executable, str(conv), str(mesh_in), str(exo_out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        warn.warn(f"medit_to_exodus.py failed: {r.stderr.strip()[:400]}")
        raise SystemExit(2)
    if r.stdout.strip():
        print(r.stdout.strip())


# --------------------------------------------------------------------------- #
#  .i emission
# --------------------------------------------------------------------------- #

def emit_i(
    p: dict,
    sched_times: list[float],
    base: dict,
    dep: dict,
    paths: dict,
    warn: BuilderWarn,
) -> str:
    af, ar, bG, cG = p["af"], p["ar"], p["bG"], p["cG"]
    P_weld = p["I_weld"] * p["U_weld"]  # 4800 W (eta carried separately, goldakQ uses P*eta)
    eta = p["eta_arc"]
    P_eff = P_weld * eta  # == FreeFEM Pweld constant (3840); audit target 714.514 kJ
    eps_split = max(0.1 * min(af, ar), 0.25 * p["lx"] / max(p["nx_dep"], 1))
    bidirectional = str(p["deposition_pattern"]) == "bidirectional"
    hz_base = p["hz_base"]
    h_first = p["h_bead_first"]
    h_sub = p["h_bead_subseq"]
    dwell = p["t_wait"]
    rad = p["emissivity"] * SIGMA_SB if p.get("enable_radiation", True) else 0.0
    # Evaporation-cap parameters (FreeFEM Tboil clip parity). The smooth
    # sink rate is chosen so the pool rides at Tboil + q/(rho*cp*rate)
    # < 10 K at the baseline arc regime; width keeps the gate C1.
    cap_rate = 100.0
    cap_width = 50.0
    use_lumped = bool(p.get("use_lumped_mass", False))
    td_kernel_type = "WAAMLumpedHeatTimeDerivative" if use_lumped else "HeatConductionTimeDerivative"
    if p.get("enable_boiling_cap", True):
        cap_block = f"""  [cap]
    type = WAAMBoilingCapKernel
    variable = T
    t_boil = {p.get('t_boil_C', 2862):.1f}
    rate = {cap_rate:.6g}
    width = {cap_width:.6g}
  []
"""
        cap_pp_block = f"""  [cap_power]
    type = WAAMCapPower
    temperature = T
    t_boil = {p.get('t_boil_C', 2862):.1f}
    rate = {cap_rate:.6g}
    width = {cap_width:.6g}
    execute_on = 'initial timestep_end'
  []
"""
    else:
        cap_block = ""
        cap_pp_block = ""
        warn.warn(
            "enable_boiling_cap is OFF: no evaporation sink emitted -- nothing "
            "removes energy above the boiling point; peak temperatures far above "
            "Tboil are expected (FreeFEM measured 6281 C on DEFAULT). Conscious "
            "choice, but audited as a fidelity difference."
        )
    cap_show = " cap_power" if p.get("enable_boiling_cap", True) else ""

    # ---- CALPHAD phase-fraction emission ---------------------------------
    # MOOSE parameters are static, so the phase fractions are exposed as
    # three fixed thermal slots (liquid / primary solid / secondary solid);
    # the real phase names travel in the calphad.json artifact.
    phase_slots = ["liquid", "primary", "secondary"]

    if base.get("phase_T") or dep.get("phase_T"):
        # NOTE: the phase fractions are NOT exported as an auxiliary field on
        # purpose. At EXEC_TIMESTEP_END the element-level user objects (the
        # aux kernels among them) see the PRE-solve values of a nonlinear
        # variable -- the variable cache is only refreshed by the output step,
        # which runs after the user-object batch -- so an exported field would
        # carry the initial condition rather than the solved state. The
        # melt-pool statistics are therefore reported by NODAL postprocessors
        # (which recompute the nodal values from the live solution vector and
        # are correct), and the per-phase fractions stay available as the
        # material properties phase_fraction_{liquid,primary,secondary}.
        meltpool_pp_block = _meltpool_pp_block(base, dep, phase_slots)
        meltpool_show = " max_liquid molten_fraction mean_liquid"
    else:
        meltpool_pp_block = ""
        meltpool_show = ""

    def phase_material_block(zone: dict, zone_name: str) -> str:
        if not zone.get("phase_T"):
            return ""
        out = f"    T_phase_{zone_name} = '{_fmt_list(zone['phase_T'])}'\n"
        for slot in phase_slots:
            values = zone["phase_slots"].get(slot, [])
            out += f"    f_{slot}_{zone_name} = '{_fmt_list(values)}'\n"
        return out

    # FreeFEM-parity post-solve nodal clip (Temp=max(Temp,Tamb);
    # psiActive<0.5 -> Tamb; Temp>=Tboil -> Tboil), emitted as a Corrector
    # (a UserObject with force_preaux = true). CRITICAL: force_preaux moves it
    # into the PRE_AUX user-object batch, which FEProblemBase::execute runs
    # BEFORE computeSystems and BEFORE the POST_AUX batch that holds element
    # postprocessors. Without force_preaux a user object is POST_AUX and
    # computeUserObjectsInternal runs element user objects (all postprocessors)
    # BEFORE general user objects, so tmin/tmax would sample the raw unclipped
    # field. This is the literal algorithm of the .edp's clip step.
    if p.get("enable_freefem_clip", True):
        corrector_block = f"""  [freefem_clip]
    type = WAAMFreeFEMClip
    variable = T
    psi = psi
    ambient = {p['T_amb']:.1f}
    boiling = {p.get('t_boil_C', 2862):.1f}
    psi_threshold = 0.5
    execute_on = 'TIMESTEP_END'
    force_preaux = true
  []
"""
    else:
        corrector_block = ""
        warn.warn(
            "enable_freefem_clip is OFF: the FreeFEM post-solve nodal clip "
            "(max(Temp,Tamb); psiActive<0.5 -> Tamb; Temp>=Tboil -> Tboil) is not "
            "reproduced, so tmin can undershoot below ambient on the cold side of "
            "the moving source and T can exceed Tboil. Audited as a fidelity "
            "difference vs the baseline."
        )

    enable_us = bool(p.get("enable_ultrasonic", False))
    us_freq = float(p.get("ultrasonic_frequency", 20000.0))
    us_amp = float(p.get("ultrasonic_amplitude", 15.0e-6))
    if enable_us:
        us_auxvar_block = """  [acoustic_pressure]
    family = MONOMIAL
    order = CONSTANT
    initial_condition = 0
  []
  [acoustic_streaming]
    family = MONOMIAL
    order = CONSTANT
    initial_condition = 0
  []
  [acoustic_dissipation]
    family = MONOMIAL
    order = CONSTANT
    initial_condition = 0
  []
  [acoustic_softening]
    family = MONOMIAL
    order = CONSTANT
    initial_condition = 0
  []
  [cavitation_index]
    family = MONOMIAL
    order = CONSTANT
    initial_condition = 0
  []
"""
        us_auxkernel_block = f"""  [uva_pressure]
    type = WAAMUltrasonicAux
    variable = acoustic_pressure
    field_type = pressure
    frequency = {us_freq:.1f}
    amplitude = {us_amp:.6e}
    execute_on = 'initial timestep_end'
  []
  [uva_streaming]
    type = WAAMUltrasonicAux
    variable = acoustic_streaming
    field_type = streaming_velocity
    frequency = {us_freq:.1f}
    amplitude = {us_amp:.6e}
    execute_on = 'initial timestep_end'
  []
  [uva_dissipation]
    type = WAAMUltrasonicAux
    variable = acoustic_dissipation
    field_type = dissipation
    frequency = {us_freq:.1f}
    amplitude = {us_amp:.6e}
    execute_on = 'initial timestep_end'
  []
  [uva_softening]
    type = WAAMUltrasonicAux
    variable = acoustic_softening
    field_type = softening
    frequency = {us_freq:.1f}
    amplitude = {us_amp:.6e}
    execute_on = 'initial timestep_end'
  []
  [uva_cavitation]
    type = WAAMUltrasonicAux
    variable = cavitation_index
    field_type = cavitation_index
    frequency = {us_freq:.1f}
    amplitude = {us_amp:.6e}
    execute_on = 'initial timestep_end'
  []
"""
        us_pp_block = """  [uva_softening_max]
    type = ElementExtremeValue
    variable = acoustic_softening
    value_type = max
    execute_on = 'initial timestep_end'
  []
  [uva_pressure_max]
    type = ElementExtremeValue
    variable = acoustic_pressure
    value_type = max
    execute_on = 'initial timestep_end'
  []
"""
        us_show = " uva_softening_max uva_pressure_max"
        softening_coupling_line = "softening = acoustic_softening"
    else:
        us_auxvar_block = ""
        us_auxkernel_block = ""
        us_pp_block = ""
        us_show = ""
        softening_coupling_line = ""

    enable_mech = bool(p.get("enable_mechanical", False))
    springback = bool(p.get("springback_solve", False)) or bool(p.get("dynamic_clamping", False))
    if enable_mech:
        mech_physics_block = """[Physics/SolidMechanics/QuasiStatic]
  displacements = 'disp_x disp_y disp_z'
  [all]
    displacements = 'disp_x disp_y disp_z'
    temperature = T
    strain = SMALL
    incremental = true
    add_variables = true
    eigenstrain_names = 'thermal_eigenstrain'
    generate_output = 'stress_xx stress_yy stress_zz vonmises_stress'
  []
[]
"""
        mech_bc_block = """  [clamp_x]
    type = DirichletBC
    variable = disp_x
    boundary = lbl_1
    value = 0
  []
  [clamp_y]
    type = DirichletBC
    variable = disp_y
    boundary = lbl_1
    value = 0
  []
  [clamp_z]
    type = DirichletBC
    variable = disp_z
    boundary = lbl_1
    value = 0
  []
"""
        if springback:
            spring_k = float(p.get("fixture_stiffness_spring", 1e3))
            mech_bc_block += f"""  [isostatic_spring_x]
    type = PenaltyDirichletBC
    variable = disp_x
    boundary = lbl_1
    value = 0
    penalty = {spring_k:.4e}
    enable = false
  []
  [isostatic_spring_y]
    type = PenaltyDirichletBC
    variable = disp_y
    boundary = lbl_1
    value = 0
    penalty = {spring_k:.4e}
    enable = false
  []
  [isostatic_spring_z]
    type = PenaltyDirichletBC
    variable = disp_z
    boundary = lbl_1
    value = 0
    penalty = {spring_k:.4e}
    enable = false
  []
"""
        mech_mat_block = f"""  [elasticity]
    type = WAAMElasticityTensor
    temperature = T
    psi_var = psi
    fa_var = fa
    hz_base = {hz_base:.6e}
    E_substrate = {base['E']:.6e}
    E_deposit = {dep['E']:.6e}
    poissons_ratio_substrate = {base['nu']:.6g}
    poissons_ratio_deposit = {dep['nu']:.6g}
    T_solidus_substrate = {base.get('T_sol', 1450.0):.6g}
    T_solidus_deposit = {dep.get('T_sol', 1450.0):.6g}
    born_floor = 1e-5
    slurry_factor = 0.02
  []
  [stress]
    type = ComputeMultipleInelasticStress
    inelastic_models = 'plasticity'
    tangent_operator = elastic
  []
  [plasticity]
    type = WAAMPlasticityStressUpdate
    temperature = T
    fa_var = fa
    T_solidus = {dep.get('T_sol', 1450.0):.6g}
    yield_stress = {dep['sigma_y']:.6e}
    hardening_constant = {dep['h_prime']:.6e}
    {softening_coupling_line}
  []
  [thermal_expansion]
    type = WAAMThermalExpansionEigenstrain
    temperature = T
    stress_free_temperature = {p.get('T_amb', 20.0):.6g}
    thermal_expansion_coeff = {dep['alpha']:.6e}
    T_solidus = {dep.get('T_sol', 1450.0):.6g}
    fa_var = fa
    eigenstrain_name = thermal_eigenstrain
  []
"""
        mech_pp_block = """  [vonmises_max]
    type = ElementExtremeValue
    variable = vonmises_stress
    value_type = max
    execute_on = 'initial timestep_end'
  []
  [disp_z_max]
    type = NodalExtremeValue
    variable = disp_z
    value_type = max
    execute_on = 'initial timestep_end'
  []
  [disp_z_min]
    type = NodalExtremeValue
    variable = disp_z
    value_type = min
    execute_on = 'initial timestep_end'
  []
"""
        mech_show = " vonmises_max disp_z_max disp_z_min"
    else:
        mech_physics_block = ""
        mech_bc_block = ""
        mech_mat_block = ""
        mech_pp_block = ""
        mech_show = ""

    controls_block = ""
    if enable_mech and springback:
        t_unclamp = float(p.get("t_unclamp", 0.0))
        if t_unclamp <= 0.0:
            t_unclamp = 0.5 * sched_times[-1] if sched_times else 10.0
        controls_block = f"""[Controls]
  [unclamp]
    type = TimePeriod
    disable_objects = 'BCs/clamp_x BCs/clamp_y BCs/clamp_z'
    enable_objects = 'BCs/isostatic_spring_x BCs/isostatic_spring_y BCs/isostatic_spring_z'
    start_time = '{t_unclamp:.6f}'
    set_sync_times = true
  []
[]
"""
        warn.warn(f"Multi-stage fixture release & springback active: clamp release at t = {t_unclamp:.3f} s.")

    def table_list(Ts, Vs):
        return " ".join(_fmt(v) for v in Ts), " ".join(_fmt(v) for v in Vs)

    base_kT, base_kV = table_list(base["kT"], base["kV"])
    base_cT, base_cV = table_list(base["cT"], base["cV"])
    dep_kT, dep_kV = table_list(dep["kT"], dep["kV"])
    dep_cT, dep_cV = table_list(dep["cT"], dep["cV"])

    ts_str = "\n".join(
        " ".join(_fmt(x) for x in sched_times[i : i + 6]) for i in range(0, len(sched_times), 6)
    )
    end_time = sched_times[-1]
    default_ls = "basic" if enable_mech else "l2"
    ls_type = p.get("linesearch", default_ls)
    petsc_opts = f"80 {ls_type} 1e-4 1e10 preonly lu mumps"

    val = p.get("adaptive_dt", False)
    adaptive_dt = (isinstance(val, bool) and val) or (str(val).lower() in ("on", "true", "1", "adaptive", "iteration_adaptive"))
    if adaptive_dt:
        dt_init = float(p.get("dt_weld", 0.5))
        dt_max = float(p.get("dt_max", 30.0))
        optimal_it = int(p.get("optimal_iterations", 16))
        window = int(p.get("iteration_window", 6))
        dt_min = float(p.get("dt_min", 0.005 if enable_mech else 0.01))
        timestepper_block = f"""  dtmin = {dt_min:.4g}
  dtmax = {dt_max:.4g}
  error_on_dtmin = false
  petsc_options_iname = '-snes_max_it -snes_linesearch_type -snes_linesearch_minlambda -snes_divergence_tolerance -ksp_type -pc_type -pc_factor_mat_solver_type'
  petsc_options_value = '{petsc_opts}'
  [TimeStepper]
    type = IterationAdaptiveDT
    dt = {dt_init:.6g}
    optimal_iterations = {optimal_it}
    iteration_window = {window}
    growth_factor = 1.2
    cutback_factor = 0.7
  []"""
    else:
        timestepper_block = f"""  dtmin = 1e-4
  error_on_dtmin = false
  petsc_options_iname = '-snes_max_it -snes_linesearch_type -snes_linesearch_minlambda -snes_divergence_tolerance -ksp_type -pc_type -pc_factor_mat_solver_type'
  petsc_options_value = '{petsc_opts}'
  [TimeStepper]
    type = TimeSequenceStepper
    time_sequence = '
{ts_str}'
  []"""

    scaling_block = """  automatic_scaling = true
  compute_scaling_once = false
""" if enable_mech else ""
    default_abs_tol = 1e-3 if enable_mech else 1e-1

    return f"""# waam_moose.i - generated by codegen/moose_builder.py (backend=moose)
# {time.strftime('%Y-%m-%d %H:%M:%S')}
# schema: waam-moose-app 8bc7d5b4 | steps: {len(sched_times)} | end: {end_time:.6f} s
# Substrate {p['material_base']} / deposit {p['material_dep']} | Pweld(eff) {P_eff:.1f} W
# eps_split {eps_split:.6e} | bidi {bidirectional}
{warn.block()}

[Mesh]
  file = {paths['mesh_exo']}
[]

[Variables]
  [T]
    family = LAGRANGE
    order = 1
    initial_condition = {p['T_amb']}
  []
[]

[AuxVariables]
  [psi]
    family = LAGRANGE
    order = 1
    initial_condition = 0
  []
  [fa]
    family = MONOMIAL
    order = CONSTANT
    initial_condition = 0
  []
{us_auxvar_block}[]

[AuxKernels]
  [psi]
    type = WAAMActivationAux
    toolpath_uo = toolpath
    variable = psi
    execute_on = 'initial timestep_begin'
  []
  [fa]
    type = WAAMActivationAux
    toolpath_uo = toolpath
    variable = fa
    execute_on = 'initial timestep_begin'
  []
{us_auxkernel_block}[]

{mech_physics_block}[Kernels]
  [goldak]
    type = WAAMGoldakKernel
    variable = T
    toolpath_uo = toolpath
    psi_var = psi
    fa_var = fa
    use_masks = true
  []
{cap_block}  [td]
    type = {td_kernel_type}
    variable = T
    density_name = density
    specific_heat = specific_heat
  []
  [diff]
    type = HeatConduction
    variable = T
    thermal_conductivity = thermal_conductivity
  []
[]

[BCs]
  [bottom]
    type = WAAMRobinBC
    variable = T
    boundary = lbl_1
    psi_var = psi
    h = {p['h_bot']}
    T_ambient = {p['T_amb']}
    radiation = 0
  []
  [surfaces]
    type = WAAMRobinBC
    variable = T
    boundary = 'lbl_2 lbl_5'
    psi_var = psi
    h = {p['h_conv']}
    T_ambient = {p['T_amb']}
    radiation = {rad:.6e}
  []
{mech_bc_block}[]

[Materials]
  [props]
    type = WAAMActivationMaterial
    temperature = T
    psi_var = psi
    fa_var = fa
    hz_base = {hz_base}
    psi_floor = 1e-4
    born_floor = 1e-5
    k_liq_factor = {p.get('k_liq_factor', 1.0)}
    T_k_substrate = '{base_kT}'
    k_substrate = '{base_kV}'
    T_cp_substrate = '{base_cT}'
    cp_substrate = '{base_cV}'
    rho_substrate = {base['rho']}
    Tliq_substrate = {base['Tliq']}
{phase_material_block(base, 'substrate')}    T_k_deposit = '{dep_kT}'
    k_deposit = '{dep_kV}'
    T_cp_deposit = '{dep_cT}'
    cp_deposit = '{dep_cV}'
    rho_deposit = {dep['rho']}
    Tliq_deposit = {dep['Tliq']}
{phase_material_block(dep, 'deposit')}  []
{mech_mat_block}[]

[UserObjects]
  [toolpath]
    type = WAAMToolpathUO
    toolpath_file = {paths['toolpath']}
    layer_times_file = {paths['layer_times']}
    hz_base = {hz_base}
    h_bead_first = {h_first}
    h_bead_sub = {h_sub}
    dwell_time = {dwell}
    match_tol_frac = 0.45
    af = {af}
    ar = {ar}
    bG = {bG}
    cG = {cG}
    z_activation_frac = {Z_ACT_FRAC}
    bidirectional = {str(bidirectional).lower()}
    split_epsilon = {eps_split:.10g}
    P_weld = {P_weld:.10g}
    eta = {eta}
    ff = {p['ff']}
    fr = {p['fr']}
  []
  [audit]
    type = WAAMEnergyAuditUO
    toolpath_uo = toolpath
    pweld = {P_eff:.10g}
    power_pp = src_power
    power_raw_pp = src_power_raw
    execute_on = 'initial timestep_end'
  []
[]

[Correctors]
{corrector_block}[]

[Postprocessors]
  [active_frac]
    type = WAAMActiveFraction
    toolpath_uo = toolpath
    execute_on = 'initial timestep_end'
  []
  [active_count]
    type = WAAMActiveFraction
    toolpath_uo = toolpath
    as_count = true
    execute_on = 'initial timestep_end'
  []
  [active_count_tq]
    type = WAAMActiveFraction
    toolpath_uo = toolpath
    as_count = true
    use_time_query = true
    execute_on = 'initial timestep_end'
  []
  [torch_x]
    type = WAAMTorchProbe
    toolpath_uo = toolpath
    component = x
    execute_on = 'initial timestep_end'
  []
  [torch_z]
    type = WAAMTorchProbe
    toolpath_uo = toolpath
    component = z
    execute_on = 'initial timestep_end'
  []
  [torch_pstate]
    type = WAAMTorchProbe
    toolpath_uo = toolpath
    component = pstate
    execute_on = 'initial timestep_end'
  []
  [torch_layer]
    type = WAAMTorchProbe
    toolpath_uo = toolpath
    component = layer
    execute_on = 'initial timestep_end'
  []
  [tmax]
    type = NodalExtremeValue
    variable = T
    value_type = max
    execute_on = 'initial timestep_end'
  []
  [tmin]
    type = NodalExtremeValue
    variable = T
    value_type = min
    execute_on = 'initial timestep_end'
  []
  [src_power]
    type = WAAMSourcePower
    toolpath_uo = toolpath
    psi_var = psi
    fa_var = fa
    execute_on = 'initial timestep_end'
  []
  [src_power_raw]
    type = WAAMSourcePower
    toolpath_uo = toolpath
    psi_var = psi
    fa_var = fa
    use_masks = false
    execute_on = 'initial timestep_end'
  []
  [e_intended]
    type = WAAMEnergyAuditPP
    audit_uo = audit
    quantity = intended_energy
    execute_on = 'initial timestep_end'
  []
  [e_injected]
    type = WAAMEnergyAuditPP
    audit_uo = audit
    quantity = injected_energy
    execute_on = 'initial timestep_end'
  []
  [e_injected_raw]
    type = WAAMEnergyAuditPP
    audit_uo = audit
    quantity = injected_energy_raw
    execute_on = 'initial timestep_end'
  []
  [fidelity]
    type = WAAMEnergyAuditPP
    audit_uo = audit
    quantity = fidelity
    execute_on = 'initial timestep_end'
  []
{cap_pp_block}{meltpool_pp_block}{mech_pp_block}{us_pp_block}  [num_failed_steps]
    type = NumFailedTimeSteps
    execute_on = 'initial timestep_end'
  []
[]

{controls_block}[Preconditioning]
  [smp]
    type = SMP
    full = true
  []
[]

[Executioner]
  type = Transient
  solve_type = NEWTON
  end_time = {end_time:.10f}
  nl_rel_tol = {p.get('nl_rel_tol', 1e-4)}
  nl_abs_tol = {p.get('nl_abs_tol', default_abs_tol)}
{scaling_block}{timestepper_block}
[]

[Outputs]
  csv = true
  [console]
    type = Console
    output_screen = true
    output_file = false
    max_rows = 12
    execute_on = 'timestep_end'
  []
  [exo]
    type = Exodus
    time_step_interval = 20
  []
  [ckpt]
    type = Checkpoint
    num_files = 1
  []
  show = 'T psi fa active_frac active_count active_count_tq tmax tmin torch_x torch_z torch_pstate torch_layer src_power src_power_raw e_intended e_injected e_injected_raw fidelity num_failed_steps{cap_show}{meltpool_show}{mech_show}{us_show}'
[]
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WAAM MOOSE input builder")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None, help="waam output .i path")
    args = ap.parse_args(argv)

    run = args.run_dir.resolve()
    # Check if run directory contains the artifacts directly (untethered MOOSE lane)
    if (run / "parameters.json").exists():
        params_path = run / "parameters.json"
        toolpath = run / "toolpath.txt"
        layer_times = run / "layer_pass_times.txt"
        cand = (sorted(run.glob("*.exo")) +
                sorted((run / "moose").glob("*.exo")) +
                sorted(run.glob("*.mesh")) +
                sorted((run / "mesh").glob("*.mesh")))
        mesh_in = cand[0] if cand else None
    else:
        # Legacy FreeFEM artifact lane fallback
        ff_dir = run / "FreeFEM"
        params_path = ff_dir / "parameters.json"
        toolpath = ff_dir / "toolpath.txt"
        layer_times = ff_dir / "layer_pass_times.txt"
        mesh_in = Path(json.loads(params_path.read_text())["mesh_file"]) if params_path.exists() else None
        if not mesh_in or not mesh_in.exists():
            cand = sorted(ff_dir.glob("*.mesh"))
            mesh_in = cand[0] if cand else None

    if not (params_path and params_path.exists() and toolpath and toolpath.exists() and
            layer_times and layer_times.exists() and mesh_in and mesh_in.exists()):
        print("[MOOSE-BUILDER] FATAL: run dir missing required artifacts "
              f"(parameters.json/toolpath.txt/layer_pass_times.txt/*.mesh|*.exo): {run}")
        return 2

    raw_params = params_path.read_bytes()
    wall = json.loads(raw_params.decode())

    warn = BuilderWarn()
    b = EDPBuilder(wall)  # validates, warns on unknown keys (same channel spirit)
    w = b._auto_size_source()
    p = b.p

    # Forward advanced simulation flags
    springback = bool(p.get("springback_solve", False)) or bool(wall.get("springback_solve", False)) or bool(wall.get("dynamic_clamping", False))
    if springback:
        p["springback_solve"] = True
    v1 = p.get("adaptive_dt", False)
    v2 = wall.get("adaptive_dt", False)
    adaptive_dt = (isinstance(v1, bool) and v1) or (isinstance(v2, bool) and v2) or (str(v1).lower() in ("on", "true", "1", "adaptive", "iteration_adaptive")) or (str(v2).lower() in ("on", "true", "1", "adaptive", "iteration_adaptive"))
    if adaptive_dt:
        p["adaptive_dt"] = True
    else:
        p["adaptive_dt"] = False

    # ---------------- structural warnings (MOOSE MVP scope) ----------------
    for key in sorted(wall):
        if key.startswith(("mech_", "ultrasonic", "adaptive_", "interpass_")) or key in (
            "enable_mechanical", "enable_j2_plasticity", "enable_microstructure",
            "enable_ultrasonic", "enable_yield_truncation", "dynamic_clamping",
            "fixture_stiffness_ratio_xy", "fixture_stiffness_ratio_z",
            "gravity_m_s2", "mechanical_bc", "mechanics_order", "nlgeom",
            "inherent_strain_fallback", "h_prime_iso", "peeq_limit", "springback_solve",
            "springback_regularization", "trip_beta", "theta", "nu", "rb", "rt",
            "a_band", "b_band", "c_band", "d_pen", "d_wire", "v_wire", "T_mech",
            "T_drop", "eta_drop", "mech_solve_cadence", "restart_resume",
        ):
            pass  # collected below via explicit MVP scope note
    if not bool(p.get("enable_mechanical", True)):
        warn.warn("enable_mechanical is OFF: running thermal-only simulation.")
    else:
        warn.warn("Coupled Thermo-Mechanics active: QuasiStatic J2 von Mises plasticity, thermal expansion, and substrate fixtures emitted.")

    if p["heat_source"] != "goldak":
        warn.warn(f"heat_source = {p['heat_source']}: only the Goldak kernel is "
                  "registered in the app at P2; refusing silently is a bug.")
        return 3
    if str(wall.get("adaptive_dt", "off")) != "off" and not adaptive_dt:
        warn.warn("adaptive_dt != off: the TimeSequenceStepper below hard-codes "
                  "the fixed-step FreeFEM schedule; run adaptive passes only "
                  "after M9 adaptivity lands.")
    elif adaptive_dt:
        warn.warn("adaptive_dt is ON: IterationAdaptiveDT dynamically adjusts time-step between dt_min and dt_max.")
    if str(wall.get("interpass_cooling_mode", "time")) != "time":
        warn.warn("interpass_cooling_mode != 'time': dwell length is a solved "
                  "quantity in that mode; the emitted schedule assumes the "
                  "legacy fixed t_wait dwell.")
    if p.get("multi_material"):
        warn.warn("multi_material deposits beyond base+deposit are not emitted; "
                  "the two-zone material block follows material_base/material_dep.")
    warn.warn("FreeFEM qScale per-step rescale is NOT replicated; the audit's "
              "injected counter measures raw fidelity (P4 option B).")

    toks = layer_times.read_text().split()
    n_layers = int(toks[0])
    lp = [float(t) for i, t in enumerate(toks[1:]) if i % 2 == 1][:n_layers]
    ps = freefem_step_times(p, lp)
    if springback:
        t_unclamp = float(p.get("t_unclamp", 0.0))
        if t_unclamp <= 0.0:
            n_dwells = max(0, n_layers - 1)
            t_unclamp = sum(lp) + n_dwells * float(p.get("t_wait", 5.0))
            p["t_unclamp"] = t_unclamp
        if not any(abs(t - t_unclamp) < 1e-5 for t in ps) and 0.0 < t_unclamp < ps[-1]:
            ps = sorted(ps + [t_unclamp])
    base_t, dep_t = material_tables(p)

    out_dir = run / "moose"
    out_dir.mkdir(exist_ok=True)
    exo = out_dir / "mesh.exo"
    convert_mesh(mesh_in, exo, warn)
    paths = {"mesh_exo": str(exo), "toolpath": str(toolpath), "layer_times": str(layer_times)}

    out_i = args.out or out_dir / "waam_moose.i"
    text = emit_i(p, ps, base_t, dep_t, paths, warn)
    out_i.write_text(text)

    def sha(f: Path) -> str:
        return hashlib.sha256(f.read_bytes()).hexdigest()

    meta = {
        "backend": "moose",
        "schema": "waam-moose-app 8bc7d5b4",
        "generated_by": "codegen/moose_builder.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parameter_sha256": sha(params_path),
        "toolpath_sha256": sha(toolpath),
        "layer_times_sha256": sha(layer_times),
        "mesh_sha256": sha(mesh_in),
        "input_sha256": sha(out_i),
        "n_steps": len(ps),
        "end_time_s": ps[-1],
        "adaptive_dt": adaptive_dt,
        "springback_solve": springback,
        "t_unclamp": p.get("t_unclamp") if springback else None,
        "zones": [p["material_base"], p["material_dep"]],
        "Pweld_eff_W": p["I_weld"] * p["U_weld"] * p["eta_arc"],
        "warnings": warn.lines,
    }
    (out_dir / "waam_moose.i.meta").write_text(json.dumps(meta, indent=2) + "\n")

    # The CALPHAD solidification model is written next to the input so the
    # audit can state which backend produced the phase-fraction tables and
    # what the real phase names behind the thermal slots were.
    calphad_payload = _calphad_payload(p)
    if calphad_payload:
        (out_dir / "calphad.json").write_text(json.dumps(calphad_payload, indent=1) + "\n")
        print("[MOOSE-BUILDER] wrote %s" % (out_dir / "calphad.json"))

    print(f"[MOOSE-BUILDER] wrote {out_i} ({len(ps)} steps, end {ps[-1]:.3f} s) + .meta")
    for line in warn.lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())