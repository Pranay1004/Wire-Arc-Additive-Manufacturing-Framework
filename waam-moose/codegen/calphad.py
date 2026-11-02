#!/usr/bin/env python3
"""
CALPHAD / solidification thermodynamics for the WAAM pipeline.
==========================================================
Computes, for each alloy, the solidification path that the thermal model
needs:

  * the **solidus** and **liquidus** (the mushy range that the enthalpy-form
    heat model turns into a latent-heat band),
  * the **latent heat** of fusion,
  * the **phase fractions vs temperature** (liquid plus the alloy family's
    solid phases) as a table the MOOSE material can interpolate,
  * the **WRC-1992 ferrite number** and the retained delta-ferrite fraction
    for the austenitic stainless steels.

Backends
--------
``pycalphad``  Real CALPHAD: equilibrium from a thermodynamic database.
               Requires the ``pycalphad`` package AND a TDB file (e.g.
               TCT-Fe). Selected automatically when both are present.
``scheil``     Built-in fallback: a Scheil solidification path with a
               composition-driven effective partition coefficient, on top of
               the WRC-1992 Cr_eq/Ni_eq equivalents already used by the
               framework's metallurgical model. Always available, needs no
               external data, and reproduces the database solidus/liquidus
               exactly, so it is a drop-in refinement rather than a
               redefinition.

The fallback is a *model*, not a thermodynamic database: it reproduces the
mushy range and the retained-phase split with the right trends and
magnitudes, but it is not a substitute for a real CALPHAD assessment. The
backend actually used is always recorded in the emitted JSON artifact so the
audit can state it.

Usage
-----
    python3 calphad.py --alloy SS308L
    python3 calphad.py --alloy SS308L --backend pycalphad --tdb TCT-Fe.tdb
    python3 calphad.py --alloy SS308L --json out.json --table
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_MOOSE_ROOT = Path(__file__).resolve().parent.parent
if str(_MOOSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOOSE_ROOT))

from core.multimaterial.alloy_metallurgy import get_alloy_category  # noqa: E402

DB_PATH = _MOOSE_ROOT / "core" / "multimaterial" / "material_database.json"


# --------------------------------------------------------------------------- #
#  WRC-1992 equivalents (shared with core/multimaterial/alloy_metallurgy.py)
# --------------------------------------------------------------------------- #

def wrc_1992_equivalents(comp: Dict[str, float]) -> Tuple[float, float]:
    """WRC-1992 Cr_eq and Ni_eq [wt%] for the austenitic stainless steels."""
    cr_eq = (comp.get("Cr", 0.0) + comp.get("Mo", 0.0)
             + 1.5 * comp.get("Si", 0.0))
    ni_eq = (comp.get("Ni", 0.0) + 30.0 * comp.get("C", 0.0)
             + 0.5 * comp.get("Mn", 0.0))
    return cr_eq, ni_eq


def ferrite_number(comp: Dict[str, float]) -> float:
    """WRC-1992 ferrite number (FN) for an austenitic stainless composition.

    Same relation the framework's physics suite validates (FN(308L) > FN(316L),
    both inside the 3-12 FN band).
    """
    cr_eq, ni_eq = wrc_1992_equivalents(comp)
    ratio = cr_eq / max(ni_eq, 1e-9)
    return min(max(4.0 + 10.0 * (ratio - 1.4), 3.0), 12.0)


def effective_partition_coefficient(comp: Dict[str, float]) -> float:
    """Effective Scheil partition coefficient for the solid-fraction path.

    Higher Cr_eq/Ni_eq (more ferrite-forming) depresses the liquidus and
    starts solidification earlier, i.e. more solute partition -> a lower k.
    Anchored so that ratio = 1.4 (FN = 4) gives k = 0.60.
    """
    cr_eq, ni_eq = wrc_1992_equivalents(comp)
    ratio = cr_eq / max(ni_eq, 1e-9)
    k = 0.60 - 0.40 * (ratio - 1.4)
    return min(max(k, 0.30), 0.90)


# --------------------------------------------------------------------------- #
#  Family phase sets
# --------------------------------------------------------------------------- #

def _family_solid_fractions(family: str, comp: Dict[str, float]) -> Tuple[Dict[str, float], str]:
    """Fully-solid phase fractions (by phase id) for a metallurgical family.

    For the austenitic stainless steels the split is the WRC-1992 ferrite
    number; for the other families it is the framework's own base default
    phase mix (ALLOY_SCHEMES[family]["base_default_phases"]).
    """
    from core.multimaterial.alloy_metallurgy import get_alloy_scheme

    if family == "Austenitic Stainless Steel":
        fn = ferrite_number(comp)
        f_ferrite = min(max(fn / 100.0, 0.0), 0.30)
        # Order matters: the first entry is the PRIMARY (first-forming) solid
        # phase. In FA mode that is delta-ferrite; austenite forms later by
        # the peritectic reaction.
        return ({"delta_ferrite": f_ferrite, "austenite": 1.0 - f_ferrite, "other": 0.0},
                "WRC-1992 ferrite number %.2f" % fn)

    scheme = get_alloy_scheme(family)
    ids = [ph["id"] for ph in scheme["phases"]]
    defaults = [float(v) for v in scheme.get("base_default_phases", [100.0, 0.0, 0.0, 0.0])]
    total = sum(defaults) or 1.0
    fracs = [d / total for d in defaults]

    out: Dict[str, float] = {}
    for index, phase_id in enumerate(ids[:3]):
        out[phase_id] = fracs[index] if index < len(fracs) else 0.0
    out["other"] = sum(fracs[3:])
    return out, "framework family default phase fractions"


# --------------------------------------------------------------------------- #
#  Result container
# --------------------------------------------------------------------------- #

@dataclass
class SolidificationModel:
    """The solidification description of one alloy."""

    alloy: str
    backend: str
    category: str
    solidus: float
    liquidus: float
    latent_heat: float
    solidification_mode: str
    ferrite_number: float
    partition_coefficient: float
    #: solid phase ids (in addition to the implicit "liquid")
    phase_names: List[str] = field(default_factory=list)
    #: temperature grid [C], ascending
    T: List[float] = field(default_factory=list)
    #: phase -> fraction on that grid ("liquid" included)
    fractions: Dict[str, List[float]] = field(default_factory=dict)
    notes: str = ""

    @property
    def mushy_range(self) -> float:
        return self.liquidus - self.solidus

    def solid_fraction(self) -> float:
        """Fully-solid fraction at the coldest grid point."""
        if not self.fractions:
            return 0.0
        return 1.0 - self.fractions["liquid"][0]

    def thermal_slots(self) -> Dict[str, List[float]]:
        """Collapse the phase set into the three slots the thermal model uses.

        MOOSE parameters are static (a material cannot declare a parameter per
        phase name), so the phase fractions are exposed as

            liquid    the molten fraction (the one the enthalpy formulation
                      and the melt-pool audit actually need),
            primary   the first solid phase to form (delta-ferrite in FA mode),
            secondary every remaining solid phase.

        The full per-phase table is kept in the JSON artifact, together with
        the real phase names, so nothing is lost.
        """
        n = len(self.T)
        liquid = list(self.fractions.get("liquid", [0.0] * n))
        primary_name = self.phase_names[0] if self.phase_names else ""
        primary = list(self.fractions.get(primary_name, [0.0] * n))
        secondary = [0.0] * n
        for name in self.phase_names[1:]:
            values = self.fractions.get(name)
            if not values:
                continue
            for i in range(min(n, len(values))):
                secondary[i] += values[i]
        return {"liquid": liquid, "primary": primary, "secondary": secondary}

    def phase_slot_names(self) -> Dict[str, str]:
        """Which real phase each thermal slot stands for."""
        primary_name = self.phase_names[0] if self.phase_names else ""
        secondary_names = ", ".join(self.phase_names[1:])
        return {
            "liquid": "liquid",
            "primary": primary_name,
            "secondary": secondary_names or "-",
        }

    def to_dict(self) -> dict:
        return {
            "alloy": self.alloy,
            "backend": self.backend,
            "category": self.category,
            "solidus_C": self.solidus,
            "liquidus_C": self.liquidus,
            "mushy_range_C": self.mushy_range,
            "latent_heat_J_per_kg": self.latent_heat,
            "solidification_mode": self.solidification_mode,
            "ferrite_number": self.ferrite_number,
            "partition_coefficient": self.partition_coefficient,
            "phase_names": self.phase_names,
            "phase_fraction_table": {
                "T": self.T,
                "fractions": self.fractions,
            },
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
#  Backends
# --------------------------------------------------------------------------- #

class CalphadBackend:
    """Base class: produce a SolidificationModel for one database entry."""

    name = "base"

    def available(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def solidification(self, alloy: str, entry: dict) -> SolidificationModel:
        raise NotImplementedError


class ScheilBackend(CalphadBackend):
    """Built-in Scheil solidification path on the database mushy range.

    The solid fraction follows the classic linear-liquidus Scheil result

        f_s(theta) = 1 - (1 - theta)^(1/(1-k)),
        theta = (T_liq - T) / (T_liq - T_sol)   in [0, 1]

    with k the effective partition coefficient. Within the mushy range the
    first solid phase (delta-ferrite in FA mode, alpha in Ti/Al, gamma in Ni)
    takes the primary fraction and the remaining solid is the second phase;
    below the solidus the fully-solid mix applies.
    """

    name = "scheil"

    def available(self) -> Tuple[bool, str]:
        return True, "built-in Scheil model (no external data required)"

    def solidification(self, alloy: str, entry: dict) -> SolidificationModel:
        comp = {k: float(v) for k, v in entry.get("composition", {}).items()}
        t_sol = float(entry["solidus"])
        t_liq = float(entry["liquidus"])
        latent = float(entry.get("latent_heat", 0.0))
        mode = entry.get("phase_transformation", {}).get("solidification_mode", "A")
        family = get_alloy_category(alloy)

        solid_mix, mix_reason = _family_solid_fractions(family, comp)
        phase_names = [name for name, value in solid_mix.items() if value > 0.0]
        if not phase_names:
            phase_names = ["other"]

        k = effective_partition_coefficient(comp) if family == "Austenitic Stainless Steel" else 0.60
        # The primary (first) solid phase carries the primary fraction.
        primary = phase_names[0]
        primary_share = solid_mix.get(primary, 1.0)

        grid = _temperature_grid(t_sol, t_liq)
        fractions: Dict[str, List[float]] = {"liquid": []}
        for name in phase_names:
            fractions[name] = []

        for temp in grid:
            if temp >= t_liq:
                fs = 0.0
            elif temp <= t_sol:
                fs = 1.0
            else:
                theta = (t_liq - temp) / max(t_liq - t_sol, 1e-9)
                fs = 1.0 - (1.0 - theta) ** (1.0 / (1.0 - k))
            fs = min(max(fs, 0.0), 1.0)

            # Primary phase forms first: it takes a share of the solid that
            # grows with the solid fraction, the rest is the secondary phase.
            prim = primary_share * fs
            rest = fs - prim
            fractions["liquid"].append(round(1.0 - fs, 6))
            for name in phase_names:
                if name == primary:
                    fractions[name].append(round(prim, 6))
                else:
                    share = solid_mix.get(name, 0.0)
                    scale = (rest / max(1.0 - primary_share, 1e-9)) if share > 0 else 0.0
                    fractions[name].append(round(share * scale, 6))

        return SolidificationModel(
            alloy=alloy,
            backend=self.name,
            category=family,
            solidus=t_sol,
            liquidus=t_liq,
            latent_heat=latent,
            solidification_mode=mode,
            ferrite_number=round(ferrite_number(comp), 3) if family == "Austenitic Stainless Steel" else 0.0,
            partition_coefficient=round(k, 4),
            phase_names=phase_names,
            T=grid,
            fractions=fractions,
            notes=("Scheil solidification on the database mushy range; effective "
                   "partition coefficient from the WRC-1992 Cr_eq/Ni_eq ratio; "
                   "fully-solid phase mix from %s." % mix_reason),
        )


class PycalphadBackend(CalphadBackend):
    """Real CALPHAD via pycalphad (equilibrium from a TDB).

    Requires:
      * the ``pycalphad`` package,
      * a thermodynamic database file (e.g. TCT-Fe.tdb) passed via ``tdb`` or
        the ``WAAM_CALPHAD_TDB`` environment variable.
    """

    name = "pycalphad"

    def __init__(self, tdb: Optional[str] = None) -> None:
        self.tdb = tdb or os.environ.get("WAAM_CALPHAD_TDB", "")
        self._db = None

    def available(self) -> Tuple[bool, str]:
        try:
            import pycalphad  # noqa: F401
        except Exception as exc:
            return False, "pycalphad is not installed (%s)" % exc
        if not self.tdb or not Path(self.tdb).exists():
            return False, ("no thermodynamic database: pass --tdb <file.tdb> or set "
                           "WAAM_CALPHAD_TDB")
        return True, "pycalphad with %s" % self.tdb

    def solidification(self, alloy: str, entry: dict) -> SolidificationModel:
        ok, why = self.available()
        if not ok:
            raise RuntimeError("pycalphad backend unavailable: %s" % why)

        from pycalphad import Database, equilibrium  # type: ignore

        if self._db is None:
            self._db = Database(self.tdb)

        comp = {k: float(v) for k, v in entry.get("composition", {}).items()}
        comps = {el: comp[el] for el in sorted(comp) if el in self._db.elements}
        if not comps:
            raise RuntimeError("no element of %s is in %s" % (alloy, self.tdb))

        t_liq = float(entry["liquidus"])
        t_sol = float(entry["solidus"])
        grid = _temperature_grid(t_sol, t_liq)

        buckets: Dict[str, List[float]] = {}
        for temp in grid:
            eq = equilibrium(self._db, comps, temp)
            phases = eq.phases
            if phases is None or not len(phases):
                for key in buckets:
                    buckets[key].append(0.0)
                continue
            names = [str(p) for p in phases]
            fracs = [float(f) for f in eq.get_phase_fraction(phases)]
            for name, frac in zip(names, fracs):
                key = _calphad_phase_key(name)
                buckets.setdefault(key, []).append(frac)
        # align lengths
        for key, values in buckets.items():
            while len(values) < len(grid):
                values.insert(0, 0.0)

        fractions: Dict[str, List[float]] = {}
        for key, values in buckets.items():
            fractions[key] = [round(v, 6) for v in values]
        if "liquid" not in fractions:
            fractions["liquid"] = [0.0] * len(grid)
        phase_names = [k for k in fractions if k != "liquid"]

        return SolidificationModel(
            alloy=alloy,
            backend=self.name,
            category=get_alloy_category(alloy),
            solidus=t_sol,
            liquidus=t_liq,
            latent_heat=float(entry.get("latent_heat", 0.0)),
            solidification_mode=entry.get("phase_transformation", {}).get("solidification_mode", "A"),
            ferrite_number=round(ferrite_number(comp), 3) if get_alloy_category(alloy) == "Austenitic Stainless Steel" else 0.0,
            partition_coefficient=round(effective_partition_coefficient(comp), 4),
            phase_names=phase_names,
            T=grid,
            fractions=fractions,
            notes="pycalphad equilibrium against %s" % self.tdb,
        )


def _calphad_phase_key(name: str) -> str:
    """Map a pycalphad phase name onto the framework's phase ids."""
    low = name.lower()
    if "liquid" in low:
        return "liquid"
    if "austenite" in low or " fcc" in low or "gamma" in low:
        return "austenite"
    if "ferrite" in low or " bcc" in low or "delta" in low:
        return "delta_ferrite"
    if "alpha" in low:
        return "alpha"
    if "beta" in low:
        return "beta"
    if "laves" in low or "gamma_prime" in low or "gamma''" in low:
        return "precipitates"
    return "other"


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _temperature_grid(t_sol: float, t_liq: float, n_mushy: int = 61,
                      t_min: float = 25.0, t_max: float = 3000.0) -> List[float]:
    """Temperature grid: dense through the mushy range, coarse outside.

    The grid must cover the whole range the temperature can reach in the
    simulation (ambient to the 2862 C boiling cap), because the MOOSE
    material interpolates the phase-fraction tables over that span.
    """
    grid: List[float] = []
    span = max(t_liq - t_sol, 1.0)
    for i in range(n_mushy):
        grid.append(t_sol + span * i / (n_mushy - 1))
    temp = int(t_liq) + 100
    while temp < t_max:
        grid.append(float(temp))
        temp += 100
    temp = int(t_sol) - 50
    while temp > t_min:
        grid.append(float(temp))
        temp -= 50
    grid.append(float(t_min))
    return sorted(set(round(t, 3) for t in grid if t_min - 1e-6 <= t <= t_max))


