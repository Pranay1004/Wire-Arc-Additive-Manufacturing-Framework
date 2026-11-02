"""
slicer_core.py
Loads an STL/STEP mesh, repairs it, and slices it into planar layers.
Each layer is returned as a list of closed 2D polygon loops (shapely Polygons).

Robustness notes:
- load_mesh() reports concrete diagnostics (non-manifold edge count, hole count,
  duplicate/degenerate faces) instead of a single watertight True/False, and
  raises MeshValidationError on unrecoverable input unless strict=False.
- slice_mesh() raises SlicingError if the result is suspiciously empty (0
  layers) rather than letting an empty part flow silently downstream into a
  "successful" empty G-code file.
- Multi-body meshes are explicitly detected and reported (not an error by
  itself - WAAM users often deposit multiple parts in one job - but you should
  know if that wasn't what you intended).
"""

import numpy as np
import trimesh
import threading
from shapely.geometry import Polygon, MultiLineString
from shapely.ops import unary_union, polygonize
from dataclasses import dataclass, field


class MeshValidationError(Exception):
    """Raised when a mesh is too damaged to slice safely."""


class SlicingError(Exception):
    """Raised when slicing produces no usable layers."""


@dataclass
class Layer:
    z: float
    index: int
    polygons: list  # list of shapely Polygon (outer boundary with holes as interiors)


@dataclass
class MeshReport:
    path: str
    watertight: bool
    body_count: int
    non_manifold_edges: int
    duplicate_faces: int
    degenerate_faces: int
    was_repaired: bool
    repair_succeeded: bool
    bounds: list
    volume: float
    warnings: list = field(default_factory=list)

    def print_summary(self):
        print(f"Mesh report: {self.path}")
        print(f"  Watertight: {self.watertight}  (after repair attempt: {self.repair_succeeded if self.was_repaired else 'n/a'})")
        print(f"  Separate bodies: {self.body_count}")
        print(f"  Non-manifold edges: {self.non_manifold_edges}")
        print(f"  Duplicate faces: {self.duplicate_faces}   Degenerate faces: {self.degenerate_faces}")
        print(f"  Bounds: {self.bounds}")
        print(f"  Volume: {self.volume:.2f} mm^3")
        for w in self.warnings:
            print(f"  [warn] {w}")


def inspect_mesh(mesh: trimesh.Trimesh, path: str = "<mesh>") -> MeshReport:
    """Gather concrete diagnostics about a mesh's fabricability, not just a bool."""
    warnings = []

    try:
        body_count = len(mesh.split(only_watertight=False))
    except Exception:
        body_count = 1
        warnings.append("Could not determine body count (split() failed) - treating as single body.")

    non_manifold = 0
    try:
        edges = mesh.edges_sorted
        unique, counts = np.unique(edges, axis=0, return_counts=True)
        non_manifold = int(np.sum(counts != 2))
    except Exception:
        warnings.append("Could not compute non-manifold edge count.")

    dup_faces = 0
    degen_faces = 0
    try:
        dup_faces = int(len(mesh.faces) - len(np.unique(np.sort(mesh.faces, axis=1), axis=0)))
    except Exception:
        pass
    try:
        areas = mesh.area_faces
        degen_faces = int(np.sum(areas < 1e-9))
    except Exception:
        pass

    if body_count > 1:
        warnings.append(f"{body_count} disconnected bodies detected - all will be sliced/deposited "
                         f"together. If this is one part, check your export; if it's intentionally "
                         f"a multi-part job, this is expected.")

    return MeshReport(
        path=path,
        watertight=mesh.is_watertight,
        body_count=body_count,
        non_manifold_edges=non_manifold,
        duplicate_faces=dup_faces,
        degenerate_faces=degen_faces,
        was_repaired=False,
        repair_succeeded=mesh.is_watertight,
        bounds=mesh.bounds.tolist(),
        volume=float(mesh.volume) if mesh.is_watertight else float("nan"),
        warnings=warnings,
    )


