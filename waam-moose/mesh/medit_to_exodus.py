"""Convert WAAM medit (.mesh) meshes to Exodus II for MOOSE.

The WAAM-Framework pipeline (mesh/stl_pipeline.py) emits medit files in SI
metres with boundary references encoded as medit refs:

    1  -> z == zmin underside (substrate base, fixture)
    2  -> flanks (all vertical faces)
    5  -> z == zmax top surface

This converter maps every referenced triangle group to a named Exodus
sideset AND nodeset (MOOSE NodalBCs require node sets; libMesh derives
sidesets from elem_ss/side_ss):

    ref r  ->  sideset "lbl_r" + nodeset "lbl_r"

Output is Exodus II in netCDF classic (CDF-2) format, which the libMesh
Nexus reader accepts. elem_ss/side_ss use the libMesh Tet4 face ordering
translated to Exodus side numbers via the tet face map {4, 1, 2, 3}.

Usage:
    python medit_to_exodus.py INPUT.mesh OUTPUT.exo
"""

import sys
from collections import defaultdict

import meshio
import netCDF4
import numpy as np

LIBMESH_TET_FACES = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))
LIBMESH_TO_EXODUS_SIDE = {0: 4, 1: 1, 2: 2, 3: 3}

EXODUS_API_VERSION = 8.03
MAX_NAME_LENGTH = 32
CHAR_DIM = 256


def read_medit(path):
    """Return (points, tets, tet_refs, tris, tri_refs) from a medit file."""
    mesh = meshio.read(path)
    tets = np.empty((0, 4), dtype=np.int64)
    tet_refs = np.empty(0, dtype=np.int64)
    tris = np.empty((0, 3), dtype=np.int64)
    tri_refs = np.empty(0, dtype=np.int64)
    ref_blocks = mesh.cell_data.get("medit:ref", [])
    for block_idx, block in enumerate(mesh.cells):
        refs = np.asarray(ref_blocks[block_idx], dtype=np.int64) if block_idx < len(ref_blocks) else np.zeros(len(block.data), dtype=np.int64)
        if block.type == "tetra":
            tets, tet_refs = block.data.astype(np.int64), refs
        elif block.type == "triangle":
            tris, tri_refs = block.data.astype(np.int64), refs
    if len(tets) == 0:
        raise SystemExit(f"{path}: no tetrahedra found")
    return np.asarray(mesh.points, dtype=np.float64), tets, tet_refs, tris, tri_refs


def tet_face_lookup(tets):
    """Map frozenset(tet face nodes) -> (tet index, libMesh side index)."""
    lookup = {}
    for tet_idx, nodes in enumerate(tets):
        for side, face in enumerate(LIBMESH_TET_FACES):
            lookup[frozenset(int(nodes[i]) for i in face)] = (tet_idx, side)
    return lookup


def build_boundary_sets(tets, tris, tri_refs):
    """Group boundary triangles into per-ref sideset and nodeset specs."""
    lookup = tet_face_lookup(tets)
    sidesets = defaultdict(lambda: {"elems": [], "sides": [], "nodes": set()})
    unmatched = 0
    for tri, ref in zip(tris, tri_refs):
        face = frozenset(int(n) for n in tri)
        hit = lookup.get(face)
        if hit is None:
            unmatched += 1
            continue
        tet_idx, libmesh_side = hit
        entry = sidesets[int(ref)]
        entry["elems"].append(tet_idx + 1)
        entry["sides"].append(LIBMESH_TO_EXODUS_SIDE[libmesh_side])
        entry["nodes"].update(int(n) + 1 for n in tri)
    if unmatched:
        raise SystemExit(f"{unmatched} boundary triangles do not match any tet face")
    return sidesets


def write_char_var(ds, name, dims, rows):
    """Write a fixed-width char variable (Exodus names arrays)."""
    var = ds.createVariable(name, "S1", dims)
    width = len(ds.dimensions[dims[-1]])
    for i, text in enumerate(rows):
        encoded = text.encode("ascii")[:width]
        var[i, :] = np.frombuffer(encoded.ljust(width, b"\x00"), dtype="S1")


