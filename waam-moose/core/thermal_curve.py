"""thermal_curve.py — the ONE Cp/latent curve module (shared source of truth).

Extracted numerically-verbatim from ``WAAM-Framework/codegen/edp_builder.py``:

* ``smooth_cp_spike``  — edp_builder.py:21 (area-preserving edge ramps)
* ``H(T)``             — make_enthalpy_func (exact piecewise trapezoids)
* ``T(H)``             — make_inverse_enthalpy_func (exact segment roots)
* ``cp(T)``            — make_pw_func usage (piecewise-linear, clamped)

One-source-of-truth rule (calculix.md §11.2): the deck generator, the energy
audit (``stored_enthalpy``) and the hardness postprocessor must all consume
THIS curve so they can never disagree.  The FreeFEM lane keeps its emitted
code until the ship-gate switch; every numeric decision here mirrors it.

Consumers today: MOOSE ``.i`` builder (PiecewiseLinear Cp table), Moose
``WAAMThermalMaterial``/audit tests.  Consumers at ship gate: FreeFEM lane
(``from codegen.thermal_curve import ...`` replacing the inline copies).
"""

from __future__ import annotations

import json
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
MATERIAL_DB = _root / "waam-framework" / "core" / "multimaterial" / "material_database.json"
if not MATERIAL_DB.exists():
    MATERIAL_DB = _root / "WAAM-Framework" / "core" / "multimaterial" / "material_database.json"


def smooth_cp_spike(t_list, v_list, delta=2.0, slope_tol=1.0e5):
    """Replace near-vertical Cp spike edges with in-band ramps, preserving area.

    Material tables encode fusion latent heat as a tall box with ~0.01 K edges
    (e.g. 650 -> 5559 J/kg/K over 0.01 K). A Picard corrector with any finite
    temperature tolerance cannot converge across a discontinuity: predicted and
    corrected states land on opposite sides of a 5000 J/kg/K jump forever, so
    solidification/melting transients keep a ~10% energy error no iteration
    count removes (measured, then fixed here). Ramps of width ``delta`` inside
    the band make Cp continuous; the box height is raised from S to
    A_box / (width - delta) so the total latent (the table's own box area) is
    preserved exactly. Smooth tables pass through untouched. Returns new
    (T, Cp) lists.
    """
    T = [float(t) for t in t_list]
    V = [float(v) for v in v_list]
    if len(T) != len(V) or len(T) < 4:
        return t_list, v_list
    out_T, out_V = [T[0]], [V[0]]
    i = 1
    changed = False
    while i < len(T) - 1:
        dt = T[i] - T[i - 1]
        dv = V[i] - V[i - 1]
        # Up-edge of a spike box: huge positive slope over a tiny interval,
        # with the value staying high afterwards (not a data glitch).
        if dt > 0 and dt < 1.0 and dv / dt > slope_tol and i + 2 < len(T):
            # Find the matching down-edge: huge negative slope back down.
            j = i + 1
            while j < len(T) - 1:
                dt2 = T[j + 1] - T[j] if j + 1 < len(T) else 0.0
                dv2 = V[j + 1] - V[j] if j + 1 < len(T) else 0.0
                if dt2 > 0 and dt2 < 1.0 and dv2 / dt2 < -slope_tol:
                    break
                j += 1
            if j < len(T) - 1:
                Ts, base = T[i - 1], V[i - 1]
                Tl = T[j + 1]
                width = Tl - Ts
                # Box area between the edges (the latent the table encodes).
                a_box = 0.0
                for k in range(i - 1, j + 1):
                    a_box += 0.5 * (V[k] + V[k + 1]) * (T[k + 1] - T[k])
                a_box -= 0.5 * (base + V[j + 1]) * width  # above the base line
                d = min(delta, width / 4.0)
                if d > 0 and width - d > 0 and a_box > 0:
                    # The (Ts, base) point is already the last one appended;
                    # do not duplicate it (zero-width segments confuse the
                    # piecewise-linear emitter's dt guard).
                    H = a_box / (width - d)
                    out_T += [Ts + d, Tl - d, Tl]
                    out_V += [base + H, base + H, V[j + 1]]
                    i = j + 2
                    changed = True
                    continue
        out_T.append(T[i])
        out_V.append(V[i])
        i += 1
    if not changed:
        return t_list, v_list
    out_T.append(T[-1])
    out_V.append(V[-1])
    return out_T, out_V