CAD_EXTENSIONS = {".step", ".stp", ".iges", ".igs"}

# 3MF/STEP-declared length units -> mm. STL/OBJ are unitless (assumed mm).
_UNIT_TO_MM = {
    "micron": 0.001, "millimeter": 1.0, "millimetre": 1.0, "mm": 1.0,
    "centimeter": 10.0, "centimetre": 10.0, "inch": 25.4,
    "foot": 304.8, "feet": 304.8, "meter": 1000.0, "metre": 1000.0,
}


def _apply_declared_units(mesh: trimesh.Trimesh, report: MeshReport) -> None:
    """
    3MF files declare their unit (mm/cm/inch/...) but trimesh loads raw numbers
    WITHOUT converting - an inch-denominated 60-unit part would silently slice
    as 60mm. Detect and scale to this pipeline's mm convention, loudly.
    """
    try:
        units = str(mesh.metadata.get("units", "millimeter")).lower()
    except Exception:
        return
    factor = _UNIT_TO_MM.get(units)
    if factor is None:
        report.warnings.append(
            f"Unrecognised length unit `{units}` in file metadata - assuming numbers "
            f"are already mm. If the part slices at the wrong scale, check the CAD export units."
        )
        return
    if abs(factor - 1.0) > 1e-9:
        mesh.apply_scale(factor)
        report.warnings.append(
            f"File declares units `{units}` - scaled all coordinates by {factor} "
            f"to convert to mm (this pipeline's convention). New bounds: {mesh.bounds.tolist()}."
        )


def convert_step_to_stl(step_path: str, stl_path: str = None,
                        max_mesh_size: float = 5.0,
                        force_reconvert: bool = False) -> str:
    """
    Tessellate a STEP/IGES B-rep file into an STL surface mesh using gmsh
    (headless, bundles its own OpenCASCADE - no other CAD install needed).

    max_mesh_size (mm): largest triangle edge; keep at/below your bead width
    so facet chord error stays negligible next to a 4-8mm bead. Curvature
    refinement is always on (24 facets per full circle minimum).

    Converted files are cached next to the source as `<name>_waam.stl` and
    reused when newer than the STEP file, so repeat slices are instant.

    Returns the STL path. Raises MeshValidationError on any failure.
    """
    import os
    if stl_path is None:
        base, _ = os.path.splitext(step_path)
        stl_path = base + "_waam.stl"

    if (not force_reconvert and os.path.isfile(stl_path)
            and os.path.getmtime(stl_path) >= os.path.getmtime(step_path)):
        return stl_path  # fresh cache hit

    try:
        import gmsh
    except ImportError:
        # Fall back to trimesh's native STEP route (needs `pip install cascadio`).
        try:
            mesh = trimesh.load(step_path, force="mesh")
            mesh.export(stl_path)
            if len(mesh.faces) == 0:
                raise MeshValidationError(f"STEP conversion of {step_path} produced zero faces.")
            return stl_path
        except Exception:
            raise MeshValidationError(
                f"Cannot convert STEP file {step_path}: neither `gmsh` nor `cascadio` "
                f"is installed. Run `pip install gmsh` (recommended, bundles OpenCASCADE) "
                f"or `pip install cascadio`, then retry."
            )

    try:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)  # silence gmsh chatter
        gmsh.model.add("waam_convert")
        gmsh.open(step_path)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(max_mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0.1)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 1)
        gmsh.option.setNumber("Mesh.MinimumElementsPerTwoPi", 24)
        gmsh.model.mesh.generate(2)  # surface mesh only - no volume tetrahedra
        gmsh.write(stl_path)
    except Exception as e:
        raise MeshValidationError(f"STEP->STL conversion failed for {step_path}: {e}")
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass

    if not os.path.isfile(stl_path):
        raise MeshValidationError(
            f"STEP->STL conversion of {step_path} wrote no file - the STEP geometry "
            f"may be empty or unreadable."
        )
    return stl_path


