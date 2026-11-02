"""Parity + closure tests for the shared Cp/latent curve (D3 duties).

Run:  /Users/pandeyji/py314env/bin/pytest core/test_thermal_curve.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MOOSE_ROOT = HERE.parent
FRAMEWORK = HERE.parents[1] / "waam-framework"
if not FRAMEWORK.exists():
    FRAMEWORK = HERE.parents[1] / "WAAM-Framework"
sys.path.insert(0, str(MOOSE_ROOT))
sys.path.insert(0, str(HERE))

from thermal_curve import ThermalCurve, load_material, smooth_cp_spike  # noqa: E402


def _load_edp_builder():
    builder_path = MOOSE_ROOT / "codegen" / "edp_builder.py"
    if not builder_path.exists():
        builder_path = FRAMEWORK / "codegen" / "edp_builder.py"
    spec = importlib.util.spec_from_file_location(
        "waam_edp_builder", builder_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EDP = _load_edp_builder()
db_path = MOOSE_ROOT / "core" / "multimaterial" / "material_database.json"
if not db_path.exists():
    db_path = FRAMEWORK / "core" / "multimaterial" / "material_database.json"
with open(db_path) as handle:
    ALLOYS = json.load(handle)["alloys"]
T_REF = 25.0


def _trapezoid(ts, vs):
    return sum(0.5 * (vs[i] + vs[i + 1]) * (ts[i + 1] - ts[i]) for i in range(len(ts) - 1))


@pytest.mark.parametrize("name", sorted(ALLOYS))
def test_smooth_spike_parity_with_edp_builder(name):
    cp = ALLOYS[name]["specific_heat"]
    for delta in (2.0, 1.5):
        theirs = EDP.smooth_cp_spike(list(cp["T"]), list(cp["Cp"]), delta=delta)
        ours = smooth_cp_spike(list(cp["T"]), list(cp["Cp"]), delta=delta)
        assert ours[0] == [float(t) for t in theirs[0]]
        assert ours[1] == [float(v) for v in theirs[1]]


@pytest.mark.parametrize("name", sorted(ALLOYS))
def test_smoothing_total_area_drift_bounded(name):
    # With a sloping base line (cp below the band != cp above), the ramp
    # construction of edp_builder.smooth_cp_spike shifts the table integral
    # by (base - v_next) * (W - d) / 2 per spike (algebraic identity; exact
    # zero when base == v_next).  Observed maximum across the database is
    # ~3.5e-3 relative; this test pins that bound so a regression that loses
    # or duplicates a spike cannot pass.
    cp = ALLOYS[name]["specific_heat"]
    raw = _trapezoid([float(t) for t in cp["T"]], [float(v) for v in cp["Cp"]])
    sm_t, sm_v = smooth_cp_spike(list(cp["T"]), list(cp["Cp"]))
    smoothed = _trapezoid(sm_t, sm_v)
    assert abs(smoothed - raw) / raw < 5.0e-3
    assert abs(smoothed - raw) < 1.0e4


@pytest.mark.parametrize("name", sorted(ALLOYS))
def test_enthalpy_matches_quadrature(name):
    curve = ThermalCurve.from_material(ALLOYS[name], t_ref=T_REF)
    t_hi = curve.breakpoints[0][-1]
    n = 400001
    step = (t_hi - T_REF) / (n - 1)
    quad = 0.0
    for i in range(n - 1):
        t_a = T_REF + i * step
        quad += 0.5 * (curve.cp(t_a) + curve.cp(t_a + step)) * step
    assert curve.enthalpy(t_hi) == pytest.approx(quad, rel=1e-6)


@pytest.mark.parametrize("name", sorted(ALLOYS))
def test_temperature_is_exact_inverse(name):
    curve = ThermalCurve.from_material(ALLOYS[name], t_ref=T_REF)
    t_lo, t_hi = curve.breakpoints[0][0], curve.breakpoints[0][-1]
    for i in range(500):
        t = t_lo + (t_hi - t_lo) * i / 499.0
        back = curve.temperature(curve.enthalpy(t))
        assert back == pytest.approx(t, abs=1e-6)
    beyond = t_hi + 200.0
    assert curve.temperature(curve.enthalpy(beyond)) == pytest.approx(beyond, abs=1e-6)


@pytest.mark.parametrize("name", sorted(ALLOYS))
def test_no_residual_vertical_edges(name):
    cp = ALLOYS[name]["specific_heat"]
    ts, vs = smooth_cp_spike(list(cp["T"]), list(cp["Cp"]))
    for i in range(len(ts) - 1):
        dt = ts[i + 1] - ts[i]
        if dt > 0:
            assert abs(vs[i + 1] - vs[i]) / dt < 1.0e5


def test_synthetic_box_latent_closure():
    # Flat surround (base == v_next): the spike smoothing preserves the table
    # integral EXACTLY and the full-band enthalpy equals sensible + latent.
    ts = [0.0, 1000.0, 1000.01, 1010.0, 1010.01, 1100.0]
    vs = [500.0, 500.0, 5000.0, 5000.0, 500.0, 500.0]
    raw = _trapezoid(ts, vs)
    sm_t, sm_v = smooth_cp_spike(ts, vs, delta=2.0)
    assert _trapezoid(sm_t, sm_v) == pytest.approx(raw, rel=1e-12)
    curve = ThermalCurve(sm_t, sm_v, t_ref=25.0)
    band = 1010.01 - 1000.0
    sensible = 500.0 * band
    latent = 4500.0 * 10.0
    assert curve.enthalpy(1010.01) - curve.enthalpy(1000.0) == pytest.approx(
        sensible + latent, rel=1e-9
    )


def test_from_material_fallback_without_table():
    material = {"solidus": 1400.0, "liquidus": 1460.0, "latent_heat": 270000.0}
    curve = ThermalCurve.from_material(material, t_ref=T_REF)
    band = curve.enthalpy(1460.0) - curve.enthalpy(1400.0)
    assert band == pytest.approx(650.0 * 60.0 + 270000.0, rel=1e-9)
    assert curve.enthalpy(1600.0) > curve.enthalpy(1500.0)


def test_loader_reads_database():
    material = load_material("AlSi10Mg")
    assert material["solidus"] < material["liquidus"]
    with pytest.raises(KeyError):
        load_material("Unobtainium")
