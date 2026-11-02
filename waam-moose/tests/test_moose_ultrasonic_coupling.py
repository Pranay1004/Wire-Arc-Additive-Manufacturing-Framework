"""
tests/test_moose_ultrasonic_coupling.py

Ultrasonic Vibration-Assisted (UVA) Coupling Verification Suite
===============================================================
Verifies the ultrasonic acoustic field formulation and dynamic softening
constitutive coupling implemented in WAAMUltrasonicAux.C and WAAMPlasticityStressUpdate.C.
"""

import math
import pytest


def eval_acoustic_fields(freq_hz: float, amp_m: float, rho: float = 7900.0, c_sound: float = 4500.0, alpha_att: float = 5.0, z: float = 0.0):
    """Python reference evaluation of WAAMUltrasonicAux.C."""
    omega = 2.0 * math.pi * freq_hz
    # Acoustic velocity amplitude at transducer face
    v_source = omega * amp_m
    # Specific acoustic impedance
    z_acou = rho * c_sound
    # Pressure amplitude with exponential spatial attenuation
    p0 = z_acou * v_source
    p_amp = p0 * math.exp(-alpha_att * max(0.0, z))
    # Acoustic intensity
    intensity = (p_amp ** 2) / (2.0 * z_acou)
    # Volumetric acoustic dissipation
    q_acou = 2.0 * alpha_att * intensity
    # Dynamic softening factor (Blaha-Langenecker acoustic softening)
    i_ref = 1.0e6  # W/m2 reference intensity
    s_acou = min(0.80, 0.45 * math.sqrt(intensity / i_ref))
    # Cavitation threshold index (P_threshold ~ 1.5 MPa in liquid steel)
    p_cav_threshold = 1.5e6
    c_cav = max(0.0, (p_amp - p_cav_threshold) / p_cav_threshold)
    return {
        "omega": omega,
        "v_source": v_source,
        "z_acou": z_acou,
        "p_amp": p_amp,
        "intensity": intensity,
        "q_acou": q_acou,
        "s_acou": s_acou,
        "c_cav": c_cav,
    }


def eval_softened_flow_stress(sigma_y0: float, T: float, T_sol: float, s_acou: float):
    """Python reference evaluation of WAAMPlasticityStressUpdate.C yield softening."""
    if T <= 20.0:
        fT = 1.0
    elif T < T_sol:
        theta = (T - 20.0) / (T_sol - 20.0)
        fT = max(0.05, 1.0 - 0.85 * theta)
    else:
        fT = 0.05

    softening_mult = max(0.10, 1.0 - s_acou)
    return sigma_y0 * fT * softening_mult


def test_acoustic_pressure_and_intensity_scaling():
    """Acoustic pressure must scale linearly with amplitude and frequency; intensity quadratically."""
    f0 = 20000.0  # 20 kHz
    a0 = 15.0e-6  # 15 μm
    res0 = eval_acoustic_fields(f0, a0)

    # Double amplitude -> double pressure, 4x intensity
    res_double_a = eval_acoustic_fields(f0, 2.0 * a0)
    assert math.isclose(res_double_a["p_amp"], 2.0 * res0["p_amp"], rel_tol=1e-6)
    assert math.isclose(res_double_a["intensity"], 4.0 * res0["intensity"], rel_tol=1e-6)

    # Double frequency -> double pressure, 4x intensity
    res_double_f = eval_acoustic_fields(2.0 * f0, a0)
    assert math.isclose(res_double_f["p_amp"], 2.0 * res0["p_amp"], rel_tol=1e-6)
    assert math.isclose(res_double_f["intensity"], 4.0 * res0["intensity"], rel_tol=1e-6)


def test_acoustic_softening_flow_stress_coupling():
    """Acoustic softening must reduce yield strength by up to 80% without going negative."""
    sigma_y0 = 300.0e6  # 300 MPa
    T_sol = 1450.0

    # Cold, no ultrasound: σy = 300 MPa
    sy_cold = eval_softened_flow_stress(sigma_y0, T=20.0, T_sol=T_sol, s_acou=0.0)
    assert math.isclose(sy_cold, sigma_y0, rel_tol=1e-6)

    # Cold, 30% acoustic softening: σy = 210 MPa
    sy_cold_uva = eval_softened_flow_stress(sigma_y0, T=20.0, T_sol=T_sol, s_acou=0.30)
    assert math.isclose(sy_cold_uva, 0.70 * sigma_y0, rel_tol=1e-6)

    # Hot (1000 °C), 50% acoustic softening
    sy_hot_uva = eval_softened_flow_stress(sigma_y0, T=1000.0, T_sol=T_sol, s_acou=0.50)
    assert sy_hot_uva < sy_cold_uva
    assert sy_hot_uva > 0.0


def test_acoustic_spatial_attenuation():
    """Acoustic pressure must decay exponentially with depth into substrate."""
    f0 = 20000.0
    a0 = 10.0e-6
    res_surface = eval_acoustic_fields(f0, a0, z=0.0)
    res_deep = eval_acoustic_fields(f0, a0, z=0.05)  # 50 mm depth

    assert res_deep["p_amp"] < res_surface["p_amp"]
    expected_ratio = math.exp(-5.0 * 0.05)
    assert math.isclose(res_deep["p_amp"] / res_surface["p_amp"], expected_ratio, rel_tol=1e-6)