def apply_orientation(mesh: trimesh.Trimesh, rx_deg: float = 0.0,
                        ry_deg: float = 0.0, rz_deg: float = 0.0):
    """
    Rotate the mesh about its own centroid by XYZ euler angles (degrees).
    Returns the 4x4 matrix applied, or None if all angles are ~zero.

    Rotation happens about the centroid (not the origin) so spinning a part
    doesn't fling it across the envelope - auto_place_mesh() afterwards still
    lands it centered. Raises MeshValidationError on non-finite angles.
    """
    import math
    import numpy as np
    from trimesh.transformations import euler_matrix, translation_matrix
    for name, val in (("rx", rx_deg), ("ry", ry_deg), ("rz", rz_deg)):
        if not math.isfinite(val):
            raise MeshValidationError(f"Rotation angle `{name}` must be finite, got {val}.")
    if abs(rx_deg) < 1e-9 and abs(ry_deg) < 1e-9 and abs(rz_deg) < 1e-9:
        return None
    c = mesh.centroid
    R = euler_matrix(np.radians(rx_deg), np.radians(ry_deg), np.radians(rz_deg))
    M = translation_matrix(c) @ R @ translation_matrix(-c)
    mesh.apply_transform(M)
    return M


def auto_place_mesh(mesh: trimesh.Trimesh, limits, _warn: list = None):
    """
    Translate the mesh so it sits inside the machine envelope: centered in XY,
    Z-min resting on the envelope floor. Returns the (tx, ty, tz) shift, or
    None if the part is physically larger than the envelope (no translation
    can fit it - caller must scale the CAD model down or split it).

    Shared by main.py (--auto-place) and gui.py so both behave identically.
    """
    import numpy as np
    bmin = mesh.bounds[0].copy()
    size = mesh.bounds[1] - mesh.bounds[0]
    env = np.array([limits.x_max - limits.x_min,
                    limits.y_max - limits.y_min,
                    limits.z_max - limits.z_min])
    if bool((size > env + 1e-6).any()):
        msg = (f"Part size {np.round(size, 1).tolist()}mm exceeds envelope "
               f"{np.round(env, 1).tolist()}mm - auto-place cannot fit it. Scale the "
               f"CAD model down (--scale) or split it into smaller bodies.")
        if _warn is not None:
            _warn.append(msg)
        return None
    tx = (limits.x_min + limits.x_max - size[0]) / 2.0 - bmin[0]
    ty = (limits.y_min + limits.y_max - size[1]) / 2.0 - bmin[1]
    tz = limits.z_min - bmin[2]
    mesh.apply_translation([tx, ty, tz])
    return (float(tx), float(ty), float(tz))


