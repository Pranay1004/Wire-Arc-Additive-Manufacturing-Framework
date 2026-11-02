"""
tests/test_moose_script_generator.py

MOOSE Input Script Generator Verification Suite
================================================
Verifies that codegen/moose_builder.py generates error-free, comprehensive
MOOSE input files (.i) that compile cleanly with waam_moose-opt --check-input.
"""

import subprocess
import tempfile
from pathlib import Path
import pytest

from run import find_moose_binary
from codegen.moose_builder import main as build_moose_input

MOOSE_ROOT = Path(__file__).resolve().parent.parent
BASE_EXO = MOOSE_ROOT / "a_base_sol.e"
if not BASE_EXO.exists():
    BASE_EXO = MOOSE_ROOT / "waam_output" / "2026-10-25_01-15-44" / "moose" / "mesh.exo"


@pytest.fixture(scope="session")
def moose_bin():
    binary = find_moose_binary()
    assert binary and Path(binary).is_file(), f"waam_moose-opt binary not found: {binary}"
    return binary


def test_script_generator_thermal_syntax_check(moose_bin):
    """Thermal-only input file must pass syntax check with waam_moose-opt --check-input."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_01-15-44"
    if not (case_dir / "moose" / "waam_moose.i").exists():
        pytest.skip("Reference case waam_moose.i not found")

    i_path = case_dir / "moose" / "waam_moose.i"
    cmd = [moose_bin, "--check-input", "-i", str(i_path)]
    p = subprocess.run(cmd, cwd=str(i_path.parent), capture_output=True, text=True)
    assert p.returncode == 0, f"MOOSE input check failed with code {p.returncode}:\n{p.stderr}"
    assert "Syntax OK" in p.stdout or p.returncode == 0


def test_script_generator_mechanical_syntax_check(moose_bin):
    """Thermo-mechanical input file must register TensorMechanics, WAAMElasticityTensor, and WAAMPlasticityStressUpdate cleanly."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_03-22-30"
    if not (case_dir / "moose" / "waam_moose.i").exists():
        pytest.skip("Mechanical case waam_moose.i not found")

    i_path = case_dir / "moose" / "waam_moose.i"
    cmd = [moose_bin, "--check-input", "-i", str(i_path)]
    p = subprocess.run(cmd, cwd=str(i_path.parent), capture_output=True, text=True)
    assert p.returncode == 0, f"MOOSE mechanical check failed with code {p.returncode}:\n{p.stderr}"
    assert "Syntax OK" in p.stdout or p.returncode == 0


def test_script_generator_adaptive_dt_syntax_check(moose_bin):
    """Adaptive time-stepping (IterationAdaptiveDT) must compile with --check-input."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_03-22-30"
    if not (case_dir / "parameters.json").exists():
        pytest.skip("Reference case parameters.json not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        import shutil, json
        # Copy required artifacts
        shutil.copy2(case_dir / "parameters.json", tmp_path / "parameters.json")
        shutil.copy2(case_dir / "toolpath.txt", tmp_path / "toolpath.txt")
        shutil.copy2(case_dir / "layer_pass_times.txt", tmp_path / "layer_pass_times.txt")
        shutil.copy2(case_dir / "moose" / "mesh.exo", tmp_path / "mesh.exo")

        p = json.loads((tmp_path / "parameters.json").read_text())
        p["adaptive_dt"] = True
        p["dt_weld"] = 0.5
        p["dt_max"] = 25.0
        p["optimal_iterations"] = 4
        (tmp_path / "parameters.json").write_text(json.dumps(p, indent=2))

        ret = build_moose_input(["--run-dir", str(tmp_path)])
        assert ret == 0, "moose_builder failed for adaptive_dt"

        i_path = tmp_path / "moose" / "waam_moose.i"
        assert i_path.exists()
        content = i_path.read_text()
        assert "type = IterationAdaptiveDT" in content
        assert "dtmax = 25" in content

        cmd = [moose_bin, "--check-input", "-i", str(i_path)]
        res = subprocess.run(cmd, cwd=str(i_path.parent), capture_output=True, text=True)
        assert res.returncode == 0, f"Adaptive DT check failed:\n{res.stderr}\n{res.stdout}"


def test_script_generator_springback_syntax_check(moose_bin):
    """Multi-stage fixture release & springback relaxation must compile with --check-input."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_03-22-30"
    if not (case_dir / "parameters.json").exists():
        pytest.skip("Reference case parameters.json not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        import shutil, json
        shutil.copy2(case_dir / "parameters.json", tmp_path / "parameters.json")
        shutil.copy2(case_dir / "toolpath.txt", tmp_path / "toolpath.txt")
        shutil.copy2(case_dir / "layer_pass_times.txt", tmp_path / "layer_pass_times.txt")
        shutil.copy2(case_dir / "moose" / "mesh.exo", tmp_path / "mesh.exo")

        p = json.loads((tmp_path / "parameters.json").read_text())
        p["enable_mechanical"] = True
        p["springback_solve"] = True
        p["t_unclamp"] = 20.0
        (tmp_path / "parameters.json").write_text(json.dumps(p, indent=2))

        ret = build_moose_input(["--run-dir", str(tmp_path)])
        assert ret == 0, "moose_builder failed for springback"

        i_path = tmp_path / "moose" / "waam_moose.i"
        assert i_path.exists()
        content = i_path.read_text()
        assert "[Controls]" in content
        assert "type = TimePeriod" in content
        assert "disable_objects = 'BCs/clamp_x BCs/clamp_y BCs/clamp_z'" in content
        assert "enable_objects = 'BCs/isostatic_spring_x BCs/isostatic_spring_y BCs/isostatic_spring_z'" in content

        cmd = [moose_bin, "--check-input", "-i", str(i_path)]
        res = subprocess.run(cmd, cwd=str(i_path.parent), capture_output=True, text=True)
        assert res.returncode == 0, f"Springback input check failed:\n{res.stderr}\n{res.stdout}"


def test_script_generator_bimetallic_graded_syntax_check(moose_bin):
    """Bi-metallic SS316L to IN625 graded deposition input must compile with --check-input."""
    case_dir = MOOSE_ROOT / "waam_output" / "2026-10-25_03-22-30"
    if not (case_dir / "parameters.json").exists():
        pytest.skip("Reference case parameters.json not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        import shutil, json
        shutil.copy2(case_dir / "parameters.json", tmp_path / "parameters.json")
        shutil.copy2(case_dir / "toolpath.txt", tmp_path / "toolpath.txt")
        shutil.copy2(case_dir / "layer_pass_times.txt", tmp_path / "layer_pass_times.txt")
        shutil.copy2(case_dir / "moose" / "mesh.exo", tmp_path / "mesh.exo")

        p = json.loads((tmp_path / "parameters.json").read_text())
        p["material_base"] = "SS316L"
        p["material_dep"] = "IN625"
        p["enable_mechanical"] = True
        p["springback_solve"] = True
        p["adaptive_dt"] = True
        (tmp_path / "parameters.json").write_text(json.dumps(p, indent=2))

        ret = build_moose_input(["--run-dir", str(tmp_path)])
        assert ret == 0, "moose_builder failed for bimetallic configuration"

        i_path = tmp_path / "moose" / "waam_moose.i"
        assert i_path.exists()
        content = i_path.read_text()
        assert "Substrate SS316L / deposit IN625" in content

        cmd = [moose_bin, "--check-input", "-i", str(i_path)]
        res = subprocess.run(cmd, cwd=str(i_path.parent), capture_output=True, text=True)
        assert res.returncode == 0, f"Bi-metallic check failed:\n{res.stderr}\n{res.stdout}"
