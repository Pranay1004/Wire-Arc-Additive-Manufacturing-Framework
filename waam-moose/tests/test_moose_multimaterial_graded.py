"""
tests/test_moose_multimaterial_graded.py

Multi-Material Graded Transition & Dilution Verification Suite
==============================================================
Verifies functionally graded materials (FGM), continuous composition
interpolation, layer dilution tracking, and intermetallic risk estimation.
"""

import pytest
from core.multimaterial.graded_transition import (
    blend_weight,
    interpolate_composition,
    compute_dilution_layer_composition,
    estimate_solidus_liquidus,
    evaluate_intermetallic_risk,
)


def test_blend_weight_bounds_and_continuity():
    """Blending weights must start at 1.0, end at 0.0, and remain strictly in [0, 1]."""
    z0, z1 = 0.0, 20.0

    for mode in ["linear", "smoothstep", "sigmoid"]:
        w_start = blend_weight(z0, z0, z1, mode)
        w_end = blend_weight(z1, z0, z1, mode)
        assert w_start == 1.0
        assert w_end == 0.0

        prev_w = 1.0
        for z in [2.0, 5.0, 10.0, 15.0, 18.0]:
            w = blend_weight(z, z0, z1, mode)
            assert 0.0 <= w <= 1.0
            assert w <= prev_w, f"{mode}: non-monotonic weight at z={z}"
            prev_w = w


def test_composition_interpolation():
    """Interpolating 50/50 between two alloys must equal exact arithmetic average."""
    alloy_a = {"Fe": 70.0, "Cr": 18.0, "Ni": 12.0}
    alloy_b = {"Ni": 60.0, "Cr": 22.0, "Mo": 9.0, "Fe": 9.0}

    mid = interpolate_composition(alloy_a, alloy_b, weight_a=0.50)
    assert mid["Fe"] == 0.5 * 70.0 + 0.5 * 9.0
    assert mid["Cr"] == 0.5 * 18.0 + 0.5 * 22.0
    assert mid["Ni"] == 0.5 * 12.0 + 0.5 * 60.0
    assert mid["Mo"] == 0.5 * 0.0 + 0.5 * 9.0


def test_layer_dilution_steady_state():
    """Repeated deposition with constant wire and dilution ratio must converge to wire composition."""
    wire = {"Cr": 20.0, "Ni": 10.0, "Fe": 70.0}
    substrate = {"Cr": 0.0, "Ni": 0.0, "Fe": 100.0}

    curr = substrate
    eta_dil = 0.30  # 30% dilution per layer
    for layer in range(1, 15):
        curr = compute_dilution_layer_composition(wire, curr, dilution_ratio=eta_dil)

    # After 14 layers, Cr should be very close to 20.0%
    assert abs(curr["Cr"] - wire["Cr"]) < 0.01, f"Layer 14 Cr={curr['Cr']:.2f}% did not converge to wire 20.0%"


def test_solidus_liquidus_freezing_range():
    """Liquidus must be strictly higher than solidus for any steel or nickel alloy."""
    comps = [
        {"C": 0.02, "Cr": 17.5, "Ni": 12.0, "Mo": 2.5, "Fe": 68.0},  # SS316L
        {"C": 0.03, "Cr": 21.5, "Ni": 61.0, "Mo": 9.0, "Nb": 3.6},   # IN625
        {"C": 0.15, "Mn": 1.4, "Si": 0.4, "Fe": 98.0},               # Carbon steel
    ]
    for c in comps:
        tsol, tliq = estimate_solidus_liquidus(c)
        assert tliq > tsol, f"Tliq ({tliq:.1f} °C) must be greater than Tsol ({tsol:.1f} °C)"
        assert tliq - tsol >= 30.0, "Freezing range must be >= 30 °C"


def test_intermetallic_risk_evaluation():
    """Intermetallic indicators must flag high risk for high Nb (Laves) and high Cr+Mo (Sigma)."""
    # High Nb superalloy
    high_nb = {"Ni": 60.0, "Cr": 20.0, "Mo": 8.0, "Nb": 4.5, "Fe": 5.0}
    risk_nb = evaluate_intermetallic_risk(high_nb)
    assert risk_nb["laves_phase_risk"] == "HIGH"

    # Standard SS316L (low Nb, moderate Cr)
    standard_316 = {"Fe": 68.0, "Cr": 17.5, "Ni": 12.0, "Mo": 2.5, "Nb": 0.0}
    risk_316 = evaluate_intermetallic_risk(standard_316)
    assert risk_316["laves_phase_risk"] == "LOW"


def test_bimetallic_graded_report_rendering(tmp_path):
    """Bi-metallic 4-panel report rendering must output 09_bimetallic_graded_transition.png with valid metrics."""
    from postprocess.report_generator import _render_bimetallic_graded_transition
    p = {
        "material_base": "SS316L",
        "material_dep": "IN625",
        "hz_base": 0.005,
        "h_bead": 0.003,
        "n_layers": 4,
    }
    plots_dir = tmp_path / "plots"
    plots_dir.mkdir()
    res = _render_bimetallic_graded_transition(p, plots_dir)
    assert res.get("valid") is True
    assert res["base_alloy"] == "SS316L"
    assert res["deposit_alloy"] == "IN625"
    assert (plots_dir / "09_bimetallic_graded_transition.png").exists()
    assert res["cr_eq_deposit"] > 20.0
    assert res["ni_eq_deposit"] > 50.0