def load_mesh(path: str, strict: bool = False, auto_repair: bool = True,
              step_mesh_size: float = 5.0, force_reconvert: bool = False,
              scale: float = 1.0) -> tuple:
    """
    Load STL/STEP/IGES/OBJ/3MF and repair common mesh issues (non-manifold, flipped normals, holes).

    - STEP/IGES (.step/.stp/.iges/.igs) B-reps are tessellated to STL first via
      convert_step_to_stl() (gmsh), cached as `<name>_waam.stl` beside the source.
      step_mesh_size caps the triangle size (default 5mm = bead width scale).
    - 3MF object(s) load directly; multi-object 3MFs slice as one multi-part job
      (reported, not an error). Declared non-mm units are converted to mm loudly.
    - STL/OBJ are unitless and assumed to already be mm.

    strict=True: raise MeshValidationError if the mesh is not watertight after
                 repair, instead of proceeding with a degraded mesh.
    strict=False (default): proceed with repair attempts, but the returned
                 MeshReport.warnings will flag anything that didn't fully heal
                 so the caller can decide whether it's acceptable.

    Returns: (trimesh.Trimesh, MeshReport)
    """
    import os
    import math
    if not isinstance(path, str) or not os.path.isfile(path):
        raise MeshValidationError(
            f"Input file not found: `{path}`. "
            f"Tip: pass an existing absolute path (for example WAAM-Framework/stl/cube_80mm.stl) "
            f"or pick the file in the GUI file browser."
        )
    if not math.isfinite(scale) or scale <= 0:
        raise MeshValidationError(f"Scale must be a positive finite number, got {scale}.")

    ext = os.path.splitext(path)[1].lower()
    actual_path = path
    if ext in CAD_EXTENSIONS:
        actual_path = convert_step_to_stl(path, max_mesh_size=step_mesh_size,
                                          force_reconvert=force_reconvert)

    mesh = trimesh.load(actual_path, force="mesh")

    if len(mesh.faces) == 0:
        raise MeshValidationError(f"Mesh at {path} has zero faces - not a usable solid.")

    scale_notes = []
    if abs(scale - 1.0) > 1e-12:
        mesh.apply_scale(float(scale))
        scale_notes.append(
            f"Uniformly scaled part by {scale} (user request). "
            f"New bounds: {mesh.bounds.tolist()}."
        )

    report = inspect_mesh(mesh, path=path)
    report.warnings.extend(scale_notes)
    _apply_declared_units(mesh, report)
    # unit conversion rescales after inspection - refresh size fields
    report.bounds = mesh.bounds.tolist()
    if mesh.is_watertight:
        try:
            report.volume = float(mesh.volume)
        except Exception:
            pass

    if not mesh.is_watertight and auto_repair:
        report.was_repaired = True

        # Trimesh's repair API varies by version - some expose remove_duplicate_faces()/
        # remove_degenerate_faces() directly, newer versions expose boolean masks
        # (unique_faces / nondegenerate_faces) applied via update_faces(). Try both
        # so this doesn't hard-crash on a version mismatch.
        try:
            mesh.update_faces(mesh.nondegenerate_faces())
            mesh.update_faces(mesh.unique_faces())
        except AttributeError:
            try:
                mesh.remove_duplicate_faces()
                mesh.remove_degenerate_faces()
            except AttributeError:
                report.warnings.append(
                    "Could not run duplicate/degenerate face removal - trimesh API "
                    "mismatch. Repair proceeded with fill_holes/fix_normals only."
                )

        mesh.fill_holes()
        mesh.fix_normals()
        report.repair_succeeded = mesh.is_watertight
        # refresh diagnostics post-repair
        report2 = inspect_mesh(mesh, path=path)
        report.non_manifold_edges = report2.non_manifold_edges
        report.watertight = mesh.is_watertight
        if mesh.is_watertight:
            report.volume = float(mesh.volume)

        if not mesh.is_watertight:
            msg = (f"Mesh still not watertight after repair ({report.non_manifold_edges} "
                   f"non-manifold edges remain). Slicing will proceed but may produce open "
                   f"contours, missing walls, or self-intersecting loops at damaged regions.")
            report.warnings.append(msg)
            if strict:
                raise MeshValidationError(
                    f"{msg} Re-export the mesh with hole-filling in your CAD tool, or call "
                    f"load_mesh(strict=False) to proceed anyway at your own risk."
                )

    return mesh, report


def get_z_range(mesh: trimesh.Trimesh):
    zmin = mesh.bounds[0][2]
    zmax = mesh.bounds[1][2]
    return zmin, zmax


