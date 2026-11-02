"""
mesh/slicer_api.py

High-Performance Multi-Strategy WAAM Slicer & G-Code Toolpath Generator.

Features:
- Multi-format support: directly slices STL, STEP, STP, IGES, IGS files.
- Advanced infill patterns:
  1. Alternating Zigzag (0° / 90° orthogonal raster)
  2. Continuous Meander (Snake / minimum non-welding travel)
  3. Perimeter Contours + Infill (Wall loops + raster core)
  4. Cross-Hatch (±45° diagonal weave)
  5. Unidirectional (Single-direction deposition with rapid return)
- Physics-based WAAM toolpath controls:
  * Bead overlap ratio calculation (stepover = bead_width * overlap_factor)
  * Bi-directional start reversal to prevent start-point height buildup
  * Inter-pass / Inter-layer dwell time cooling (G4 P...)
  * Customized welding feedrate & G0 rapid travel feedrate
  * Arc initiation / termination M-codes (M3 S... / M5)
  * Comprehensive deposition metrics: Total length (m), Print time (min),
    Bead mass deposited (kg), Electrical energy (kJ).
"""

import os
import sys
import math
import struct
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any
import numpy as np


class STLLoader:
    """High-speed binary and ASCII STL mesh loader."""

    @staticmethod
    def load(filepath: str) -> List[Tuple[Tuple[float, float, float],
                                         Tuple[float, float, float],
                                         Tuple[float, float, float]]]:
        """Load triangles as list of ((x1,y1,z1), (x2,y2,z2), (x3,y3,z3))."""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        # Check if binary
        with open(filepath, 'rb') as f:
            header = f.read(80)
            count_bytes = f.read(4)
            if len(count_bytes) == 4:
                n_triangles = struct.unpack('<I', count_bytes)[0]
                expected_size = 84 + n_triangles * 50
                actual_size = filepath.stat().st_size
                if actual_size == expected_size:
                    triangles = []
                    for _ in range(n_triangles):
                        data = f.read(50)
                        floats = struct.unpack('<12fH', data)
                        p1 = (floats[3], floats[4], floats[5])
                        p2 = (floats[6], floats[7], floats[8])
                        p3 = (floats[9], floats[10], floats[11])
                        triangles.append((p1, p2, p3))
                    return triangles

        # Fallback to ASCII
        triangles = []
        with open(filepath, 'r', errors='ignore') as f:
            p1, p2, p3 = None, None, None
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0].lower() == 'vertex':
                    v = (float(parts[1]), float(parts[2]), float(parts[3]))
                    if p1 is None:
                        p1 = v
                    elif p2 is None:
                        p2 = v
                    elif p3 is None:
                        p3 = v
                        triangles.append((p1, p2, p3))
                        p1, p2, p3 = None, None, None
        return triangles


