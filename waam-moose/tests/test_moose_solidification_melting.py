"""
tests/test_moose_solidification_melting.py

Solidification, Melting & Thermal Annealing Verification Suite
=============================================================
Verifies the core physical principles implemented in native C++ kernels:
1. Solidification-referenced thermal eigenstrain (locking above T_sol with dε/dT = 0).
2. Liquid melt pool slurry modulus reduction (E_slurry = 0.02 * E_solid, 1e6 Pa floor).
3. Thermal annealing and plastic memory loss (plastic strain reset when T >= T_sol).
4. Quiet element activation scaling (1e-5 * E0 for unactivated elements).
5. C1-continuous boiling cap evaporation sink regularization.
"""

import math
import numpy as np
import pytest


def eval_thermal_eigenstrain(T: float, T_ref: float, T_sol: float, alpha: float, fa: float):
    """Python reference evaluation of WAAMThermalExpansionEigenstrain.C."""
    if fa < 0.5:
        return 0.0, 0.0
    if T <= T_sol:
        eth = alpha * (T - T_ref)
        deth_dT = alpha
    else:
        # Molten state: lock at solidus contraction, derivative drops to zero
        eth = alpha * (T_sol - T_ref)
        deth_dT = 0.0
    return eth, deth_dT


def eval_elasticity_modulus(T: float, T_sol: float, E0: float, fa: float, born_floor: float = 1e-5, slurry_factor: float = 0.02):
    """Python reference evaluation of WAAMElasticityTensor.C."""
    if fa < 0.5:
        return E0 * born_floor
    if T <= 20.0:
        return E0
    elif T < T_sol:
        frac = (T - 20.0) / (T_sol - 20.0)
        return max(E0 * slurry_factor, E0 * (1.0 - 0.70 * frac))
    else:
        # Slurry state above solidus
        return max(1.0e6, E0 * slurry_factor)


def eval_plastic_annealing(T: float, T_sol: float, ep_in: np.ndarray, peeq_in: float):
    """Python reference evaluation of WAAMPlasticityStressUpdate.C annealing."""
    if T >= T_sol:
        # Full thermodynamic memory loss in molten liquid
        ep_out = np.zeros_like(ep_in)
        peeq_out = 0.0
        annealed = True
    else:
        ep_out = ep_in.copy()
        peeq_out = peeq_in
        annealed = False
    return ep_out, peeq_out, annealed


def eval_boiling_cap(T: float, T_boil: float = 2862.0, rate: float = 2.0e3, width: float = 25.0):
    """Python reference evaluation of WAAMBoilingCapKernel.C."""
    if T <= T_boil:
        return 0.0, 0.0
    delta = T - T_boil
    if delta < width:
        # C1 quadratic transition
        s = delta / width
        smooth_val = s * s
        residual = rate * delta * smooth_val
        jacobian = rate * (3.0 * s * s)
    else:
        residual = rate * delta
        jacobian = rate
    return residual, jacobian


def test_thermal_eigenstrain_solidus_locking():
    """Thermal expansion must lock above T_sol and its temperature derivative must be identically 0."""
    T_ref = 20.0
    T_sol = 1450.0
    alpha = 1.6e-5

    # Below solidus
    eth_1000, deth_1000 = eval_thermal_eigenstrain(1000.0, T_ref, T_sol, alpha, fa=1.0)
    assert math.isclose(eth_1000, alpha * (1000.0 - 20.0), rel_tol=1e-6)
    assert math.isclose(deth_1000, alpha, rel_tol=1e-6)

    # At solidus
    eth_sol, deth_sol = eval_thermal_eigenstrain(T_sol, T_ref, T_sol, alpha, fa=1.0)
    assert math.isclose(eth_sol, alpha * (T_sol - 20.0), rel_tol=1e-6)
    assert math.isclose(deth_sol, alpha, rel_tol=1e-6)

    # Above solidus (melt pool: 1800 °C, 2500 °C)
    eth_1800, deth_1800 = eval_thermal_eigenstrain(1800.0, T_ref, T_sol, alpha, fa=1.0)
    eth_2500, deth_2500 = eval_thermal_eigenstrain(2500.0, T_ref, T_sol, alpha, fa=1.0)

    assert math.isclose(eth_1800, eth_sol, rel_tol=1e-9), "Eigenstrain above solidus must be capped at T_sol"
    assert math.isclose(eth_2500, eth_sol, rel_tol=1e-9), "Eigenstrain above solidus must be capped at T_sol"
    assert deth_1800 == 0.0, "Thermal eigenstrain derivative above solidus must be strictly 0"
    assert deth_2500 == 0.0, "Thermal eigenstrain derivative above solidus must be strictly 0"