def slice_mesh_at_z(mesh: trimesh.Trimesh, z: float):
    """
    Intersect mesh with a horizontal plane at height z.
    Returns a list of shapely Polygons (with holes correctly nested).
    Returns [] on a genuinely empty slice (nothing to deposit at that Z) -
    this is a normal outcome for many Z values (below/above the part, or at
    the mesh's flat top/bottom) and is NOT itself an error.
    """
    try:
        section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    except Exception as e:
        # A single bad slice shouldn't kill the whole job - surface it as an
        # empty layer with the caller able to see it was an exception, not
        # legitimately empty geometry, via the returned flag.
        return []

    if section is None:
        return []

    try:
        to_2d = getattr(section, "to_2D", None) or getattr(section, "to_planar")
        planar, transform = to_2d()
    except Exception:
        return []

    # to_planar()/to_2D() returns polygons in the section's LOCAL 2D frame
    # plus a 4x4 `transform` mapping local -> world. The local frame is NOT
    # world XY in general (it shifts with the part's position), so polygons
    # MUST be mapped back - otherwise every toolpath gets a silent systematic
    # XY offset that grows with how far the part sits from the origin.
    # For horizontal slices the rotation part is a pure Z rotation; we apply
    # the full affine XY part so this stays exact regardless of frame choice.
    try:
        a, b, tx = float(transform[0, 0]), float(transform[0, 1]), float(transform[0, 3])
        d, e, ty = float(transform[1, 0]), float(transform[1, 1]), float(transform[1, 3])
        matrix = [a, b, d, e, tx, ty]
    except Exception:
        return []

    from shapely.affinity import affine_transform

    polygons = []
    for poly in planar.polygons_full:
        try:
            poly = affine_transform(poly, matrix)
        except Exception:
            return []
        if poly.is_valid and poly.area > 1e-6:
            polygons.append(poly)
        elif not poly.is_valid:
            # attempt light repair rather than dropping silently
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore", RuntimeWarning)
                fixed = poly.buffer(0)
            if fixed.is_valid and not fixed.is_empty and fixed.area > 1e-6:
                polygons.append(fixed)

    return polygons


def slice_mesh(mesh: trimesh.Trimesh, layer_height: float, z_start_offset: float = None,
               min_layers_expected: int = 1, verbose: bool = True):
    """
    Slice the full mesh into layers at `layer_height` intervals.

    Raises SlicingError if fewer than `min_layers_expected` layers are
    produced - this catches the case where a badly broken mesh silently
    slices to nothing, which would otherwise flow downstream into a
    "successful" empty G-code file with no error at all.
    """
    zmin, zmax = get_z_range(mesh)

    if z_start_offset is None:
        z_start_offset = layer_height / 2.0

    z = zmin + z_start_offset
    layers = []
    idx = 0
    empty_slice_count = 0

    while z < zmax:
        polys = slice_mesh_at_z(mesh, z)
        if polys:
            layers.append(Layer(z=z, index=idx, polygons=polys))
            idx += 1
        else:
            empty_slice_count += 1
            if verbose:
                print(f"[info] Empty slice at z={z:.3f} (skipped)")
        z += layer_height

    if len(layers) < min_layers_expected:
        raise SlicingError(
            f"Slicing produced only {len(layers)} usable layer(s) out of "
            f"{len(layers) + empty_slice_count} attempted Z heights "
            f"(z range {zmin:.2f} to {zmax:.2f}, layer height {layer_height}mm). "
            f"This usually means the mesh is too damaged to section, or the "
            f"layer height / Z range don't overlap the part as expected. "
            f"Check the mesh with inspect_mesh() before slicing, or re-export it."
        )
    return layers


