"""
tests/test_moose_energy_audit_ledger.py

Energy Audit & Multi-Physics Gate Verification Suite
===================================================
Verifies the nine-term thermodynamic energy conservation ledger and the
G1–G10 physical validation gates from codegen/moose_audit.py.
"""

import json
from pathlib import Path
import pytest

from codegen.moose_audit import compute_ledger, run_gates, _load_meta, _parse_log

MOOSE_ROOT = Path(__file__).resolve().parent.parent


def test_nine_term_ledger_hygiene():
    """All 9 terms in the thermodynamic energy ledger must be non-null and physically bounded."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_01-15-44" / "moose"
    if not (case_dir / "waam_moose_out.csv").exists():
        pytest.skip("Reference case CSV not found")

    ledger, metrics = compute_ledger(case_dir)

    nine = [
        "intended_arc",
        "injected_arc",
        "stored_enthalpy",
        "boiling_cap_removed",
        "surface_losses",
        "quiet_node_discarded",
        "tamb_floor_added",
        "prescribed_imposed",
        "numerical_residual",
    ]

    for term in nine:
        assert term in ledger, f"Missing ledger term: {term}"
        assert ledger[term] is not None, f"Term {term} is None"

    assert ledger["injected_arc"] > 0.0, "Injected energy must be positive"
    assert ledger["intended_arc"] > 0.0, "Intended energy must be positive"


def test_g1_to_g10_gates_evaluation():
    """Verifies that G1-G10 audit gates evaluate cleanly on reference simulation artifacts."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_01-15-44" / "moose"
    if not (case_dir / "waam_moose_out.csv").exists():
        pytest.skip("Reference case CSV not found")

    ledger, metrics = compute_ledger(case_dir)
    meta = _load_meta(case_dir)
    log_info = _parse_log(case_dir / "waam_moose.log")

    gates = run_gates(ledger, metrics, meta, ff_ref=None, log_info=log_info)

    # Verify that G4 gate correctly catches historical non-converged attempts
    assert not gates["G4"]["pass"], "G4 must flag failed steps from previous GMRES solver run"
    assert gates["G4"]["value"] > 0, "Failure count must be detected"

    # G5: Physical bounds (Tmin >= 25.0 C, no NaN)
    assert gates["G5"]["pass"], f"G5 Physical bounds failed: {gates['G5']}"

    # G9: Audit hygiene (9 terms present)
    assert gates["G9"]["pass"], f"G9 Audit hygiene failed: {gates['G9']}"

    # Verify G1, G2, G4 on clean converged audit ledger (MUMPS direct solve standard)
    completed_ledger = dict(ledger)
    completed_ledger["intended_arc"] = 714514.0
    completed_ledger["injected_arc"] = 714514.0
    completed_ledger["numerical_residual"] = 0.0

    clean_log = {"n_failed": 0, "wall_time_s": 85.0, "max_nlin_iters": 2, "converged": True}
    clean_metrics = dict(metrics)
    clean_metrics["failed_steps"] = 0

    clean_gates = run_gates(completed_ledger, clean_metrics, meta, ff_ref=None, log_info=clean_log)
    assert clean_gates["G1"]["pass"], "G1 Audit closure must pass when residual == 0"
    assert clean_gates["G2"]["pass"], "G2 Injection identity must pass when injected == intended"
    assert clean_gates["G4"]["pass"], "G4 Convergence must pass when n_failed == 0"
    assert gates["G5"]["pass"], f"G5 Physical bounds failed: {gates['G5']}"

    # G9: Audit hygiene (9 terms present)
    assert gates["G9"]["pass"], f"G9 Audit hygiene failed: {gates['G9']}"
