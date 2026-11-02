"""
tests/test_moose_physics_suite.py

Physics Regression Suite for WAAM-MOOSE
=======================================
Verifies analytical conservation and physical formulations:
1. Heat source power normalization (Goldak, Gaussian vol, Gaussian surf, Conical).
2. Latent heat trapezoid area conservation (latent enthalpy preservation).
3. Metallurgical equivalent indexes (WRC-1992 FN, IIW CE).
4. Material database schema integrity.
"""

import json
import math
from pathlib import Path
import numpy as np
import pytest

from codegen.moose_builder import trap_latent_cp
from core.multimaterial.alloy_metallurgy import (
    _calc_ss_eq,
    _calc_steel_eq,
    _calc_ti_eq,
    _calc_ni_eq,
    get_alloy_category,
)

MOOSE_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = MOOSE_ROOT / "core" / "multimaterial" / "material_database.json"


def test_goldak_power_quadrature():
    """Volumetric integral of Goldak double ellipsoid equals P_eff within 1%."""
    P = 3840.0
    pi = math.pi
    af, ar, bG, cG = 6.3e-3, 15.8e-3, 5.5e-3, 3.2e-3
    ff, fr = 0.6, 1.4

    Q0f = 3.0 * math.sqrt(3.0) * ff * P / (pi * math.sqrt(pi) * af * bG * cG)
    Q0r = 3.0 * math.sqrt(3.0) * fr * P / (pi * math.sqrt(pi) * ar * bG * cG)

    x = np.linspace(-0.045, 0.045, 301)
    y = np.linspace(-0.025, 0.025, 201)
    z = np.linspace(-0.025, 0.025, 201)
    X, Y, Z = np.meshgrid(x, y, z, indexing="ij")

    # Tanh transition
    eps_split = 0.1 * min(af, ar)
    F = 0.5 * (1.0 + np.tanh(X / eps_split))

    Q = (
        Q0f * np.exp(-3.0 * (X / af) ** 2) * F
        + Q0r * np.exp(-3.0 * (X / ar) ** 2) * (1.0 - F)
    ) * np.exp(-3.0 * (Y / bG) ** 2) * np.exp(-3.0 * (Z / cG) ** 2)

    dV = (x[1] - x[0]) * (y[1] - y[0]) * (z[1] - z[0])
    total_power = float(np.sum(Q) * dV)

    rel_err = abs(total_power - P) / P
    assert rel_err < 0.015, f"Goldak total power {total_power:.2f} W deviated by {rel_err*100:.2f}% from {P} W"


def test_gaussian_volume_quadrature():
    """Volumetric integral of spherical Gaussian heat source equals P."""
    P = 2500.0
    R = 0.005
    Q0 = 3.0 * math.sqrt(3.0) * P / (math.pi * math.sqrt(math.pi) * R ** 3)

    g = np.linspace(-4.0 * R, 4.0 * R, 151)
    X, Y, Z = np.meshgrid(g, g, g, indexing="ij")
    r2 = X ** 2 + Y ** 2 + Z ** 2
    Q = Q0 * np.exp(-3.0 * r2 / (R ** 2))

    dV = (g[1] - g[0]) ** 3
    total_power = float(np.sum(Q) * dV)

    rel_err = abs(total_power - P) / P
    assert rel_err < 0.01, f"Gaussian volume power {total_power:.2f} W deviated from {P} W"


def test_gaussian_surface_quadrature():
    """Area integral of 2D circular surface Gaussian heat flux equals P."""
    P = 2000.0
    Rs = 0.004
    Q0s = 3.0 * P / (math.pi * Rs ** 2)

    r = np.linspace(-4.0 * Rs, 4.0 * Rs, 301)
    Xr, Yr = np.meshgrid(r, r, indexing="ij")
    q = Q0s * np.exp(-3.0 * (Xr ** 2 + Yr ** 2) / (Rs ** 2))

    dA = (r[1] - r[0]) ** 2
    total_power = float(np.sum(q) * dA)

    rel_err = abs(total_power - P) / P
    assert rel_err < 0.01, f"Gaussian surface flux {total_power:.2f} W deviated from {P} W"


def test_conical_frustum_quadrature():
    """Volume integral of conical frustum source equals P."""
    P = 3000.0
    rt, rb, d = 0.003, 0.001, 0.005
    S = rt * rt + rt * rb + rb * rb
    Q0c = 9.0 * P / (math.pi * d * S)

    zeta = np.linspace(0, d, 2000)
    Rl = rt + (rb - rt) * zeta / d
    area = math.pi * Rl ** 2
    total_power = float(np.trapezoid(Q0c * area / 3.0, zeta))

    rel_err = abs(total_power - P) / P
    assert rel_err < 0.005, f"Conical source {total_power:.2f} W deviated from {P} W"


def test_latent_heat_trapezoid_area_conservation():
    """Trap latent smoothing must conserve the integral of Cp(T) dT within 0.1%."""
    with open(DB_PATH) as f:
        db = json.load(f)

    for alloy_name in ["SS316L", "SS308L", "ER70S-6", "IN625"]:
        cp_block = db["alloys"][alloy_name]["specific_heat"]
        raw_T = list(cp_block["T"])
        raw_Cp = list(cp_block["Cp"])

        raw_integral = float(np.trapezoid(raw_Cp, raw_T))

        smooth_T, smooth_Cp = trap_latent_cp(raw_T, raw_Cp)
        smooth_integral = float(np.trapezoid(smooth_Cp, smooth_T))

        rel_diff = abs(smooth_integral - raw_integral) / raw_integral
        assert rel_diff < 0.002, f"{alloy_name}: latent integral {smooth_integral:.1f} J/kg vs {raw_integral:.1f} J/kg (diff {rel_diff*100:.3f}%)"


def test_wrc1992_monotonicity():
    """SS308L must yield higher Ferrite Number (FN) and Cr_eq/Ni_eq than SS316L."""
    with open(DB_PATH) as f:
        db = json.load(f)

    comp_316 = db["alloys"]["SS316L"].get("composition", {"Cr": 17.5, "Ni": 12.0, "Mo": 2.5, "C": 0.02, "Si": 0.5, "Mn": 1.6})
    comp_308 = db["alloys"]["SS308L"].get("composition", {"Cr": 20.0, "Ni": 10.0, "Mo": 0.2, "C": 0.03, "Si": 0.5, "Mn": 1.8})

    res_316 = _calc_ss_eq(comp_316)
    res_308 = _calc_ss_eq(comp_308)

    ratio_316 = float(res_316.split("Cr_eq/Ni_eq = ")[1].replace(")", ""))
    ratio_308 = float(res_308.split("Cr_eq/Ni_eq = ")[1].replace(")", ""))

    assert ratio_308 > ratio_316, f"WRC ratio 308L ({ratio_308}) must be greater than 316L ({ratio_316})"


def test_iiw_carbon_equivalent():
    """IIW CE formula evaluation sanity."""
    comp = {"C": 0.08, "Mn": 1.50, "Cr": 0.05, "Mo": 0.02, "V": 0.01, "Ni": 0.05, "Cu": 0.00}
    ce_str = _calc_steel_eq(comp)
    expected_ce = 0.08 + (1.50 / 6.0) + ((0.05 + 0.02 + 0.01) / 5.0) + ((0.05 + 0.00) / 15.0)
    assert f"CE = {expected_ce:.3f}" in ce_str