class AdvancedWAAMSlicer:
    """Multi-Strategy WAAM Slicing Engine."""

    def __init__(self, triangles: list,
                 layer_height: float = 3.0,
                 bead_width: float = 8.0,
                 infill_pattern: str = "zigzag",
                 overlap_pct: float = 75.0,
                 perimeters: int = 1,
                 feedrate: float = 600.0,
                 rapid_feedrate: float = 3000.0,
                 power: float = 3840.0,
                 dwell_time: float = 10.0,
                 start_reverse: bool = True,
                 density_kg_m3: float = 7850.0,
                 sub_lx: float = 150.0,
                 sub_ly: float = 150.0,
                 sub_hz: float = 5.0,
                 build_height: float = 150.0,
                 z_hop: float = 2.0):
        self.triangles = triangles
        self.h = max(float(layer_height), 0.2)
        self.w = max(float(bead_width), 0.5)
        self.infill_pattern = infill_pattern
        self.overlap_factor = max(min(float(overlap_pct) / 100.0, 1.0), 0.3)
        self.perimeters = max(int(perimeters), 0)
        self.feedrate = max(float(feedrate), 60.0)
        self.rapid_feedrate = max(float(rapid_feedrate), 300.0)
        self.power = max(float(power), 0.0)
        self.dwell_time = max(float(dwell_time), 0.0)
        self.start_reverse = start_reverse
        self.density = density_kg_m3
        # Retract height for rapid travels (torch clears the deposited bead).
        # The G-code arc is gated M3/M5 per weld run: the old writer turned the
        # arc ON at the top of the file and OFF at EOF, so the real machine
        # (and its arc) stayed live through every G0 rapid and dwell -- the
        # toolpath's own pState column says those moves are arc-off.
        self.z_hop = max(float(z_hop), 0.0)
        # Enclosure / substrate placement. sub_hz must equal the solver's
        # hz_base or the sliced part floats above the plate.
        self.sub_lx = sub_lx
        self.sub_ly = sub_ly
        self.sub_hz = sub_hz
        self.build_height = build_height
        # Non-fatal slicing notes (contour-offset fallback, repairs, ...).
        # Surfaced through slice_to_gcode()'s "warnings" so the GUI and the
        # CLI can report them instead of silently depositing something else.
        self.warnings = []

        # Compute bounding box
        all_pts = [pt for tri in triangles for pt in tri]
        if all_pts:
            raw_xmin = min(p[0] for p in all_pts)
            raw_xmax = max(p[0] for p in all_pts)
            raw_ymin = min(p[1] for p in all_pts)
            raw_ymax = max(p[1] for p in all_pts)
            raw_zmin = min(p[2] for p in all_pts)
            raw_zmax = max(p[2] for p in all_pts)

            # Build enclosure limits. SUB_HZ MUST match the solver's hz_base
            # (codegen default 5 mm): the slicer drops the part onto the plate
            # top and the builder meshes the plate at hz_base, so a mismatch
            # leaves the deposit floating above the substrate by |SUB_HZ -
            # hz_base|. It was hardcoded to 15 mm while the builder moved to 5 mm
            # in the thin-plate re-baseline, so every sliced part started 10 mm
            # in mid-air.
            SUB_LX = float(self.sub_lx)
            SUB_LY = float(self.sub_ly)
            SUB_HZ = float(self.sub_hz)
            BUILD_HEIGHT = float(self.build_height)
            V_ENCLOSURE = SUB_LX * SUB_LY * BUILD_HEIGHT  # 3,375,000 mm^3
            MAX_OCCUPIED_VOL = 0.75 * V_ENCLOSURE       # 2,531,250 mm^3 (75% max volume)

            dx = max(raw_xmax - raw_xmin, 1e-4)
            dy = max(raw_ymax - raw_ymin, 1e-4)
            dz = max(raw_zmax - raw_zmin, 1e-4)
            v_bbox = dx * dy * dz

            # Check if larger than enclosure or exceeds 75% volume limit
            scale_applied = 1.0
            if dx > SUB_LX or dy > SUB_LY or dz > BUILD_HEIGHT or v_bbox > MAX_OCCUPIED_VOL:
                s_vol = (MAX_OCCUPIED_VOL / max(v_bbox, 1e-6)) ** (1.0 / 3.0)
                s_dim = min(SUB_LX / dx, SUB_LY / dy, BUILD_HEIGHT / dz)
                scale_applied = min(s_vol, s_dim)
                scaled_triangles = []
                for (p1, p2, p3) in self.triangles:
                    sp1 = (p1[0] * scale_applied, p1[1] * scale_applied, p1[2] * scale_applied)
                    sp2 = (p2[0] * scale_applied, p2[1] * scale_applied, p2[2] * scale_applied)
                    sp3 = (p3[0] * scale_applied, p3[1] * scale_applied, p3[2] * scale_applied)
                    scaled_triangles.append((sp1, sp2, sp3))
                self.triangles = scaled_triangles
                raw_xmin *= scale_applied; raw_xmax *= scale_applied
                raw_ymin *= scale_applied; raw_ymax *= scale_applied
                raw_zmin *= scale_applied; raw_zmax *= scale_applied

            # Auto-place correctly on top of the substrate plate
            # (default 150x150x5mm): centered in X and Y, bottom resting on
            # top of the substrate (Z = SUB_HZ).
            cx = (raw_xmin + raw_xmax) / 2.0
            cy = (raw_ymin + raw_ymax) / 2.0
            min_z = raw_zmin
            tx = (SUB_LX / 2.0) - cx
            ty = (SUB_LY / 2.0) - cy
            tz = SUB_HZ - min_z

            placed_triangles = []
            for (p1, p2, p3) in self.triangles:
                pp1 = (p1[0] + tx, p1[1] + ty, p1[2] + tz)
                pp2 = (p2[0] + tx, p2[1] + ty, p2[2] + tz)
                pp3 = (p3[0] + tx, p3[1] + ty, p3[2] + tz)
                placed_triangles.append((pp1, pp2, pp3))
            self.triangles = placed_triangles
            self.xmin = raw_xmin + tx
            self.xmax = raw_xmax + tx
            self.ymin = raw_ymin + ty
            self.ymax = raw_ymax + ty
            self.zmin = raw_zmin + tz
            self.zmax = raw_zmax + tz
            self.scale_applied = scale_applied
        else:
            self.xmin, self.xmax = 0.0, self.sub_lx
            self.ymin, self.ymax = 0.0, self.sub_ly
            self.zmin, self.zmax = self.sub_hz, self.sub_hz + self.h
            self.scale_applied = 1.0

    def _intersect_edge_with_z(self, p1, p2, z):
        if (p1[2] < z <= p2[2]) or (p2[2] < z <= p1[2]):
            dz = p2[2] - p1[2]
            if abs(dz) < 1e-9:
                return None
            t = (z - p1[2]) / dz
            x = p1[0] + t * (p2[0] - p1[0])
            y = p1[1] + t * (p2[1] - p1[1])
            return (x, y)
        return None

    def slice_layer_segments(self, z: float) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Slice all triangles with horizontal plane z = const, returning 2D segments."""
        segments = []
        for p1, p2, p3 in self.triangles:
            tri_zmin = min(p1[2], p2[2], p3[2])
            tri_zmax = max(p1[2], p2[2], p3[2])
            if tri_zmin <= z <= tri_zmax:
                pts = []
                for a, b in [(p1, p2), (p2, p3), (p3, p1)]:
                    pt = self._intersect_edge_with_z(a, b, z)
                    if pt:
                        pts.append(pt)
                if len(pts) == 2:
                    segments.append((pts[0], pts[1]))
        return segments
        
    @staticmethod
    def _chain_segments_into_loops(segments, tol: float = None) -> list:
        """Chain unordered line segments into continuous ordered loops.

        `tol` defaults to a fraction of the part size rather than a fixed 1 mm:
        on a sub-millimetre bead nothing ever connected (every segment became
        its own 2-point "loop"), and on a 150 mm plate unrelated ends inside a
        1 mm gap were welded into one loop.
        """
        if not segments:
            return []
        if tol is None:
            spans = [abs(a - b) for seg in segments
                     for a, b in ((seg[0][0], seg[1][0]), (seg[0][1], seg[1][1]))]
            span = max(spans) if spans else 1.0
            tol = max(1.0e-3, 1.0e-3 * span)
        unvisited = list(segments)
        loops = []
        while unvisited:
            curr_p1, curr_p2 = unvisited.pop(0)
            chain = [curr_p1, curr_p2]
            extended = True
            while extended:
                extended = False
                last_pt = chain[-1]
                best_idx = -1
                rev = False
                min_d = tol
                for idx, (sp1, sp2) in enumerate(unvisited):
                    d1 = math.hypot(sp1[0] - last_pt[0], sp1[1] - last_pt[1])
                    d2 = math.hypot(sp2[0] - last_pt[0], sp2[1] - last_pt[1])
                    if d1 < min_d:
                        min_d = d1
                        best_idx = idx
                        rev = False
                    elif d2 < min_d:
                        min_d = d2
                        best_idx = idx
                        rev = True
                if best_idx >= 0:
                    sp1, sp2 = unvisited.pop(best_idx)
                    next_pt = sp2 if not rev else sp1
                    chain.append(next_pt)
                    extended = True
                    if math.hypot(next_pt[0] - chain[0][0], next_pt[1] - chain[0][1]) < tol and len(chain) > 3:
                        break
            if len(chain) >= 3:
                loops.append(chain)
        return loops


    def _clip_segment_to_region(self, p0, p1, segments):
        """Clip a straight lead against the layer cross-section.

        Returns the list of sub-segments of p0->p1 that lie INSIDE the region
        bounded by `segments` (closed contours). The previous cross-hatch code
        only clamped the endpoints to the bounding box, which keeps the
        straight chord and deposits material outside the part wherever the
        cross-section is not convex.
        """
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        if abs(dx) < 1e-15 and abs(dy) < 1e-15:
            return []

        ts = [0.0, 1.0]
        for a, b in segments:
            ex, ey = b[0] - a[0], b[1] - a[1]
            denom = dx * ey - dy * ex
            if abs(denom) < 1e-15:
                continue
            t = ((a[0] - p0[0]) * ey - (a[1] - p0[1]) * ex) / denom
            u = ((a[0] - p0[0]) * dy - (a[1] - p0[1]) * dx) / denom
            if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
                ts.append(min(1.0, max(0.0, t)))
        ts.sort()
        uniq = []
        for t in ts:
            if not uniq or t - uniq[-1] > 1e-9:
                uniq.append(t)

        def inside(pt):
            # even-odd ray cast to +x
            crossings = 0
            for a, b in segments:
                if (a[1] > pt[1]) != (b[1] > pt[1]):
                    x_cross = a[0] + (pt[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    if x_cross > pt[0]:
                        crossings += 1
            return (crossings % 2) == 1

        out = []
        for i in range(len(uniq) - 1):
            tv, tn = uniq[i], uniq[i + 1]
            if tn - tv <= 1e-9:
                continue
            mid = (p0[0] + 0.5 * (tv + tn) * dx, p0[1] + 0.5 * (tv + tn) * dy)
            if inside(mid):
                out.append(((p0[0] + tv * dx, p0[1] + tv * dy),
                            (p0[0] + tn * dx, p0[1] + tn * dy)))
        return out

    def generate_toolpath_for_layer(self, z: float, layer_idx: int) -> List[Tuple[float, float, str]]:
        """
        Generate layer toolpath based on the chosen pattern (zigzag, meander, contour, crosshatch, unidirectional).
        Returns list of (x, y, command_type) where command_type is 'G0' (rapid) or 'G1' (weld).
        """
        segments = self.slice_layer_segments(z)
        toolpath = []

        if not segments:
            # Fallback toolpath across bounding box
            x0, x1 = self.xmin, self.xmax
            y_mid = (self.ymin + self.ymax) / 2.0
            toolpath.append((x0, y_mid, "G0"))
            toolpath.append((x1, y_mid, "G1"))
            return toolpath

        # Layer cross-section as a real (multi)polygon with holes: polygonize
        # reconstructs interior rings, so rasters and rings are clipped against
        # the true section instead of the raw boundary segments.
        try:
            region_full = self._layer_region(segments)
        except Exception as ex:
            self.warnings.append(
                f"layer {layer_idx}: polygonize failed ({ex}); used span-paired raster")
            region_full = None
        if region_full is None or region_full.is_empty:
            step = max(self.w * self.overlap_factor, 0.5)
            return self._raster_fallback(segments, step)

        # Step distance between infill raster lines
        step = max(self.w * self.overlap_factor, 0.5)

        # 1. Perimeter Passes: bead CENTRELINES offset bead_width/2 (then one
        # bead_width per extra pass) INSIDE the boundary. The previous version
        # deposited on the raw CAD boundary, throwing half a bead outside the
        # part, and ignored perimeters > 1 entirely (only on/off mattered).
        # When the stroke is thinner than bead_width/2 the offset vanishes:
        # keep shrinking the first ring until it survives (centre-line pass,
        # bead overflows the wall -- reported) instead of depositing nothing.
        nPer = max(int(self.perimeters), 0)
        ring0_off = self.w / 2.0
        probe = region_full.buffer(-ring0_off, join_style=2)
        if nPer > 0 and probe.is_empty:
            for frac in (0.5, 0.25, 0.125):
                ring0_off = (self.w / 2.0) * frac
                probe = region_full.buffer(-ring0_off, join_style=2)
                if not probe.is_empty:
                    break
            if probe.is_empty:
                ring0_off = 0.0
                probe = region_full
            self.warnings.append(
                f"layer {layer_idx}: cross-section thinner than bead_width/2; "
                f"deposited centre-line pass at offset {ring0_off:.2f}mm (bead overflows the CAD wall)")
        fitted_perimeters = 0
        for k in range(nPer):
            ring_region = (probe if k == 0
                           else region_full.buffer(-(self.w / 2.0 + k * self.w), join_style=2))
            if ring_region is None or ring_region.is_empty:
                break
            fitted_perimeters = k + 1
            for poly in self._polys_of(ring_region):
                self._emit_ring(toolpath, poly.exterior.coords)
                for interior in poly.interiors:
                    self._emit_ring(toolpath, interior.coords)

        # 2. Infill region: if pattern is hollow/perimeter_only, skip infill
        pattern = self.infill_pattern.lower()
        if pattern in ("hollow", "perimeter_only", "contour_only"):
            return toolpath

        # Infill region: stay inside the innermost perimeter bead (its inner
        # edge sits fitted_perimeters * bead_width in from the boundary).
        infill_region = (region_full if fitted_perimeters == 0
                         else region_full.buffer(-(fitted_perimeters * self.w), join_style=2))
        if infill_region is None or infill_region.is_empty or infill_region.area <= (step * step * 0.05):
            return toolpath

        clip_segs = self._region_boundary_segments(infill_region)
        if not clip_segs:
            return toolpath
        
        bnds = infill_region.bounds
        if len(bnds) < 4 or any(not math.isfinite(v) for v in bnds):
            return toolpath
        rx_min, ry_min, rx_max, ry_max = bnds

        def scanline_pieces(horizontal, coord):
            """Even-odd clipped pieces of a full scanline inside infill_region."""
            if not math.isfinite(coord):
                return []
            if horizontal:
                return self._clip_segment_to_region(
                    (rx_min - 1.0, coord), (rx_max + 1.0, coord), clip_segs)
            return self._clip_segment_to_region(
                (coord, ry_min - 1.0), (coord, ry_max + 1.0), clip_segs)

        def emit_pieces(pieces, horizontal, direction, allow_weld_connect, prev_end_box):
            """Emit one raster line: G0 to each piece start (or a weld connector
            when it stays inside the region), G1 along the piece."""
            if horizontal:
                ordered = sorted(pieces, key=lambda pc: min(pc[0][0], pc[1][0]))
            else:
                ordered = sorted(pieces, key=lambda pc: min(pc[0][1], pc[1][1]))
            if direction < 0:
                ordered = list(reversed(ordered))
            for (a, b) in ordered:
                if not (math.isfinite(a[0]) and math.isfinite(a[1]) and math.isfinite(b[0]) and math.isfinite(b[1])):
                    continue
                if direction < 0:
                    a, b = b, a
                prev_end = prev_end_box[0]
                started = False
                if allow_weld_connect and prev_end is not None:
                    conn = math.hypot(a[0] - prev_end[0], a[1] - prev_end[1])
                    if conn <= 1e-9:
                        started = True
                    else:
                        clip = self._clip_segment_to_region(prev_end, a, clip_segs)
                        clen = sum(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) for p1, p2 in clip)
                        if len(clip) == 1 and abs(clen - conn) < 0.05:
                            toolpath.append((a[0], a[1], "G1"))  # weld connector (inside)
                            started = True
                if not started:
                    toolpath.append((a[0], a[1], "G0"))
                toolpath.append((b[0], b[1], "G1"))
                prev_end_box[0] = (b[0], b[1])

        # 2b. Infill Strategies matching Slicer (contour, concentric, zigzag, lines, grid, triangles, hollow)

        # Strategy A: Alternating Zigzag (0° on odd layers, 90° on even layers)
        if pattern in ("zigzag", "meander"):
            is_horizontal = (layer_idx % 2 == 1)
            is_meander = (pattern == "meander")
            prev_end_box = [None]

            if is_horizontal:
                y_curr = ry_min + step / 2.0
                direction = 1 if not (self.start_reverse and layer_idx % 4 >= 2) else -1
                while y_curr <= ry_max + 1e-4:
                    emit_pieces(scanline_pieces(True, y_curr), True, direction,
                                is_meander, prev_end_box)
                    direction *= -1
                    y_curr += step
            else:
                # 90° Vertical Raster
                x_curr = rx_min + step / 2.0
                direction = 1
                while x_curr <= rx_max + 1e-4:
                    emit_pieces(scanline_pieces(False, x_curr), False, direction,
                                is_meander, prev_end_box)
                    direction *= -1
                    x_curr += step

        # Strategy B: Lines / Unidirectional (deposits only in +X with rapid return)
        elif pattern in ("unidirectional", "lines", "line"):
            prev_end_box = [None]
            y_curr = ry_min + step / 2.0
            while y_curr <= ry_max + 1e-4:
                emit_pieces(scanline_pieces(True, y_curr), True, 1, False, prev_end_box)
                y_curr += step

        # Strategy C: Cross-Hatch / Grid (Orthogonal or ±45° Diagonal Weave)
        elif pattern in ("crosshatch", "cross_hatch", "diagonal", "grid"):
            if pattern == "grid":
                # True orthogonal grid: horizontal scanlines + vertical scanlines
                prev_end_box = [None]
                y_curr = ry_min + step / 2.0
                while y_curr <= ry_max + 1e-4:
                    emit_pieces(scanline_pieces(True, y_curr), True, 1, False, prev_end_box)
                    y_curr += step
                x_curr = rx_min + step / 2.0
                while x_curr <= rx_max + 1e-4:
                    emit_pieces(scanline_pieces(False, x_curr), False, 1, False, prev_end_box)
                    x_curr += step
            else:
                angle_sign = 1 if (layer_idx % 2 == 1) else -1
                diag_span = (rx_max - rx_min) + (ry_max - ry_min)
                n_diag = max(int(diag_span / step), 1)
                direction = 1

                for d_i in range(n_diag):
                    offset = d_i * step
                    if angle_sign == 1:
                        p_start = (rx_min + offset, ry_min)
                        p_end = (rx_min, ry_min + offset)
                    else:
                        p_start = (rx_min + offset, ry_max)
                        p_end = (rx_min, ry_max - offset)

                    clipped = self._clip_segment_to_region(p_start, p_end, clip_segs)
                    for (x0, y0), (x1, y1) in clipped:
                        if (x0 - x1) ** 2 + (y0 - y1) ** 2 > (step * 0.25) ** 2:
                            if direction == 1:
                                toolpath.append((x0, y0, "G0"))
                                toolpath.append((x1, y1, "G1"))
                            else:
                                toolpath.append((x1, y1, "G0"))
                                toolpath.append((x0, y0, "G1"))
                            direction *= -1

        # Strategy D: Triangles (0°, 60°, 120° triangular lattice)
        elif pattern in ("triangles", "triangle"):
            angles_deg = [0.0, 60.0, 120.0]
            cx = (rx_min + rx_max) / 2.0
            cy = (ry_min + ry_max) / 2.0
            d_span = math.hypot(rx_max - rx_min, ry_max - ry_min) * 1.2
            for a_deg in angles_deg:
                rad = math.radians(a_deg)
                cos_a, sin_a = math.cos(rad), math.sin(rad)
                n_lines = max(int(d_span / step), 2)
                for i_l in range(-n_lines // 2, n_lines // 2 + 1):
                    disp = i_l * step
                    p_mid = (cx - sin_a * disp, cy + cos_a * disp)
                    p_start = (p_mid[0] - cos_a * d_span, p_mid[1] - sin_a * d_span)
                    p_end = (p_mid[0] + cos_a * d_span, p_mid[1] + sin_a * d_span)
                    clipped = self._clip_segment_to_region(p_start, p_end, clip_segs)
                    for (x0, y0), (x1, y1) in clipped:
                        if (x0 - x1)**2 + (y0 - y1)**2 > (step * 0.25)**2:
                            toolpath.append((x0, y0, "G0"))
                            toolpath.append((x1, y1, "G1"))

        # Strategy E: Concentric / Contour Infill (Inward Offset Loops)
        elif pattern in ("contour", "contours", "concentric", "contour_parallel",
                         "contour_infill", "offset", "offset_infill"):
            try:
                from shapely.geometry import Point
                cavity = infill_region
                if cavity is not None and not cavity.is_empty:
                    cx0, cy0 = cavity.centroid.x, cavity.centroid.y
                    curr_poly = cavity.buffer(-(step / 2.0), join_style=2)
                    max_rings = max(int(max(rx_max - rx_min, ry_max - ry_min) / max(step, 0.5)) + 5, 20)
                    ring_idx = 0
                    inner_dist = None
                    while (not curr_poly.is_empty and curr_poly.area > (step * step * 0.05)
                           and ring_idx < max_rings):
                        ring_idx += 1
                        for sp in self._polys_of(curr_poly):
                            coords = list(sp.exterior.coords)
                            if len(coords) >= 3:
                                self._emit_ring(toolpath, coords)
                                for interior in sp.interiors:
                                    self._emit_ring(toolpath, interior.coords)
                                if math.isfinite(cx0) and math.isfinite(cy0):
                                    inner_dist = min(math.hypot(px - cx0, py - cy0) for px, py in coords if math.isfinite(px) and math.isfinite(py))
                        curr_poly = curr_poly.buffer(-step, join_style=2)

                    # Centre fill if a small core remains
                    if inner_dist is None and not cavity.is_empty:
                        bnds = cavity.bounds
                        if len(bnds) == 4 and all(math.isfinite(v) for v in bnds):
                            bx0, by0, bx1, by1 = bnds
                            inner_dist = min(abs(bx1 - cx0), abs(cx0 - bx0),
                                             abs(by1 - cy0), abs(cy0 - by0))
                    if inner_dist is not None and inner_dist > 0.6 * step and math.isfinite(cx0) and math.isfinite(cy0):
                        arm = min(inner_dist, step)
                        for _ in range(4):
                            ends = [(cx0 - arm, cy0), (cx0 + arm, cy0),
                                    (cx0, cy0 - arm), (cx0, cy0 + arm)]
                            if all(cavity.covers(Point(px, py)) for px, py in ends):
                                break
                            arm *= 0.5
                        else:
                            arm = 0.0
                        if arm > 0.2 * step:
                            toolpath.append((cx0 - arm, cy0, "G0"))
                            toolpath.append((cx0 + arm, cy0, "G1"))
                            toolpath.append((cx0, cy0 - arm, "G0"))
                            toolpath.append((cx0, cy0 + arm, "G1"))
            except Exception as ex:
                self.warnings.append(
                    f"layer {layer_idx}: contour offset failed ({ex}); used span-paired raster")
                toolpath.extend(self._raster_fallback(segments, step))

        # Fallback: simple zigzag
        else:
            toolpath.extend(self._raster_fallback(segments, step))

        if not toolpath:
            # Region too thin for the requested spacing at all: never hand a
            # layer back empty. Deposit centre-line passes and say so.
            self.warnings.append(
                f"layer {layer_idx}: cross-section thinner than the bead/step; "
                f"deposited centre-line passes")
            for poly in self._polys_of(region_full):
                self._emit_ring(toolpath, poly.exterior.coords)
                for interior in poly.interiors:
                    self._emit_ring(toolpath, interior.coords)

        return toolpath

    def _raster_fallback(self, segments, step):
        """Span-paired zigzag raster over the raw slice segments.

        Crossings are paired (even-odd: [x0-x1], [x2-x3], ...) so a scanline
        that re-enters the section (holes, notches) deposits only the inside
        pieces -- the previous first-to-last span welded straight across the
        void with the arc on.
        Returns list of (x, y, command_type).
        """
        fb = []
        ly_min = min(min(s[0][1], s[1][1]) for s in segments)
        ly_max = max(max(s[0][1], s[1][1]) for s in segments)
        y_curr = ly_min + step / 2.0
        direction = 1
        while y_curr <= ly_max + 1e-4:
            xs = []
            for s1, s2 in segments:
                if (s1[1] <= y_curr <= s2[1]) or (s2[1] <= y_curr <= s1[1]):
                    dy = s2[1] - s1[1]
                    if abs(dy) > 1e-9:
                        t = (y_curr - s1[1]) / dy
                        xs.append(s1[0] + t * (s2[0] - s1[0]))
            xs.sort()
            spans = self._span_pairs(xs)
            if direction < 0:
                spans = list(reversed(spans))
            for a, b in spans:
                if direction == 1:
                    fb.append((a, y_curr, "G0"))
                    fb.append((b, y_curr, "G1"))
                else:
                    fb.append((b, y_curr, "G0"))
                    fb.append((a, y_curr, "G1"))
            if spans:
                direction *= -1
            y_curr += step
        return fb

    @staticmethod
    def _span_pairs(xs):
        """Even-odd pairing of sorted crossing coordinates: [x0-x1], [x2-x3]..."""
        spans = []
        for i in range(0, len(xs) - 1, 2):
            a, b = xs[i], xs[i + 1]
            if abs(b - a) > 1e-9:
                spans.append((a, b))
        return spans

    def _layer_region(self, segments):
        """Layer cross-section as a shapely (multi)polygon with holes.

        polygonize() reconstructs interior rings and nested islands from the
        unordered raw segments; the chained-loop union is kept as a fallback
        if shapely rejects the segment soup.
        """
        from shapely.geometry import LineString, Polygon
        from shapely.ops import unary_union, polygonize
        lines = [LineString([(s[0][0], s[0][1]), (s[1][0], s[1][1])]) for s in segments]
        merged = unary_union(lines)
        polys = [p for p in polygonize(merged) if not p.is_empty and p.area > 1e-9]
        if not polys:
            for loop in self._chain_segments_into_loops(segments):
                if len(loop) >= 3:
                    p = Polygon(loop).buffer(0)
                    if not p.is_empty and p.area > 1e-9:
                        polys.append(p)
        if not polys:
            return None
        return unary_union(polys)

    @staticmethod
    def _polys_of(region):
        """Polygon components of a shapely (multi)polygon."""
        if region is None or region.is_empty:
            return []
        geoms = list(getattr(region, "geoms", [region]))
        return [g for g in geoms
                if g.geom_type == "Polygon" and not g.is_empty and g.area > 1e-9]

    @staticmethod
    def _region_boundary_segments(region):
        """Boundary segments (exteriors + hole rings) of a polygon set."""
        segs = []
        if region is None or region.is_empty:
            return segs
        geoms = list(getattr(region, "geoms", [region]))
        for g in geoms:
            if g.geom_type != "Polygon" or g.is_empty or g.area <= 1e-9:
                continue
            rings = [g.exterior] + list(g.interiors)
            for r in rings:
                cs = list(r.coords)
                for a, b in zip(cs[:-1], cs[1:]):
                    if abs(a[0] - b[0]) > 1e-12 or abs(a[1] - b[1]) > 1e-12:
                        segs.append(((a[0], a[1]), (b[0], b[1])))
        return segs

    @staticmethod
    def _emit_ring(toolpath, coords):
        """G0 to the ring start, G1 around it, G1 back to close."""
        pts = list(coords)
        if len(pts) < 3:
            return
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        valid_pts = []
        for p in pts:
            if math.isfinite(p[0]) and math.isfinite(p[1]):
                valid_pts.append((float(p[0]), float(p[1])))
        if len(valid_pts) < 3:
            return
        toolpath.append((valid_pts[0][0], valid_pts[0][1], "G0"))
        for pt in valid_pts[1:]:
            toolpath.append((pt[0], pt[1], "G1"))
        toolpath.append((valid_pts[0][0], valid_pts[0][1], "G1"))

    def slice_to_gcode(self, output_path: str) -> dict:
        """Slice geometry and generate production G-code with comprehensive metrics."""
        z_curr = self.zmin + self.h / 2.0
        layer_idx = 0
        lines = [
            "; ============================================================",
            "; WAAM PRODUCTION TOOLPATH — AUTO-GENERATED BY WAAM-FRAMEWORK",
            "; ============================================================",
            f"; Layer Height (h_bead):   {self.h:.2f} mm",
            f"; Bead Width (W_bead):     {self.w:.2f} mm",
            f"; Infill Pattern Strategy: {self.infill_pattern.upper()}",
            f"; Infill Overlap:          {self.overlap_factor*100:.1f} %",
            f"; Welding Feedrate:        {self.feedrate:.1f} mm/min ({self.feedrate/60.0:.2f} mm/s)",
            f"; Rapid Traverse Feedrate: {self.rapid_feedrate:.1f} mm/min",
            f"; Arc Power:               {self.power:.0f} W",
            f"; Inter-Layer Dwell Pause: {self.dwell_time:.1f} s",
            f"; Part Bounding Box:       [{self.xmin:.1f}, {self.ymin:.1f}, {self.zmin:.1f}] to [{self.xmax:.1f}, {self.ymax:.1f}, {self.zmax:.1f}] mm",
            "; ============================================================",
            "G90 ; Absolute Coordinates",
            "G21 ; Millimeter Units",
            "M82 ; Absolute Extruder / Wire Feed",
            "M5 ; Arc OFF (arc is gated M3/M5 around every weld run)",
            ""
        ]

        total_pts = 0
        total_weld_dist_mm = 0.0
        total_rapid_dist_mm = 0.0
        last_pt = (0.0, 0.0)

        txt_lines = []
        t_curr = 0.0

        # Initial point
        txt_lines.append(f"{t_curr:.3f} {0.0} {0.0} {self.zmin/1000.0:.5f} 0")

        # Per-layer pass time tracking for physics-accurate simulation
        layer_pass_times = []

        # Arc / torch travel state: the M3/M5 gates and the Z hop mirror the
        # pState column of toolpath.txt (weld moves arc-on, rapids arc-off).
        arc_on = False
        hopped = False

        while z_curr <= self.zmax + 1e-4:
            layer_idx += 1
            lines.append(f"; --- LAYER {layer_idx} (Z = {z_curr:.3f} mm) ---")
            if arc_on:
                lines.append("M5 ; Arc OFF")
                arc_on = False
            lines.append(f"G0 Z{z_curr:.3f} F{self.rapid_feedrate:.0f}")
            hopped = False

            path = self.generate_toolpath_for_layer(z_curr, layer_idx)

            layer_weld_dist = 0.0
            layer_rapid_dist = 0.0
            layer_start_time = t_curr

            for x, y, move in path:
                dist = math.hypot(x - last_pt[0], y - last_pt[1])
                if move == "G1":
                    total_weld_dist_mm += dist
                    layer_weld_dist += dist
                    f_val = self.feedrate
                    p_state = 1
                    if not arc_on:
                        if hopped:
                            lines.append(f"G0 Z{z_curr:.3f} F{self.rapid_feedrate:.0f}")
                            hopped = False
                        lines.append(f"M3 S{self.power:.0f} ; Arc ON")
                        arc_on = True
                else:
                    total_rapid_dist_mm += dist
                    layer_rapid_dist += dist
                    f_val = self.rapid_feedrate
                    p_state = 0
                    if arc_on:
                        lines.append("M5 ; Arc OFF")
                        arc_on = False
                    if not hopped and self.z_hop > 0:
                        lines.append(f"G0 Z{z_curr + self.z_hop:.3f} F{self.rapid_feedrate:.0f} ; Travel retract")
                        hopped = True

                lines.append(f"{move} X{x:.3f} Y{y:.3f} F{f_val:.0f}")

                dt = (dist / (f_val / 60.0)) if f_val > 0 else 0.0
                t_curr += dt
                txt_lines.append(f"{t_curr:.3f} {x/1000.0:.5f} {y/1000.0:.5f} {z_curr/1000.0:.5f} {p_state}")

                total_pts += 1
                last_pt = (x, y)

            # Per-layer pass time = weld time + rapid time for this layer
            layer_pass_time = (layer_weld_dist / (self.feedrate / 60.0) if self.feedrate > 0 else 0.0) + \
                              (layer_rapid_dist / (self.rapid_feedrate / 60.0) if self.rapid_feedrate > 0 else 0.0)
            layer_pass_times.append(layer_pass_time)

            if self.dwell_time > 0:
                if arc_on:
                    lines.append("M5 ; Arc OFF")
                    arc_on = False
                lines.append(f"G4 P{int(self.dwell_time * 1000)} ; Inter-layer cooling dwell ({self.dwell_time}s)")
                t_curr += self.dwell_time
                txt_lines.append(f"{t_curr:.3f} {last_pt[0]/1000.0:.5f} {last_pt[1]/1000.0:.5f} {z_curr/1000.0:.5f} 0")
            lines.append("")
            z_curr += self.h

        if arc_on:
            lines.append("M5 ; Arc OFF")
        lines.append(f"G0 Z{self.zmax + 25.0:.3f} F{self.rapid_feedrate:.0f} ; Retract to safe Z")
        lines.append("; End of WAAM G-code")

        output_path = str(Path(output_path).resolve())
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write("\n".join(lines) + "\n")

        txt_path = str(Path(output_path).with_suffix(".txt"))
        with open(txt_path, 'w') as f:
            f.write(f"{len(txt_lines)}\n")
            f.write("\n".join(txt_lines) + "\n")

        # Write per-layer pass times for the FreeFEM solver
        layer_times_path = str(Path(output_path).with_suffix(".layer_times.txt"))
        with open(layer_times_path, 'w') as f:
            f.write(f"{len(layer_pass_times)}\n")
            for i, pt in enumerate(layer_pass_times):
                f.write(f"{i+1} {pt:.6f}\n")

        # Canonical solver artifacts (layer_pass_times.txt and toolpath.txt)
        parent_dir = Path(output_path).parent
        canon_lt = parent_dir / "layer_pass_times.txt"
        with open(canon_lt, 'w') as f:
            f.write(f"{len(layer_pass_times)}\n")
            for i, pt in enumerate(layer_pass_times):
                f.write(f"{i+1} {pt:.6f}\n")

        canon_tp = parent_dir / "toolpath.txt"
        if canon_tp.resolve() != Path(txt_path).resolve():
            with open(canon_tp, 'w') as f:
                f.write(f"{len(txt_lines)}\n")
                f.write("\n".join(txt_lines) + "\n")

        # Compute physics metrics
        weld_dist_m = total_weld_dist_mm / 1000.0
        bead_volume_m3 = (total_weld_dist_mm / 1000.0) * (self.w / 1000.0) * (self.h / 1000.0)
        bead_mass_kg = bead_volume_m3 * self.density
        weld_time_sec = (total_weld_dist_mm / (self.feedrate / 60.0)) if self.feedrate > 0 else 0.0
        rapid_time_sec = (total_rapid_dist_mm / (self.rapid_feedrate / 60.0)) if self.rapid_feedrate > 0 else 0.0
        dwell_total_sec = layer_idx * self.dwell_time
        total_time_min = (weld_time_sec + rapid_time_sec + dwell_total_sec) / 60.0
        energy_kj = (self.power * weld_time_sec) / 1000.0

        return {
            "output_file": output_path,
            "toolpath_path": txt_path,
            "layer_times_path": layer_times_path,
            "scale_applied": getattr(self, "scale_applied", 1.0),
            "n_layers": layer_idx,
            "n_points": total_pts,
            "warnings": list(self.warnings),
            "layer_height_mm": self.h,
            "bead_width_mm": self.w,
            "infill_pattern": self.infill_pattern,
            "total_length_m": round(weld_dist_m, 2),
            "estimated_time_min": round(total_time_min, 1),
            "bead_mass_kg": round(bead_mass_kg, 3),
            "energy_kj": round(energy_kj, 1),
            "layer_pass_times_s": layer_pass_times,
            "bounding_box": {
                "xmin": self.xmin, "xmax": self.xmax,
                "ymin": self.ymin, "ymax": self.ymax,
                "zmin": self.zmin, "zmax": self.zmax
            }
        }

def _load_medit_mesh_triangles(mesh_path: str, sub_hz_mm: float = 5.0) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]]:
    """Parse surface triangles from a Medit .mesh file, keeping deposited geometry above substrate."""
    vertices = []
    triangles = []
    with open(mesh_path, "r", errors="ignore") as f:
        lines = f.readlines()

    i = 0
    n_lines = len(lines)
    while i < n_lines:
        line = lines[i].strip()
        if line == "Vertices" and i + 1 < n_lines:
            try:
                n_verts = int(lines[i+1].strip())
                for j in range(n_verts):
                    parts = lines[i + 2 + j].split()
                    if len(parts) >= 3:
                        vertices.append((float(parts[0]), float(parts[1]), float(parts[2])))
                i += 2 + n_verts
            except Exception:
                i += 1
        elif line == "Triangles" and i + 1 < n_lines:
            try:
                n_tris = int(lines[i+1].strip())
                for j in range(n_tris):
                    parts = lines[i + 2 + j].split()
                    if len(parts) >= 3:
                        v1, v2, v3 = int(parts[0]) - 1, int(parts[1]) - 1, int(parts[2]) - 1
                        if 0 <= v1 < len(vertices) and 0 <= v2 < len(vertices) and 0 <= v3 < len(vertices):
                            triangles.append((v1, v2, v3))
                i += 2 + n_tris
            except Exception:
                i += 1
        else:
            i += 1

    if not vertices or not triangles:
        return []

    pts = np.array(vertices, dtype=np.float64)
    spans = pts.max(axis=0) - pts.min(axis=0)
    if spans.max() < 1.0:
        pts *= 1000.0

    out_tris = []
    sub_cutoff = sub_hz_mm - 0.1
    for v1, v2, v3 in triangles:
        p1 = tuple(pts[v1])
        p2 = tuple(pts[v2])
        p3 = tuple(pts[v3])
        if max(p1[2], p2[2], p3[2]) > sub_cutoff:
            out_tris.append((p1, p2, p3))

    if not out_tris:
        for v1, v2, v3 in triangles:
            out_tris.append((tuple(pts[v1]), tuple(pts[v2]), tuple(pts[v3])))

    return out_tris


def slice_geometry_to_toolpath(geometry_file: str, output_gcode: str,

                              layer_height: float = 3.0,
                              bead_width: float = 8.0,
                              infill_pattern: str = "zigzag",
                              overlap_pct: float = 75.0,
                              perimeters: int = 1,
                              feedrate: float = 600.0,
                              rapid_feedrate: float = 3000.0,
                              power: float = 3840.0,
                              dwell_time: float = 10.0,
                              start_reverse: bool = True,
                              sub_hz: float = 5.0,
                              sub_lx_mm: float = None,
                              sub_ly_mm: float = None,
                              z_hop: float = 2.0) -> dict:
    """
    High-level slicing API supporting STL, STEP, STP, IGES, IGS formats.

    sub_hz / sub_lx_mm / sub_ly_mm MUST be the same plate the volume mesher
    built (mesh/stl_pipeline.stl_to_freefem_mesh): the toolpath is centred on
    sub_lx/2, sub_ly/2 and starts at sub_hz, so any mismatch parks the torch
    away from the meshed part and nothing activates. None -> 150 mm default.
    """
    p = Path(geometry_file)
    suffix = p.suffix.lower()

    if suffix in ('.stl', '.ply', '.obj'):
        triangles = STLLoader.load(str(p))
    elif suffix in ('.step', '.stp', '.iges', '.igs', '.brep'):
        # Convert STEP/IGES to surface triangles via Gmsh OCC
        import gmsh
        gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("step_to_slicer")
        gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        gmsh.model.occ.importShapes(str(p))
        gmsh.model.occ.synchronize()

        gmsh.option.setNumber("Mesh.MeshSizeMin", max(layer_height * 0.5, 0.5))
        gmsh.option.setNumber("Mesh.MeshSizeMax", max(layer_height * 2.0, 3.0))
        gmsh.model.mesh.generate(2)

        temp_stl = str(p.with_suffix(".temp_slice.stl"))
        gmsh.write(temp_stl)
        gmsh.finalize()

        triangles = STLLoader.load(temp_stl)
        try:
            os.remove(temp_stl)
        except Exception:
            pass
    elif suffix in ('.mesh', '.mesh3'):
        # Check if source/sibling CAD file exists (e.g. original .stl / .step)
        resolved_cad = None
        cand_names = [p.stem]
        if p.stem.startswith("imported_"):
            cand_names.append(p.stem[len("imported_"):])
        for cname in cand_names:
            for ext in ('.stl', '.step', '.stp', '.ply', '.obj', '.iges', '.igs'):
                for folder in [p.parent, p.parent.parent, Path("./stl"), Path(__file__).resolve().parent.parent / "stl"]:
                    target = folder / (cname + ext)
                    if target.exists():
                        resolved_cad = target
                        break
                if resolved_cad:
                    break
            if resolved_cad:
                break

        if resolved_cad and resolved_cad.suffix.lower() != suffix:
            return slice_geometry_to_toolpath(
                geometry_file=str(resolved_cad),
                output_gcode=output_gcode,
                layer_height=layer_height,
                bead_width=bead_width,
                infill_pattern=infill_pattern,
                overlap_pct=overlap_pct,
                perimeters=perimeters,
                feedrate=feedrate,
                rapid_feedrate=rapid_feedrate,
                power=power,
                dwell_time=dwell_time,
                start_reverse=start_reverse,
                sub_hz=sub_hz,
                sub_lx_mm=sub_lx_mm,
                sub_ly_mm=sub_ly_mm,
                z_hop=z_hop
            )
        else:
            # Parse surface triangles directly from Medit .mesh file
            triangles = _load_medit_mesh_triangles(str(p), sub_hz_mm=sub_hz)
    else:
        raise ValueError(f"Unsupported geometry file format: {suffix}")


    slicer = AdvancedWAAMSlicer(
        triangles=triangles,
        layer_height=layer_height,
        bead_width=bead_width,
        infill_pattern=infill_pattern,
        overlap_pct=overlap_pct,
        perimeters=perimeters,
        feedrate=feedrate,
        rapid_feedrate=rapid_feedrate,
        power=power,
        dwell_time=dwell_time,
        start_reverse=start_reverse,
        sub_hz=sub_hz,
        sub_lx=(float(sub_lx_mm) if sub_lx_mm else 150.0),
        sub_ly=(float(sub_ly_mm) if sub_ly_mm else 150.0),
        z_hop=z_hop
    )
    return slicer.slice_to_gcode(output_gcode)