def write_exodus(path, points, tets, sidesets, title="WAAM MOOSE mesh"):
    """Write a minimal single-block Exodus II (CDF-2) file."""
    refs = sorted(sidesets)
    ds = netCDF4.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET")
    ds.title = title
    ds.api_version = np.float32(EXODUS_API_VERSION)
    ds.version = np.float32(EXODUS_API_VERSION)
    ds.floating_point_word_size = np.int32(8)
    ds.file_size = np.int32(1)
    ds.maximum_name_length = np.int32(MAX_NAME_LENGTH)
    ds.int64_status = np.int32(0)

    ds.createDimension("len_name", CHAR_DIM)
    ds.createDimension("time_step", None)
    ds.createDimension("num_dim", 3)
    ds.createDimension("num_nodes", len(points))
    ds.createDimension("num_elem", len(tets))
    ds.createDimension("num_el_blk", 1)
    ds.createDimension("num_side_sets", len(refs))
    ds.createDimension("num_node_sets", len(refs))
    ds.createDimension("num_el_in_blk1", len(tets))
    ds.createDimension("num_nod_per_el1", 4)
    for i, ref in enumerate(refs):
        ds.createDimension(f"num_side_ss{i + 1}", len(sidesets[ref]["elems"]))
        ds.createDimension(f"num_nod_ns{i + 1}", len(sidesets[ref]["nodes"]))

    ds.createVariable("time_whole", "f8", ("time_step",))
    ds.createVariable("eb_status", "i4", ("num_el_blk",))[:] = 1
    eb_prop1 = ds.createVariable("eb_prop1", "i4", ("num_el_blk",))
    eb_prop1[:] = 1
    eb_prop1.setncattr("name", "ID")
    ds.createVariable("ss_status", "i4", ("num_side_sets",))[:] = 1
    ss_prop1 = ds.createVariable("ss_prop1", "i4", ("num_side_sets",))
    ss_prop1[:] = [ref for ref in refs]
    ss_prop1.setncattr("name", "ID")
    ds.createVariable("ns_status", "i4", ("num_node_sets",))[:] = 1
    ns_prop1 = ds.createVariable("ns_prop1", "i4", ("num_node_sets",))
    ns_prop1[:] = [ref for ref in refs]
    ns_prop1.setncattr("name", "ID")

    coor_names = ds.createVariable("coor_names", "S1", ("num_dim", "len_name"))
    for i, axis in enumerate(("x", "y", "z")):
        coor_names[i, :] = np.frombuffer(axis.encode("ascii").ljust(CHAR_DIM, b"\x00"), dtype="S1")
    for i, axis in enumerate("xyz"):
        ds.createVariable(f"coord{axis}", "f8", ("num_nodes",))[:] = points[:, i]

    connect = ds.createVariable("connect1", "i4", ("num_el_in_blk1", "num_nod_per_el1"))
    connect[:] = tets + 1
    connect.setncattr("elem_type", "TETRA")

    write_char_var(ds, "eb_names", ("num_el_blk", "len_name"), ["domain"])
    write_char_var(ds, "ss_names", ("num_side_sets", "len_name"), [f"lbl_{ref}" for ref in refs])
    write_char_var(ds, "ns_names", ("num_node_sets", "len_name"), [f"lbl_{ref}" for ref in refs])

    for i, ref in enumerate(refs):
        entry = sidesets[ref]
        ds.createVariable(f"elem_ss{i + 1}", "i4", (f"num_side_ss{i + 1}",))[:] = entry["elems"]
        ds.createVariable(f"side_ss{i + 1}", "i4", (f"num_side_ss{i + 1}",))[:] = entry["sides"]
        ds.createVariable(f"node_ns{i + 1}", "i4", (f"num_nod_ns{i + 1}",))[:] = sorted(entry["nodes"])
    ds.close()


def convert(input_path, output_path):
    points, tets, _tet_refs, tris, tri_refs = read_medit(input_path)
    sidesets = build_boundary_sets(tets, tris, tri_refs)
    write_exodus(output_path, points, tets, sidesets)
    summary = ", ".join(
        f"lbl_{ref}: {len(sidesets[ref]['elems'])} faces / {len(sidesets[ref]['nodes'])} nodes"
        for ref in sorted(sidesets)
    )
    print(f"{input_path} -> {output_path}: {len(points)} nodes, {len(tets)} tets, {summary}")


medit_to_exodus = convert


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    convert(sys.argv[1], sys.argv[2])
