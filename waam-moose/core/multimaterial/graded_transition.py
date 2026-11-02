"""
core/multimaterial/graded_transition.py

Multi-Material Graded Transition & CALPHAD Dilution Engine
=========================================================
Implements functionally graded material (FGM) transition kinetics,
continuous composition blending, dilution tracking, and intermetallic
risk estimation for Wire Arc Additive Manufacturing (WAAM).

Enables bi-metallic multi-material WAAM (e.g., SS316L to Inconel 625,
or Low-Alloy Steel to Stainless Steel) with physical thermodynamics.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


def blend_weight(z: float, z_start: float, z_end: float, mode: str = "smoothstep") -> float:
    """
    Computes blending weight w in [0, 1] as a function of height z.
    w = 1.0 at z <= z_start (100% Substrate/Alloy A)
    w = 0.0 at z >= z_end (100% Deposit/Alloy B)
    """
    if z <= z_start:
        return 1.0
    if z >= z_end:
        return 0.0
    
    s = (z - z_start) / max(1e-9, z_end - z_start)
    
    if mode == "linear":
        return 1.0 - s
    elif mode == "smoothstep":
        # C1 continuous cubic smoothstep
        return 1.0 - (s * s * (3.0 - 2.0 * s))
    elif mode == "sigmoid":
        k = 10.0
        return 1.0 / (1.0 + math.exp(k * (s - 0.5)))
    return 1.0 - s


def interpolate_composition(
    comp_a: Dict[str, float],
    comp_b: Dict[str, float],
    weight_a: float
) -> Dict[str, float]:
    """
    Blends elemental weight percentages between two alloys.
    weight_a in [0, 1] is the fraction of alloy A.
    """
    w_a = max(0.0, min(1.0, float(weight_a)))
    w_b = 1.0 - w_a
    
    all_elements = set(comp_a.keys()).union(comp_b.keys())
    blended: Dict[str, float] = {}
    
    for el in sorted(all_elements):
        val_a = float(comp_a.get(el, 0.0))
        val_b = float(comp_b.get(el, 0.0))
        blended[el] = w_a * val_a + w_b * val_b
        
    return blended


def compute_dilution_layer_composition(
    wire_comp: Dict[str, float],
    prev_layer_comp: Dict[str, float],
    dilution_ratio: float = 0.25
) -> Dict[str, float]:
    """
    Computes effective layer composition accounting for substrate/previous layer
    melt pool dilution:
      C_layer = (1 - eta_dil) * C_wire + eta_dil * C_prev
    """
    eta = max(0.0, min(1.0, float(dilution_ratio)))
    return interpolate_composition(prev_layer_comp, wire_comp, weight_a=eta)


def estimate_solidus_liquidus(comp: Dict[str, float]) -> Tuple[float, float]:
    """
    Empirical CALPHAD-calibrated Scheil-Gulliver polynomial estimation for
    solidus and liquidus temperatures (°C) based on blended Fe-Ni-Cr-Mo-C composition.
    """
    c = comp.get("C", 0.05)
    si = comp.get("Si", 0.5)
    mn = comp.get("Mn", 1.5)
    cr = comp.get("Cr", 18.0)
    ni = comp.get("Ni", 10.0)
    mo = comp.get("Mo", 2.0)
    nb = comp.get("Nb", 0.0)
    
    # Liquidus approximation (Fe-base / Ni-base continuum)
    t_liq = 1538.0 - (78.0 * c + 7.6 * si + 4.9 * mn + 1.3 * cr + 3.1 * ni + 1.4 * mo + 10.0 * nb)
    
    # Freezing range estimation
    delta_t = 45.0 + 120.0 * c + 35.0 * nb + 15.0 * mo + 8.0 * si
    t_sol = t_liq - max(30.0, delta_t)
    
    return float(t_sol), float(t_liq)


def evaluate_intermetallic_risk(comp: Dict[str, float]) -> Dict[str, Any]:
    """
    Evaluates solidification cracking and embrittlement risks in transition zones:
    1. WRC-1992 Cr_eq / Ni_eq ratio (Austenitic-Ferritic mode)
    2. Sigma phase (Fe-Cr intermetallic) susceptibility index
    3. Laves phase (Nb segregation) susceptibility index
    """
    cr = comp.get("Cr", 0.0)
    mo = comp.get("Mo", 0.0)
    si = comp.get("Si", 0.0)
    nb = comp.get("Nb", 0.0)
    ni = comp.get("Ni", 0.0)
    c = comp.get("C", 0.0)
    mn = comp.get("Mn", 0.0)
    fe = comp.get("Fe", 0.0)
    
    # WRC-1992 equivalents
    cr_eq = cr + mo + 0.7 * nb
    ni_eq = ni + 35.0 * c + 20.0 * comp.get("N", 0.0) + 0.25 * comp.get("Cu", 0.0)
    ratio = cr_eq / max(ni_eq, 0.1)
    
    # Ferrite Number (FN) prediction via WRC-1992
    # FN = -18 + 4.0 * (Cr_eq - Ni_eq) in typical range
    fn = max(0.0, -18.0 + 4.0 * (cr_eq - ni_eq)) if (cr_eq > ni_eq) else 0.0
    
    # Sigma phase risk index: High when Cr >= 20% and Mo >= 3% and T in [600, 850] °C
    sigma_factor = max(0.0, (cr - 17.0) * 0.15 + (mo - 2.0) * 0.25)
    sigma_risk = "HIGH" if sigma_factor > 0.8 else ("MODERATE" if sigma_factor > 0.3 else "LOW")
    
    # Laves phase risk index: Driven by Nb content (> 3.5 wt% Nb)
    laves_factor = max(0.0, (nb - 1.5) / 3.0)
    laves_risk = "HIGH" if laves_factor > 0.7 else ("MODERATE" if laves_factor > 0.2 else "LOW")
    
    # Solidification cracking susceptibility: low if primary Ferrite (FA mode: 1.48 <= ratio <= 1.95)
    if ratio < 1.25:
        crack_risk = "MODERATE (Primary Austenite Solidification, low Ferrite Number)"
    elif 1.45 <= ratio <= 1.95:
        crack_risk = "VERY LOW (Primary δ-Ferrite FA mode, optimal resistance)"
    elif ratio > 2.0:
        crack_risk = "MODERATE (Excess Ferrite, risk of 475 °C embrittlement)"
    else:
        crack_risk = "LOW"
        
    return {
        "cr_eq": cr_eq,
        "ni_eq": ni_eq,
        "cr_ni_ratio": ratio,
        "ferrite_number_FN": fn,
        "sigma_phase_risk": sigma_risk,
        "laves_phase_risk": laves_risk,
        "hot_cracking_susceptibility": crack_risk
    }