def load_database() -> dict:
    return json.loads(DB_PATH.read_text())["alloys"]


def select_backend(name: str = "auto", tdb: Optional[str] = None) -> CalphadBackend:
    """Pick the backend: explicit name, or the best available."""
    if name == "scheil":
        return ScheilBackend()
    if name == "pycalphad":
        backend = PycalphadBackend(tdb)
        ok, why = backend.available()
        if not ok:
            raise SystemExit("[calphad] pycalphad backend unavailable: %s" % why)
        return backend
    backend = PycalphadBackend(tdb)
    ok, why = backend.available()
    if ok:
        print("[calphad] using the pycalphad backend (%s)" % why)
        return backend
    print("[calphad] pycalphad unavailable (%s); using the built-in Scheil backend" % why)
    return ScheilBackend()


def compute_alloy(alloy: str, backend: CalphadBackend) -> SolidificationModel:
    alloys = load_database()
    if alloy not in alloys:
        raise SystemExit("[calphad] unknown alloy '%s' (have: %s)"
                         % (alloy, ", ".join(sorted(alloys))))
    return backend.solidification(alloy, alloys[alloy])


def print_table(model: SolidificationModel, rows: int = 12) -> None:
    names = ["liquid"] + model.phase_names
    print("")
    print("  %-9s %s" % ("T [C]", " ".join("%-11s" % ("f_" + n[:8]) for n in names)))
    step = max(1, len(model.T) // rows)
    for i in range(0, len(model.T), step):
        print("  %-9.1f %s" % (model.T[i],
                               " ".join("%-11.4f" % model.fractions[n][i] for n in names)))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CALPHAD solidification model for WAAM")
    ap.add_argument("--alloy", help="alloy key, e.g. SS308L")
    ap.add_argument("--backend", default="auto", choices=["auto", "scheil", "pycalphad"])
    ap.add_argument("--tdb", help="thermodynamic database for the pycalphad backend")
    ap.add_argument("--json", help="write the model(s) to this JSON file")
    ap.add_argument("--table", action="store_true", help="print the phase-fraction table")
    args = ap.parse_args(argv)

    backend = select_backend(args.backend, args.tdb)
    alloys = [args.alloy] if args.alloy else sorted(load_database().keys())

    models: Dict[str, SolidificationModel] = {}
    for name in alloys:
        try:
            model = compute_alloy(name, backend)
        except Exception as exc:
            print("[calphad] %s failed: %s" % (name, exc))
            continue
        models[name] = model
        print("")
        print("  %-12s backend=%-10s category=%s" % (name, model.backend, model.category))
        print("  solidus %.1f C   liquidus %.1f C   mushy range %.1f C   L = %.0f J/kg"
              % (model.solidus, model.liquidus, model.mushy_range, model.latent_heat))
        print("  phases: liquid + %s" % ", ".join(model.phase_names))
        if model.ferrite_number:
            print("  WRC-1992 FN = %.2f   retained delta-ferrite = %.2f%%   mode = %s"
                  % (model.ferrite_number,
                     100.0 * model.fractions.get("delta_ferrite", [0.0])[0],
                     model.solidification_mode))
        if args.table:
            print_table(model)

    if args.json:
        payload = {name: model.to_dict() for name, model in models.items()}
        Path(args.json).write_text(json.dumps(payload, indent=1))
        print("")
        print("[calphad] wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