class ThermalCurve:
    """Piecewise-linear cp(T) table with exact H(T) and T(H).

    Semantics mirror the FreeFEM emissions exactly (see module docstring):

    * ``cp`` clamps at both ends of the table.
    * ``enthalpy`` integrates the table from ``t_ref`` (0 below it) with exact
      partial trapezoids; linear continuation with the last table slope above.
    * ``temperature`` is the exact segment-root inverse used by the enthalpy
      solver; linear continuation above the table.
    """

    def __init__(self, t_list, cp_list, t_ref=25.0):
        pairs = sorted((float(t), float(v)) for t, v in zip(t_list, cp_list))
        if len(pairs) < 2:
            raise ValueError("thermal curve needs at least two breakpoints")
        self._T = [t for t, _ in pairs]
        self._V = [v for _, v in pairs]
        self.t_ref = float(t_ref)
        self._H = self._cumulative()

    @classmethod
    def from_material(cls, material: dict, cp_spike_smooth_K: float = 2.0, t_ref: float = 25.0) -> "ThermalCurve":
        """Build from a material_database.json entry.

        Table path mirrors edp_builder ``_generate_interp_functions``: the
        tabulated Cp is smoothed with ``smooth_cp_spike`` first.  Without a
        table, the smooth box-spike construction of the FreeFEM fallback is
        used (its breakpoints are already smooth; no further smoothing).
        """
        cp_data = material.get("specific_heat", {}) or {}
        cp_T = list(cp_data.get("T", []))
        cp_V = list(cp_data.get("Cp", []))
        if cp_T and cp_V:
            cp_T, cp_V = smooth_cp_spike(cp_T, cp_V, delta=cp_spike_smooth_K)
        else:
            tsol = float(material.get("solidus", 1450.0))
            tliq = float(material.get("liquidus", 1520.0))
            latent = float(material.get("latent_heat", 270000.0))
            spd = min(cp_spike_smooth_K, max((tliq - tsol) / 4.0, 1e-6))
            sph = latent / max((tliq - tsol) - spd, 1e-6)
            cp_T = [0.0, tsol, tsol + spd, tliq - spd, tliq, 3000.0]
            cp_V = [500.0, 650.0, 650.0 + sph, 650.0 + sph, 650.0, 800.0]
        return cls(cp_T, cp_V, t_ref=t_ref)

    def _cumulative(self):
        """Exact piecewise-trapezoid cumulative integral from t_ref."""
        T, V, t_ref = self._T, self._V, self.t_ref
        H = [0.0] * len(T)
        acc = 0.0
        for i in range(len(T) - 1):
            t0, v0, t1, v1 = T[i], V[i], T[i + 1], V[i + 1]
            if t1 <= t0:
                H[i + 1] = acc
                continue
            ta = max(t0, t_ref)
            if t1 <= ta:
                H[i + 1] = acc
                continue
            m = (v1 - v0) / (t1 - t0)
            va = v0 + m * (ta - t0)
            acc += 0.5 * (va + v1) * (t1 - ta)
            H[i + 1] = acc
        return H

    @property
    def breakpoints(self):
        return list(self._T), list(self._V)

    @property
    def band(self):
        return self._T[0], self._T[-1]

    def cp(self, temperature: float) -> float:
        T, V = self._T, self._V
        if temperature <= T[0]:
            return V[0]
        for i in range(len(T) - 1):
            t0, t1 = T[i], T[i + 1]
            dt = t1 - t0
            if dt < 1e-9:
                continue
            if temperature <= t1:
                return V[i] + (V[i + 1] - V[i]) * (temperature - t0) / dt
        return V[-1]

    def enthalpy(self, temperature: float) -> float:
        T, V, t_ref = self._T, self._V, self.t_ref
        if temperature <= t_ref:
            return 0.0
        acc = 0.0
        for i in range(len(T) - 1):
            t0, v0, t1, v1 = T[i], V[i], T[i + 1], V[i + 1]
            if t1 <= t0:
                continue
            ta = max(t0, t_ref)
            if t1 <= ta:
                continue
            m = (v1 - v0) / (t1 - t0)
            va = v0 + m * (ta - t0)
            if temperature <= ta:
                return acc
            if temperature <= t1:
                return acc + 0.5 * (va + (v0 + m * (temperature - t0))) * (temperature - ta)
            acc += 0.5 * (va + v1) * (t1 - ta)
        return acc + V[-1] * (temperature - T[-1])

    def temperature(self, enthalpy: float) -> float:
        if enthalpy <= 0.0:
            return self.t_ref
        T, V, t_ref = self._T, self._V, self.t_ref
        acc = 0.0
        for i in range(len(T) - 1):
            t0, v0, t1, v1 = T[i], V[i], T[i + 1], V[i + 1]
            if t1 <= t0:
                continue
            ta = max(t0, t_ref)
            if t1 <= ta:
                continue
            L = t1 - ta
            m = (v1 - v0) / (t1 - t0)
            va = v0 + m * (ta - t0)
            dH = va * L + 0.5 * m * L * L
            if dH <= 1e-12:
                continue
            if enthalpy <= acc + dH:
                if abs(m) > 1e-9:
                    rad = max(va * va + 2.0 * m * (enthalpy - acc), 0.0)
                    return ta + (-va + rad**0.5) / m
                return ta + (enthalpy - acc) / va
            acc += dH
        return T[-1] + (enthalpy - acc) / V[-1]

    def sample(self, n: int):
        """Uniform sampling for a MOOSE PiecewiseLinear table."""
        if n < 2:
            raise ValueError("need at least two sample points")
        t0, t1 = self._T[0], self._T[-1]
        step = (t1 - t0) / (n - 1)
        xs = [t0 + i * step for i in range(n)]
        return xs, [self.cp(x) for x in xs]


def load_material(name: str, db_path: Path = MATERIAL_DB) -> dict:
    """Load one alloy entry from the framework material database."""
    with open(db_path) as handle:
        db = json.load(handle)
    alloys = db.get("alloys", db)
    if name not in alloys:
        raise KeyError(f"material {name!r} not in {db_path} ({len(alloys)} entries)")
    return alloys[name]
