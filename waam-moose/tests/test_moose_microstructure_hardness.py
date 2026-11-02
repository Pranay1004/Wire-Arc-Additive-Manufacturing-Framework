"""
tests/test_moose_microstructure_hardness.py

Microstructure Evolution & Vickers Hardness Verification Suite
==============================================================
Verifies phase kinetics, CCT cooling curves (Δt_8/5), and rule-of-mixtures
Vickers microhardness predictions across all primary alloy families.
"""

import math
import numpy as np
import pytest

from core.multimaterial.alloy_metallurgy import get_alloy_category, get_alloy_scheme


def compute_steel_phases_and_hv(dt85: float) -> tuple[float, float, float, float, float]:
    """CCT model for low-carbon steel (ER70S-6). Returns (fF, fP, fB, fM, HV)."""
    if dt85 < 0.1:
        fF, fP, fB, fM = 0.85, 0.15, 0.0, 0.0
    elif dt85 < 3.0:
        fM = 0.90
        fB = 0.10
        fF, fP = 0.0, 0.0
    elif dt85 < 10.0:
        fM = max(0.0, 0.90 - 0.10 * (dt85 - 3.0))
        fB = 1.0 - fM
        fF, fP = 0.0, 0.0
    elif dt85 < 50.0:
        fB = max(0.0, 1.0 - 0.02 * (dt85 - 10.0))
        fF = 1.0 - fB
        fP, fM = 0.0, 0.0
    else:
        fP = min(0.40, 0.10 + 0.006 * (dt85 - 50.0))
        fF = 1.0 - fP
        fB, fM = 0.0, 0.0

    hv = fF * 150.0 + fP * 250.0 + fB * 350.0 + fM * 550.0
    return fF, fP, fB, fM, hv


def test_steel_phase_conservation():
    """Phase fractions for carbon steel must sum to 1.0 for all cooling times."""
    for dt in [0.0, 0.5, 2.0, 5.0, 15.0, 45.0, 75.0, 150.0]:
        fF, fP, fB, fM, hv = compute_steel_phases_and_hv(dt)
        total = fF + fP + fB + fM
        assert math.isclose(total, 1.0, abs_tol=1e-6), f"At dt85={dt}s, sum={total} != 1.0"
        assert all(0.0 <= f <= 1.0 for f in (fF, fP, fB, fM)), f"Fractions out of [0, 1] at dt85={dt}s"


def test_steel_hardness_cooling_monotonicity():
    """Faster cooling (smaller Δt8/5) must produce strictly harder microstructure."""
    _, _, _, _, hv_fast = compute_steel_phases_and_hv(1.5)   # Martensite dominant
    _, _, _, _, hv_med = compute_steel_phases_and_hv(8.0)    # Mixed Bainite/Martensite
    _, _, _, _, hv_slow = compute_steel_phases_and_hv(30.0)  # Bainite/Ferrite
    _, _, _, _, hv_furnace = compute_steel_phases_and_hv(100.0) # Ferrite/Pearlite

    assert hv_fast > hv_med > hv_slow > hv_furnace, (
        f"Hardness not monotonically decreasing with cooling time: "
        f"{hv_fast:.1f} > {hv_med:.1f} > {hv_slow:.1f} > {hv_furnace:.1f}"
    )


def test_stainless_hall_petch_cell_hardening():
    """Stainless steel hardness must increase as solidification cells refine with cooling rate."""
    cr_high = 200.0  # K/s
    cr_low = 10.0    # K/s

    sdas_fine = 50.0 * (cr_high ** -0.33)
    sdas_coarse = 50.0 * (cr_low ** -0.33)

    assert sdas_fine < sdas_coarse, "Higher cooling rate must produce finer SDAS"

    hv_fine = 165.0 + 38.0 / math.sqrt(sdas_fine)
    hv_coarse = 165.0 + 38.0 / math.sqrt(sdas_coarse)

    assert hv_fine > hv_coarse, f"Fine cells ({hv_fine:.1f} HV) must be harder than coarse ({hv_coarse:.1f} HV)"
    assert 165.0 <= hv_fine <= 220.0, "Stainless hardness must be within physical engineering bounds"


def test_titanium_martensite_critical_rate():
    """Ti-6Al-4V above critical cooling rate (410 °C/s) must form hard acicular α' martensite."""
    scheme = get_alloy_scheme("Ti-6Al-4V")
    assert scheme["category_id"] == "titanium"
    phases = [p["short"] for p in scheme["phases"]]
    assert "Martensite α'" in phases
    assert any("Transf" in p for p in phases)


def test_dt85_extraction_synthetic_curve():
    """Verify Δt8/5 extraction algorithm on an exponential cooling curve."""
    times = np.linspace(0.0, 100.0, 1001)
    # T(t) heats to 2000 C at t=10s, then cools exponentially: T(t) = 25 + 1975 * exp(-(t-10)/20)
    T = np.zeros_like(times)
    for i, t in enumerate(times):
        if t <= 10.0:
            T[i] = 25.0 + (1975.0 / 10.0) * t
        else:
            T[i] = 25.0 + 1975.0 * math.exp(-(t - 10.0) / 20.0)

    # Analytical t800 and t500
    # 800 = 25 + 1975 * exp(-(t800 - 10)/20) -> t800 = 10 - 20 * ln(775/1975)
    t800_exact = 10.0 - 20.0 * math.log(775.0 / 1975.0)
    t500_exact = 10.0 - 20.0 * math.log(475.0 / 1975.0)
    dt85_exact = t500_exact - t800_exact

    # Numerical interpolation
    max_idx = int(np.argmax(T))
    cool_t = times[max_idx:]
    cool_T = T[max_idx:]
    t800_num, t500_num = None, None
    for j in range(len(cool_T) - 1):
        if cool_T[j] >= 800.0 and cool_T[j + 1] < 800.0:
            frac = (800.0 - cool_T[j + 1]) / (cool_T[j] - cool_T[j + 1])
            t800_num = cool_t[j + 1] + frac * (cool_t[j] - cool_t[j + 1])
        if cool_T[j] >= 500.0 and cool_T[j + 1] < 500.0:
            frac = (500.0 - cool_T[j + 1]) / (cool_T[j] - cool_T[j + 1])
            t500_num = cool_t[j + 1] + frac * (cool_t[j] - cool_t[j + 1])

    dt85_num = t500_num - t800_num
    assert math.isclose(dt85_num, dt85_exact, rel_tol=1e-3), f"dt85 {dt85_num:.3f}s != exact {dt85_exact:.3f}s"
