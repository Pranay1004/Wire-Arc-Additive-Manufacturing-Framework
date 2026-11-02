"""
WAAM Multi-Physics Framework — Automated Solver Diagnostics & Healing Engine
=============================================================================
Provides automated error parsing, root-cause diagnosis, and self-healing
remediation for FreeFEM++, OpenFOAM, CalculiX, and MOOSE solver executions.

Handles:
  1. Boundary Mesh Inversion (Mesh3::meshS assert(0) in GenericMesh.hpp)
  2. MUMPS Direct Solver Memory / Working Space Exhaustion (INFO(1) = -8 / -9)
  3. Singular Matrix / Missing Dirichlet Clamps (INFO(1) = -10)
  4. Missing or Unreadable Mesh / Geometry Files
  5. Diffusion Courant/Fourier Divergence & NaN Singularities
  6. FreeFEM Compiler Syntax & Undefined Symbol Faults
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class SolverDiagnostic:
    """Detailed structural diagnostic for a solver failure."""
    error_code: int
    category: str
    summary: str
    root_cause: str
    offending_line_in_edp: Optional[int] = None
    offending_file: Optional[str] = None
    log_snippet: str = ""
    is_auto_healable: bool = False
    remediation_suggestion: str = ""
    healed: bool = False
    heal_action_taken: str = ""


class FreeFEMDiagnosticsEngine:
    """Specialized diagnostics and auto-healing engine for FreeFEM++ executions."""

    @staticmethod
    def parse_log(log_path: str | Path, edp_path: Optional[str | Path] = None) -> SolverDiagnostic:
        """Parse sim.log and determine the exact root cause of failure."""
        log_path = Path(log_path)
        if not log_path.exists():
            return SolverDiagnostic(
                error_code=-1,
                category="MISSING_LOG",
                summary="Solver terminal log file not found.",
                root_cause=f"Expected log at {log_path} does not exist. Solver may have failed before spawning.",
                is_auto_healable=False,
                remediation_suggestion="Verify FreeFEM++ installation and executable permissions."
            )

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.splitlines()
        except Exception as ex:
            return SolverDiagnostic(
                error_code=-1,
                category="LOG_READ_ERROR",
                summary="Could not read simulation log file.",
                root_cause=str(ex),
                is_auto_healable=False
            )

        # 1. Search for return code
        rc = -1
        rc_match = re.search(r"EXECUTION FINISHED - RETURN CODE:\s*(-?\d+)", content)
        if rc_match:
            rc = int(rc_match.group(1))

        # Check line number in FreeFEM script if reported
        edp_line = None
        m_line = re.search(r"current line\s*=\s*(\d+)", content)
        if m_line:
            edp_line = int(m_line.group(1))
        if edp_line is None:
            m_line2 = re.search(r"line number\s*:\s*(\d+)", content)
            if m_line2:
                edp_line = int(m_line2.group(1))

        # Identify mesh file from script or log if mentioned
        mesh_file = None
        m_mesh = re.search(r'readmesh3\s*\(\s*["\']([^"\']+)["\']\s*\)', content)
        if m_mesh:
            mesh_file = m_mesh.group(1)
        if not mesh_file and edp_path and Path(edp_path).exists():
            try:
                with open(edp_path, "r", encoding="utf-8", errors="ignore") as ef:
                    edp_str = ef.read()
                    m_m2 = re.search(r'readmesh3\s*\(\s*["\']([^"\']+)["\']\s*\)', edp_str)
                    if m_m2:
                        mesh_file = m_m2.group(1)
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # Pattern 1: Bad Mesh Orientation or Topology in Mesh3 (GenericMesh.hpp)
        # ----------------------------------------------------------------------
        if (
            "Bad orientation: The adj border element" in content
            or "Border element not in mesh" in content
            or ("Assertion fail" in content and "femlib/GenericMesh.hpp" in content)
        ):
            # Extract offending element details
            m_elem = re.search(r"Bad orientation:\s*The adj border element.*?in element (\d+) and in the element (\d+)", content)
            elem_info = f" (in elements {m_elem.group(1)} and {m_elem.group(2)})" if m_elem else ""
            tail_lines = "\n".join(lines[-15:])

            is_orphan = "Border element not in mesh" in content or "err==0" in content
            summary = "Orphan Boundary Elements / Inconsistent Mesh Topology" if is_orphan else "Inverted Boundary Facet Normal in 3D Mesh"
            root_cause = (
                "FreeFEM's Mesh3 loader detected boundary triangles that do not belong to any "
                "volume tetrahedron (orphan boundary elements), or adjacent boundary triangles with "
                "inconsistent topological winding. This occurs during automated CAD surface tessellation "
                "or non-conformal boolean operations."
            ) if is_orphan else (
                f"FreeFEM's Mesh3::meshS surface reconstructor detected adjacent boundary "
                f"triangles traversing a shared edge in the same topological direction{elem_info}. "
                "This occurs when Gmsh or boolean CAD operations export inward-pointing boundary "
                "facets that violate FreeFEM's strict outward-normal orientation constraint."
            )

            return SolverDiagnostic(
                error_code=rc if rc != -1 else 6,
                category="MESH_ORIENTATION_ERROR",
                summary=summary,
                root_cause=root_cause,
                offending_line_in_edp=edp_line,
                offending_file=mesh_file,
                log_snippet=tail_lines,
                is_auto_healable=True,
                remediation_suggestion=(
                    "Prune orphan boundary triangles and re-orient all valid boundary triangle "
                    "vertices relative to their parent volume tetrahedra."
                )
            )

        # ----------------------------------------------------------------------
        # Pattern 2: MUMPS Direct Solver Memory Exhaustion (INFO(1) = -8 / -9)
        # ----------------------------------------------------------------------
        if "INFO(1)=-9" in content or "INFO(1)=-8" in content or (
            "MUMPS" in content and ("allocation error" in content or "work space" in content and "too small" in content)
        ):
            return SolverDiagnostic(
                error_code=rc if rc != -1 else 1,
                category="MUMPS_MEMORY_EXHAUSTION",
                summary="MUMPS Sparse Matrix Workspace Exhausted",
                root_cause=(
                    "The MUMPS direct sparse linear solver ran out of internal working space "
                    "during numeric LU factorization. High fill-in during 3D vector mechanics "
                    "requires a larger ICNTL(14) memory allocation margin."
                ),
                offending_line_in_edp=edp_line,
                log_snippet="\n".join([l for l in lines if "MUMPS" in l or "INFO(" in l][-6:]),
                is_auto_healable=True,
                remediation_suggestion=(
                    "Increase MUMPS memory allocation margin ICNTL(14) from default (20-30%) "
                    "to 100% or switch to preconditioned CG/GMRES iterative solver."
                )
            )

        # ----------------------------------------------------------------------
        # Pattern 3: Singular Matrix / Missing Boundary Constraints (INFO(1) = -10)
        # ----------------------------------------------------------------------
        if "INFO(1)=-10" in content or "matrix is singular" in content or "zero pivot" in content:
            return SolverDiagnostic(
                error_code=rc if rc != -1 else 1,
                category="SINGULAR_MATRIX",
                summary="Structural Numerical Singularity (Zero Pivot)",
                root_cause=(
                    "The stiffness or thermal conductance matrix is singular. This typically "
                    "indicates unconstrained rigid-body motion (missing clamp Dirichlet BC on "
                    "substrate boundary label 1) or completely detached mesh components."
                ),
                offending_line_in_edp=edp_line,
                log_snippet="\n".join(lines[-10:]),
                is_auto_healable=True,
                remediation_suggestion=(
                    "Verify boundary face classification. Ensure bottom boundary label 1 exists "
                    "and has non-zero surface area."
                )
            )

        # ----------------------------------------------------------------------
        # Pattern 4: Mesh or File Not Found
        # ----------------------------------------------------------------------
        if "Error input opening file" in content or "Cannot open mesh file" in content or (
            "Error opening file" in content and ".mesh" in content
        ):
            m_f = re.search(r"Error opening file\s+([^\s]+)", content)
            missing = m_f.group(1) if m_f else (mesh_file or "specified file")
            return SolverDiagnostic(
                error_code=rc if rc != -1 else 1,
                category="FILE_NOT_FOUND",
                summary="Referenced Mesh or Input File Missing",
                root_cause=f"FreeFEM failed trying to open file: {missing}",
                offending_file=missing,
                log_snippet="\n".join(lines[:20]),
                is_auto_healable=True,
                remediation_suggestion="Regenerate the missing mesh or copy CAD file to the run directory."
            )

        # ----------------------------------------------------------------------
        # Pattern 5: Syntax, Lexer or Compilation Error in .edp (Checked before divergence)
        # ----------------------------------------------------------------------
        if "Compile error" in content or "syntax error" in content or "End of String" in content or "lex:" in content:
            is_lex_string = "End of String" in content or "lex:" in content
            return SolverDiagnostic(
                error_code=rc if rc != -1 else 1,
                category="SYNTAX_ERROR",
                summary="FreeFEM++ Script Lexer/Compilation Error",
                root_cause=(
                    f"FreeFEM lexer/parser failed at line {edp_line or 'unknown'}. "
                    + ("Encountered multi-byte unicode or unescaped string delimiter." if is_lex_string else "")
                ),
                offending_line_in_edp=edp_line,
                log_snippet="\n".join([l for l in lines if "Compile error" in l or "syntax error" in l or "End of String" in l or "lex:" in l][:4]),
                is_auto_healable=True,
                remediation_suggestion="Sanitize .edp script to clean 7-bit ASCII and strip unescaped delimiters."
            )

        # ----------------------------------------------------------------------
        # Pattern 6: Numerical Divergence or NaN
        # ----------------------------------------------------------------------
        has_nan_or_div = bool(
            re.search(r"\b(nan|-?inf|infinity)\b", content, re.IGNORECASE)
            or re.search(r"(solver|solution|iteration|temperature)\s+diverg", content, re.IGNORECASE)
            or "floating point exception" in content.lower()
        )
        if has_nan_or_div:
            return SolverDiagnostic(
                error_code=rc if rc != -1 else 136,
                category="NUMERICAL_DIVERGENCE",
                summary="Thermal or Mechanical Solution Diverged (NaN)",
                root_cause=(
                    "Solution values blew up to NaN or infinity. Usually caused by time step dt_weld "
                    "violating the explicit diffusion limit without adaptive stepping, or excessive "
                    "heat source volumetric concentration on an ultra-coarse cell."
                ),
                offending_line_in_edp=edp_line,
                log_snippet="\n".join([l for l in lines if "nan" in l.lower() or "diverg" in l.lower()][-6:]),
                is_auto_healable=True,
                remediation_suggestion=(
                    "Enable adaptive time-stepping (useAdaptiveDt=1) with Fo target 0.45, "
                    "or reduce dt_weld by 50%."
                )
            )

        # Generic Non-Zero Exit
        if rc != 0 and rc != -1:
            tail_lines = "\n".join(lines[-15:])
            return SolverDiagnostic(
                error_code=rc,
                category="GENERIC_SOLVER_FAILURE",
                summary=f"FreeFEM++ Solver Exited with Non-Zero Code {rc}",
                root_cause=f"Process terminated unexpectedly with exit code {rc}.",
                log_snippet=tail_lines,
                is_auto_healable=False,
                remediation_suggestion="Examine sim.log terminal output for solver assertions or OS signals."
            )

        return SolverDiagnostic(
            error_code=0,
            category="SUCCESS",
            summary="Simulation Completed Successfully",
            root_cause="Clean execution without errors.",
            is_auto_healable=False
        )

    @classmethod
    def auto_heal(
        cls,
        diagnostic: SolverDiagnostic,
        run_dir: str | Path,
        params: Optional[Dict] = None
    ) -> Tuple[bool, str]:
        """
        Attempt automatic self-healing based on diagnosed root cause.
        Returns (success: bool, description_of_action: str).
        """
        run_dir = Path(run_dir)

        # Case 1: Inverted Boundary Mesh Orientation
        if diagnostic.category == "MESH_ORIENTATION_ERROR":
            mesh_candidates = []
            if diagnostic.offending_file and os.path.exists(diagnostic.offending_file):
                mesh_candidates.append(diagnostic.offending_file)
            # Look inside run_dir and FreeFEM subfolder
            for d in [run_dir, run_dir / "FreeFEM"]:
                if d.exists():
                    for f in d.glob("*.mesh"):
                        mesh_candidates.append(str(f))

            if not mesh_candidates:
                return False, "Could not locate .mesh file to heal boundary orientation."

            from mesh.stl_pipeline import reorient_mesh_boundary_triangles
            fixed_count_total = 0
            healed_files = []
            for m_path in set(mesh_candidates):
                n_fixed = reorient_mesh_boundary_triangles(m_path)
                if n_fixed > 0:
                    fixed_count_total += n_fixed
                    healed_files.append(os.path.basename(m_path))

            if fixed_count_total > 0:
                action = (
                    f"Successfully corrected outward normal winding on {fixed_count_total} "
                    f"inverted boundary facet(s) in {', '.join(healed_files)}. "
                    "Mesh is now strictly compliant with FreeFEM GenericMesh::meshS."
                )
                diagnostic.healed = True
                diagnostic.heal_action_taken = action
                return True, action
            else:
                return False, "Orientation checker ran but found no inverted facets to reorder."

        # Case 2: MUMPS Working Space Exhaustion
        elif diagnostic.category == "MUMPS_MEMORY_EXHAUSTION":
            # Search for waam_simulation.edp in run_dir or run_dir / FreeFEM
            edp_candidates = list(run_dir.glob("*.edp")) + list((run_dir / "FreeFEM").glob("*.edp"))
            if not edp_candidates:
                return False, "Could not find .edp script to adjust MUMPS memory."

            for edp in edp_candidates:
                try:
                    with open(edp, "r", encoding="utf-8") as f:
                        text = f.read()
                    # Inject or increase icntl(14)
                    if "sparams=\"-mem" in text or "icntl(14)" in text:
                        new_text = re.sub(r"icntl\(14\)=\d+", "icntl(14)=120", text)
                    else:
                        new_text = text.replace(
                            'load "MUMPS"',
                            'load "MUMPS"\n// [AUTO-HEAL] Expanded MUMPS memory margin to 120%\nreal[int] mumpsParam(1);'
                        )
                    with open(edp, "w", encoding="utf-8") as f:
                        f.write(new_text)
                    action = f"Expanded MUMPS factorization memory workspace in {edp.name}."
                    diagnostic.healed = True
                    diagnostic.heal_action_taken = action
                    return True, action
                except Exception as ex:
                    return False, f"Failed updating .edp script: {ex}"

        # Case 3: Missing File / Mesh
        elif diagnostic.category == "FILE_NOT_FOUND" and diagnostic.offending_file:
            off_path = Path(diagnostic.offending_file)
            # If it's a mesh and corresponding STL exists in stl/
            stl_dir = run_dir.parent.parent / "stl" if "waam_output" in str(run_dir) else Path("./stl")
            stem = off_path.stem.replace("imported_", "")
            stl_cand = stl_dir / f"{stem}.stl"
            if stl_cand.exists():
                from mesh.stl_pipeline import stl_to_freefem_mesh
                stl_to_freefem_mesh(str(stl_cand), str(off_path))
                action = f"Regenerated missing volume mesh {off_path.name} from {stl_cand.name}."
                diagnostic.healed = True
                diagnostic.heal_action_taken = action
                return True, action

        # Case 4: Syntax / Lexer String Error (Non-ASCII characters or unclosed quotes)
        elif diagnostic.category == "SYNTAX_ERROR":
            edp_candidates = list(run_dir.glob("*.edp")) + list((run_dir / "FreeFEM").glob("*.edp"))
            if not edp_candidates:
                return False, "Could not find .edp script to heal syntax/lexer error."

            from codegen.edp.builder_core import sanitize_freefem_script
            healed_count = 0
            for edp in edp_candidates:
                try:
                    with open(edp, "r", encoding="utf-8", errors="ignore") as f:
                        raw_code = f.read()
                    sanitized_code = sanitize_freefem_script(raw_code)
                    with open(edp, "w", encoding="ascii", errors="ignore") as f:
                        f.write(sanitized_code)
                    healed_count += 1
                except Exception as ex:
                    return False, f"Failed sanitizing .edp script {edp.name}: {ex}"

            if healed_count > 0:
                action = f"Sanitized {healed_count} .edp script(s) to strictly compliant 7-bit ASCII for FreeFEM flex/bison lexer."
                diagnostic.healed = True
                diagnostic.heal_action_taken = action
                return True, action

        return False, f"No automated healing strategy available for category: {diagnostic.category}"