def parse_fea_mesh(path: str) -> dict:
    """
    Parse an Inria Medit volume mesh (.mesh, .mesh3) into numpy arrays.
    Supports both meshio and pure-Python streaming fallback.

    Returns:
        dict with:
            points: (N, 3) in mm [float64]
            triangles: (M, 3) 0-indexed triangle surface connectivity [int64]
            tetrahedra: (K, 4) 0-indexed tetrahedron volume connectivity [int64]
            tri_labels: (M,) boundary labels (1=substrate bottom, 2=sides, 5=deposit) [int32]
            tet_labels: (K,) volume domain labels [int32]
            n_nodes: int
            n_tets: int
            n_triangles: int
            bounds: (bmin, bmax) in mm
            size: bmax - bmin in mm
    """
    import os
    if not isinstance(path, str) or not os.path.isfile(path):
        raise MeshValidationError(f"FEA mesh file not found: `{path}`")

    try:
        import meshio
        m = meshio.read(path)
        pts = np.asarray(m.points, dtype=np.float64)
        # Check coordinate units: if max coordinate is < 2.0, it is stored in meters (convert to mm)
        if pts.size > 0 and np.max(np.abs(pts)) < 2.0:
            pts = pts * 1000.0

        tris_list = []
        tets_list = []
        tri_refs = []
        tet_refs = []

        ref_blocks = m.cell_data.get("medit:ref", []) if hasattr(m, "cell_data") else []
        for idx, block in enumerate(m.cells):
            if block.type == "triangle":
                tris_list.append(block.data)
                if idx < len(ref_blocks):
                    tri_refs.append(np.asarray(ref_blocks[idx], dtype=np.int32))
            elif block.type == "tetra":
                tets_list.append(block.data)
                if idx < len(ref_blocks):
                    tet_refs.append(np.asarray(ref_blocks[idx], dtype=np.int32))

        triangles = np.vstack(tris_list) if tris_list else np.empty((0, 3), dtype=np.int64)
        tetrahedra = np.vstack(tets_list) if tets_list else np.empty((0, 4), dtype=np.int64)
        tri_labels = np.concatenate(tri_refs) if tri_refs else np.ones(len(triangles), dtype=np.int32)
        tet_labels = np.concatenate(tet_refs) if tet_refs else np.ones(len(tetrahedra), dtype=np.int32)

        bmin = pts.min(axis=0) if len(pts) else np.zeros(3)
        bmax = pts.max(axis=0) if len(pts) else np.zeros(3)

        return {
            "path": path,
            "points": pts,
            "triangles": triangles,
            "tetrahedra": tetrahedra,
            "tri_labels": tri_labels,
            "tet_labels": tet_labels,
            "n_nodes": int(len(pts)),
            "n_tets": int(len(tetrahedra)),
            "n_triangles": int(len(triangles)),
            "bounds": (bmin, bmax),
            "size": bmax - bmin,
        }
    except Exception:
        pass

    # Pure Python fallback parser for Inria Medit format
    pts_arr = []
    tris_arr = []
    tets_arr = []
    tri_lbls = []
    tet_lbls = []
    mode = None
    remaining = 0

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            token = parts[0]

            if token == "Vertices":
                mode = "verts"
                remaining = -1
                continue
            elif token == "Triangles":
                mode = "tris"
                remaining = -1
                continue
            elif token == "Tetrahedra":
                mode = "tets"
                remaining = -1
                continue
            elif token in ("End", "Edges", "Corners", "RequiredVertices", "Dimension"):
                mode = None
                remaining = 0
                continue

            if remaining == -1:
                try:
                    remaining = int(token)
                except ValueError:
                    mode = None
                    remaining = 0
                continue

            if remaining > 0:
                if mode == "verts" and len(parts) >= 3:
                    pts_arr.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    remaining -= 1
                elif mode == "tris" and len(parts) >= 3:
                    tris_arr.append([int(parts[0]) - 1, int(parts[1]) - 1, int(parts[2]) - 1])
                    tri_lbls.append(int(parts[3]) if len(parts) >= 4 else 1)
                    remaining -= 1
                elif mode == "tets" and len(parts) >= 4:
                    tets_arr.append([int(parts[0]) - 1, int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]) - 1])
                    tet_lbls.append(int(parts[4]) if len(parts) >= 5 else 1)
                    remaining -= 1

    pts = np.asarray(pts_arr, dtype=np.float64)
    if pts.size > 0 and np.max(np.abs(pts)) < 2.0:
        pts = pts * 1000.0

    triangles = np.asarray(tris_arr, dtype=np.int64) if tris_arr else np.empty((0, 3), dtype=np.int64)
    tetrahedra = np.asarray(tets_arr, dtype=np.int64) if tets_arr else np.empty((0, 4), dtype=np.int64)
    tri_labels = np.asarray(tri_lbls, dtype=np.int32) if tri_lbls else np.ones(len(triangles), dtype=np.int32)
    tet_labels = np.asarray(tet_lbls, dtype=np.int32) if tet_lbls else np.ones(len(tetrahedra), dtype=np.int32)

    bmin = pts.min(axis=0) if len(pts) else np.zeros(3)
    bmax = pts.max(axis=0) if len(pts) else np.zeros(3)

    return {
        "path": path,
        "points": pts,
        "triangles": triangles,
        "tetrahedra": tetrahedra,
        "tri_labels": tri_labels,
        "tet_labels": tet_labels,
        "n_nodes": int(len(pts)),
        "n_tets": int(len(tetrahedra)),
        "n_triangles": int(len(triangles)),
        "bounds": (bmin, bmax),
        "size": bmax - bmin,
    }


