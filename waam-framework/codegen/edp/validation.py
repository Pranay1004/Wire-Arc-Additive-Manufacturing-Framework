"""
Parameter validation mixin for EDPBuilder.
"""

from pathlib import Path


class EDPValidationMixin:
    """Provides physical and numerical parameter validation for WAAM simulation."""

    def _validate(self):
        p = self.p
        errors = []
        self.warnings = []
        # Source sizing must run before the geometry/mesh checks below so they
        # see the final axes, and before any source block is emitted.
        self._auto_size_source()

        # Axes still unset (auto-sizing disabled): fall back to the classic
        # values and say so, instead of crashing on None in the checks below.
        if p.get("heat_source") == "goldak":
            for _key, _classic in (("af", 8.0e-3), ("ar", 20.0e-3),
                                   ("bG", 7.0e-3), ("cG", 3.0e-3)):
                if p.get(_key) is None:
                    p[_key] = _classic
                    self.warnings.append(
                        f"Heat-source {_key} unset with auto_source_sizing off; "
                        f"using classic {_classic*1000:.1f} mm. Verify it fits the bead.")

        # --- P48 GMAW-WAAM validation & arc resolution check ---
        if p.get("heat_source") in ("p48_surface", "p48_gmaw", "p48"):
            eta_d = float(p.get("eta_drop", 0.25))
            if eta_d < 0.0 or eta_d > 1.0:
                errors.append(f"P48 droplet enthalpy fraction eta_drop must be in [0, 1] (got {eta_d})")
            I_weld = float(p.get("I_weld", 150.0))
            sigma_q = 6.205e-4 * (max(I_weld, 10.0) ** 0.28)
            dx = float(p["lx"]) / max(int(p.get("nx_dep", 1)), 1)
            dy = float(p["ty_dep"]) / max(int(p.get("ny_dep", 1)), 1)
            cell_xy = max(dx, dy)
            if sigma_q < cell_xy:
                self.warnings.append(
                    f"P48 arc radius sigma_q={sigma_q*1000:.2f} mm spans fewer than 1 mesh cell in deposit "
                    f"(dx={dx*1000:.2f} mm, dy={dy*1000:.2f} mm): arc flux gradient will be under-resolved. "
                    f"Consider increasing nx_dep or ny_dep."
                )
            for _k in ("af", "ar", "bG", "cG"):
                if _k in p and p[_k] is not None:
                    p[_k] = None

        # Auto-detect if geometric dimensions were entered in millimeters instead of meters
        for dim_key, threshold in [("lx", 5.0), ("ly_base", 5.0), ("hz_base", 1.0), ("ty_dep", 1.0), ("h_bead", 0.5)]:
            val = p.get(dim_key)
            if val is not None and isinstance(val, (int, float)) and val > threshold:
                p[dim_key] = val / 1000.0
                self.warnings.append(
                    f"Auto-scaled {dim_key}: {val:.1f} -> {p[dim_key]:.4f} m "
                    f"(assumed mm input; VERIFY UNITS - a legitimate meter value this large would be wrong)"
                )

        # Auto-detect if Goldak dimensions were entered in millimeters
        for src_key in ["af", "ar", "bG", "cG", "R_beam", "R_spot", "rt", "rb", "d_pen"]:
            val = p.get(src_key)
            if val is not None and isinstance(val, (int, float)) and val > 1.0:
                p[src_key] = val / 1000.0
                self.warnings.append(
                    f"Auto-scaled {src_key}: {val:.1f} -> {p[src_key]:.4f} m "
                    f"(assumed mm input; VERIFY UNITS)"
                )

        # Physics checks
        Pweld = p["I_weld"] * p["U_weld"] * p["eta_arc"]
        if Pweld <= 0:
            errors.append(f"Arc power must be positive (got {Pweld} W)")

        if abs(p["ff"] + p["fr"] - 2.0) > 0.01:
            errors.append(f"ff + fr must equal 2.0 (got {p['ff']+p['fr']:.3f})")

        # --- Deposit mesh must resolve each layer in Z ---
        # psiActive activation and the Goldak depth axis both assume ~1 element
        # per layer. Under-resolved NzD makes layer gating span multiple layers
        # and leaves the vertical source profile meaningless.
        n_lay = int(p.get("n_layers", 1))
        nz_dep = int(p.get("nz_dep", 1))
        # One cell per layer is the geometrically clean choice, but for a tall
        # thin wall it multiplies the deposit cell count by n_layers (25 layers ->
        # 25 cells -> ~50x the deposit elements) for no accuracy gain, because the
        # layer ADVECTION is handled by activation, not by vertical resolution.
        # The cross-section (ny_dep, nz_dep over ONE layer) is what resolves the
        # source, so below 4 cells/layer the vertical count is clamped rather than
        # forced to n_layers; the warning stays because it IS a tradeoff.
        min_per_layer = int(p.get("nz_dep_min_per_layer", 0) or 0)
        if min_per_layer > 0:
            want = max(min_per_layer, 1)
            if nz_dep < n_lay * want:
                p["nz_dep"] = n_lay * want
                self.warnings.append(
                    f"Raised nz_dep {nz_dep} -> {p['nz_dep']} "
                    f"({want} cell(s) per layer x {n_lay} layers): the source "
                    f"depth (cG) must be resolved within a layer."
                )
        elif nz_dep < n_lay and bool(p.get("nz_dep_follows_layers", True)):
            p["nz_dep"] = n_lay
            suffix = " and Goldak depth resolution." if p.get("heat_source") == "goldak" else "."
            self.warnings.append(
                f"Raised nz_dep {nz_dep} -> {n_lay} (= n_layers): deposit needs "
                f">= 1 element per layer for correct psi activation{suffix}"
            )
        # --- Source/node-plane ALIGNMENT (the injection-fidelity killer) ---
        # The activation gate is z in [zLayBot, zLayTop] and the source is centred
        # on zLayMid. If the uniform deposit node spacing does not divide the
        # layer height, node planes drift out of phase with layer boundaries and a
        # layer can end up containing a single node plane sitting off the source
        # centre. Measured on the 8 x 3.2 mm wall with nz_dep=10 over 25.6 mm
        # (2.56 mm planes vs 3.20 mm layers): every layer held ONE node carrying
        # 0.38-0.90 of the peak source weight, and injection fidelity fell to
        # 49%. The heat was computed correctly and then masked off.
        # Requiring >= 2 cells per layer makes spacing <= h_layer/2, so the source
        # axis is spanned by >= 2 planes and layer boundaries fall on or near a
        # node plane.
        if p.get("heat_source") == "goldak":
            nz_eff = int(p.get("nz_dep", 1))
            if nz_eff > 0 and n_lay > 0:
                min_cells = 2 * n_lay
                if nz_eff < min_cells:
                    self.warnings.append(
                        f"nz_dep={nz_eff} gives {nz_eff/n_lay:.2f} cells per layer; "
                        f"the Goldak depth axis (cG) can then fall BETWEEN node "
                        f"planes and be masked off (measured: 49% injection fidelity "
                        f"at 1.25 cells/layer). Use nz_dep >= {min_cells} "
                        f"(= 2 x n_layers) or set nz_dep_follows_layers=False with an "
                        f"explicit count that divides the layer height."
                    )

        # P2 mechanics + J2 plasticity is BETA: the nodal Picard return map
        # churns on sharp P2 strain gradients at the activation front (measured:
        # force resid pinned at 0.17-0.37 over 150 iterations across relax/cap/dt
        # variations, while P1 converges and P2-elastic converges in 2). The
        # infrastructure (P2 spaces, dof loops, checkpoints, VTU order) is
        # complete and verified; what is missing is a consistent-tangent Newton
        # to replace Picard. P2-elastic works fully. Do not mistake BETA output
        # for validated results: unconverged solves are still refused downstream.
        if int(p.get("mechanics_order", 1)) == 2 and bool(
                p.get("enable_j2_plasticity", True)):
            self.warnings.append(
                "mechanics_order=2 with J2 plasticity is BETA: the Picard "
                "iteration may not converge on sharp fronts (consistent-tangent "
                "Newton is the defined cure). P2-elastic is fully supported. "
                "Unconverged results are refused as usual."
            )

        # Mesh vs source size (Non-blocking advisory warning on ALL Goldak axes)
        if p["heat_source"] == "goldak":
            hx = p["lx"] / max(p["nx_dep"], 1)
            hy = p["ty_dep"] / max(p["ny_dep"], 1)
            hz_dep = (p.get("h_bead_first", p.get("h_bead", 0.004))
                      + max(n_lay - 1, 0) * float(p.get("h_bead_subseq",
                         float(p.get("h_bead_first", p.get("h_bead", 0.004))) * float(p.get("remelt_ratio", 0.8))))
                      ) / max(int(p["nz_dep"]), 1)
            for axis, h, source, rec in [
                ("X", hx, p["af"], p["nx_dep"]),
                ("Y", hy, p["bG"], p["ny_dep"]),
                ("Z", hz_dep, p["cG"], p["nz_dep"]),
            ]:
                if h > source:
                    self.warnings.append(
                        f"Notice: mesh dz{axis} ({h*1000:.1f} mm) > source semi-axis "
                        f"({source*1000:.1f} mm). Peak temperature will be mesh-dependent; "
                        f"consider more elements along {axis} (current: {rec})."
                    )

        # CFL-like check (Non-blocking advisory warning)
        dx_min = p["lx"] / max(p["nx_dep"], 1)
        courant = p["v_scan"] * p["dt_weld"] / max(dx_min, 1e-9)
        if courant > 2.0:
            self.warnings.append(
                f"Notice: Courant ratio is {courant:.1f}. "
                f"Consider smaller dt_weld for finer thermal gradients."
            )

        if p["T_sol"] >= p["T_liq"]:
            errors.append("Solidus must be below liquidus")

        # Unclamped-temperature warning: with enable_boiling_cap off there is
        # no evaporation sink, and a WAAM arc routinely drives the pool past
        # the boiling point (measured: 6281 C on the DEFAULT preset, which
        # ships with the cap off). That is a legitimate "raw physics" choice,
        # but it must be a CONSCIOUS one -- temperatures above Tboil mean the
        # energy that vapourisation would have carried away is still in the
        # part, so pool dimensions and peak-T figures from such runs are not
        # comparable with capped ones.
        if not bool(p.get("enable_boiling_cap", True)):
            try:
                _p_net = (float(p.get("I_weld", 0.0)) * float(p.get("U_weld", 0.0))
                          * float(p.get("eta_arc", 0.8)))
            except (TypeError, ValueError):
                _p_net = 0.0
            self.warnings.append(
                "enable_boiling_cap is OFF: nothing removes energy above the "
                f"boiling point at {_p_net:.0f} W net arc power, so peak "
                "temperatures far above Tboil are expected and pool/peak-T "
                "figures are not comparable with capped runs. Enable the cap "
                "unless raw unclamped physics is exactly what is wanted.")

        # --- Fixture spring stiffness: derive from plate bending stiffness ---
        # k_bend = E*t^3/(12*(1-nu^2)) [N/m per unit width]; the fixture spring is
        # expressed as a multiple of this so its restraint is meaningful and
        # independent of material and thickness. An explicit k_spring_z /
        # k_spring_xy always wins (backwards compatibility).
        self._derive_fixture_stiffness()

        if errors:
            raise ValueError("Parameter validation failed:\n" +
                             "\n".join(f"  • {e}" for e in errors))