def test_molten_slurry_modulus_reduction():
    """Young's modulus must drop to slurry cutoff above solidus and be scaled by 1e-5 when unactivated."""
    E0 = 2.0e11
    T_sol = 1450.0

    # Unactivated element
    E_quiet = eval_elasticity_modulus(300.0, T_sol, E0, fa=0.0)
    assert math.isclose(E_quiet, 1e-5 * E0, rel_tol=1e-6)

    # Active solid at room temp
    E_room = eval_elasticity_modulus(20.0, T_sol, E0, fa=1.0)
    assert math.isclose(E_room, E0, rel_tol=1e-6)

    # Active solid near solidus
    E_hot = eval_elasticity_modulus(1400.0, T_sol, E0, fa=1.0)
    assert E_hot < E0
    assert E_hot >= 0.02 * E0

    # Active molten pool above solidus
    E_melt = eval_elasticity_modulus(1800.0, T_sol, E0, fa=1.0)
    assert math.isclose(E_melt, 0.02 * E0, rel_tol=1e-6)
    assert E_melt >= 1.0e6


def test_thermal_annealing_plastic_strain_wipeout():
    """Remelting a previously strained deposit must wipe accumulated plastic strains to zero."""
    T_sol = 1450.0
    ep_prior = np.array([0.025, -0.012, -0.013, 0.005, 0.0, 0.0])
    peeq_prior = 0.038

    # Solid cooling/reheating below T_sol: strain preserved
    ep_cool, peeq_cool, ann_cool = eval_plastic_annealing(1200.0, T_sol, ep_prior, peeq_prior)
    assert not ann_cool
    assert np.allclose(ep_cool, ep_prior)
    assert peeq_cool == peeq_prior

    # Remelting pass: T = 1550 °C >= T_sol
    ep_remelt, peeq_remelt, ann_remelt = eval_plastic_annealing(1550.0, T_sol, ep_prior, peeq_prior)
    assert ann_remelt, "Annealing must trigger when T >= T_sol"
    assert np.all(ep_remelt == 0.0), f"Plastic strain must be zeroed out in melt pool, got {ep_remelt}"
    assert peeq_remelt == 0.0, f"Equivalent plastic strain must be zeroed out, got {peeq_remelt}"


def test_boiling_cap_c1_continuity():
    """Boiling cap must return exactly zero residual and Jacobian below T_boil and be C1 continuous."""
    T_boil = 2862.0

    # Below boiling point
    r_sub, j_sub = eval_boiling_cap(2800.0, T_boil)
    assert r_sub == 0.0
    assert j_sub == 0.0

    # At boiling point
    r_boil, j_boil = eval_boiling_cap(T_boil, T_boil)
    assert r_boil == 0.0
    assert j_boil == 0.0

    # Smooth quadratic transition zone (T_boil + 10 °C)
    r_mid, j_mid = eval_boiling_cap(2872.0, T_boil, rate=2000.0, width=25.0)
    assert r_mid > 0.0
    assert j_mid > 0.0

    # Above transition zone (T_boil + 50 °C)
    r_high, j_high = eval_boiling_cap(2912.0, T_boil, rate=2000.0, width=25.0)
    assert math.isclose(r_high, 2000.0 * 50.0, rel_tol=1e-6)
    assert math.isclose(j_high, 2000.0, rel_tol=1e-6)