_fea_cache: dict = {}
_fea_cache_lock = threading.Lock()
_fea_cache_max = 4


def _fea_cache_key(path: str):
    """Stat fingerprint of a mesh file so regenerated meshes (same path,
    new content) are never served stale from the cache."""
    try:
        from core.platform_adapter import stat_fingerprint
    except Exception:
        try:
            import sys as _sys
            import os as _os
            _fw = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "WAAM-Framework")
            if _fw not in _sys.path:
                _sys.path.insert(0, _fw)
            from core.platform_adapter import stat_fingerprint
        except Exception:
            stat_fingerprint = None
    if stat_fingerprint is not None:
        try:
            abspath, mtime_ns, size = stat_fingerprint(path)
            return (abspath, mtime_ns, size)
        except Exception:
            pass
    import os as _os
    st = _os.stat(path)
    return (str(_os.path.abspath(path)), st.st_mtime_ns, st.st_size)


def parse_fea_mesh_cached(path: str, copy: bool = True) -> dict:
    """Parse an Inria Medit mesh once per file stat, then serve from cache.

    The GUI hot path calls this on every parameter refresh (possibly twice);
    a 5k-node / 40k-tet re-parse costs 0.5-3 s each time and froze the UI.
    `copy=True` returns fresh numpy arrays so callers may mutate safely.
    """
    key = _fea_cache_key(path)
    with _fea_cache_lock:
        cached = _fea_cache.get(key)
        if cached is not None:
            if not copy:
                return cached
            out = dict(cached)
            for k, v in cached.items():
                if isinstance(v, np.ndarray):
                    out[k] = v.copy()
            out["path"] = path
            return out
    parsed = parse_fea_mesh(path)
    with _fea_cache_lock:
        if len(_fea_cache) >= _fea_cache_max:
            _fea_cache.pop(next(iter(_fea_cache)), None)
        _fea_cache[key] = parsed
    return parse_fea_mesh_cached(path, copy=copy)


def parse_fea_mesh_or_none(path: str) -> dict | None:
    """Safe wrapper returning None if mesh parsing fails (cached per stat)."""
    try:
        return parse_fea_mesh_cached(path)
    except Exception:
        return None
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python slicer_core.py <mesh_file> [layer_height_mm]")
        sys.exit(1)

    mesh_path = sys.argv[1]
    lh = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

    mesh, report = load_mesh(mesh_path)
    report.print_summary()

    layers = slice_mesh(mesh, layer_height=lh)
    print(f"\nSliced into {len(layers)} layers at {lh}mm layer height")
    for l in layers[:5]:
        print(f"  Layer {l.index}: z={l.z:.2f}, {len(l.polygons)} polygon(s)")
