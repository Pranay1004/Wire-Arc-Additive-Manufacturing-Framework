"""
Heat source formulations and ultrasonic coupling mixin for EDPBuilder.
"""

import math


class EDPHeatSourceMixin:
    """Assembles Goldak, P48, conical, Gaussian heat sources and ultrasonic fields."""

    _GOLDAK_95PCT = 1.0
    _GOLDAK_SAFETY = 0.85     # target 95%-footprint inside this fraction of the bead

    def _auto_size_source(self):
        """Derive Goldak axes from the bead cross-section when not set.

        Fits the 95% footprint inside the deposited volume:
            bG <= ty_dep / (2 * safety),  cG <= h_layer / (2 * safety)
            af, ar from the deposit cell size along travel (>= ~2 cells so the
            moving source is resolved rather than smeared over one cell).

        Returns the axes that were chosen so the caller can report them.
        """
        p = self.p
        hs = p.get("heat_source")
        if hs not in ("goldak", "gaussian_vol", "gaussian_surf"):
            return None
        if not bool(p.get("auto_source_sizing", True)):
            return None
        ty = float(p.get("ty_dep", 0.005))
        h1 = float(p.get("h_bead_first", p.get("h_bead", 0.004)))
        nl = max(int(p.get("n_layers", 1)), 1)
        remelt = float(p.get("remelt_ratio", 0.8))
        h_layer = h1
        lx = float(p.get("lx", 0.15))

        # Check cell size for mesh (CAD tet mesh vs Structured hexahedral grid)
        is_cad = bool(
            p.get("mesh_source") == "cad_file" or
            p.get("stl_file") or
            (p.get("mesh_file") and str(p.get("mesh_file")).lower().endswith((".mesh", ".mesh3", ".msh")))
        )

        if is_cad:
            mesh_file = str(p.get("mesh_file", ""))
            cad_cell_raw = float(p.get("step_mesh", p.get("step_mesh_size", 0.0)))
            if cad_cell_raw <= 0:
                # CAD deposit resolution is typically 0.5 * h_layer (see mesh/stl_pipeline.py lc_fine)
                cad_cell = 0.5 * h_layer
            elif cad_cell_raw > 0.05:
                cad_cell = cad_cell_raw / 1000.0  # mm to m
            else:
                cad_cell = cad_cell_raw
            # In the deposit zone, element size is governed by bead geometry
            cell = min(cad_cell, max(0.4 * ty, 0.5 * h_layer, 0.0008))
        else:
            nx_dep = max(int(p.get("nx_dep", 1)), 1)
            dx = lx / nx_dep
            ny_dep = max(int(p.get("ny_dep", 1)), 1)
            dy = ty / ny_dep
            nz_dep = max(int(p.get("nz_dep", 1)), 1)
            nz_total = int(p.get("nz_dep", 1))
            if bool(p.get("nz_dep_follows_layers", True)):
                cells_per_layer = max(nz_total / nl, 0.5)
            else:
                cells_per_layer = max(nz_total, 1)
            dz_layer = h_layer / cells_per_layer
            cell = min(dx, dy, dz_layer)

        # 1. Bead-fit cross-section (the leading rule; NEVER clamped to the
        # mesh size). The 95%-footprint radius of exp(-3 r^2 / L^2) is r = L, so
        # L = 0.45*bead/safety keeps ~96% of BOTH Gaussian axes inside the
        # deposited volume (measured combined retention 0.96). The earlier
        # "full penetration" cG >= 1.8*h_layer put ~half the source energy in
        # the layer below and tripped the bead-fit acceptance check (measured
        # retention 0.38-0.48); remelt depth is delivered by the moving source
        # tail and conduction, and is controlled by remelt_ratio in the layer
        # stack, not by inflating the arc ellipsoid.
        if hs == "goldak":
            bG = 0.45 * ty / self._GOLDAK_SAFETY
            cG = 0.45 * h_layer / self._GOLDAK_SAFETY
            # 2. Along travel: resolve the moving source (>= 2.5 / 6 cells) but
            # keep the classic elliptical ratio; these axes run over already-active
            # or soon-to-activate material, so they are floor-clamped, not shrunk.
            af = max(2.5 * cell, 0.4 * bG)
            ar = max(6.0 * cell, 1.0 * bG)
            chosen = {"bG": bG, "cG": cG, "af": af, "ar": ar}
            axis_keys = ("bG", "cG", "af", "ar")
            prev_note = (
                "The previous fixed 7/4 mm defaults put a 14 x 8 mm footprint "
                "on a 7 x 3.2 mm bead and clipped ~95% of the injected energy."
            )
        else:
            # Gaussian spot/volume sources: R_beam/R_spot is PROCESS physics
            # (beam or laser radius), not a mesh artifact -- never resized here
            # (bead-fitting a 0.5 mm laser would corrupt the process model).
            # Its resolvability is still checked below, and the runtime
            # symmetric qScale forces the injected total to exactly Pweld.
            axis_keys = ("R_beam",) if hs == "gaussian_vol" else ("R_spot",)
            prev_note = ""

        applied = {}
        if hs == "goldak":
            for key in axis_keys:
                if p.get(key) is None:
                    p[key] = chosen[key]
                    applied[key] = chosen[key]

        if applied:
            self.warnings.append(
                "AUTO-SIZED heat source to the bead cross-section: "
                + ", ".join(f"{k}={v*1000:.2f} mm" for k, v in applied.items())
                + f" (bead {ty*1000:.1f} x {h_layer*1000:.1f} mm, "
                f"min cell {cell*1000:.2f} mm). " + prev_note
            )

        # Under-resolution of ANY axis (auto or user): WARN, never resize.
        # The arc size is process physics, not mesh numerics -- silently
        # shrinking it to fit the mesh corrupts the process model.
        under = [f"{k}={float(p[k])*1000:.2f}mm" for k in axis_keys
                 if p.get(k) is not None and float(p[k]) < 2.0 * cell]
        if under:
            self.warnings.append(
                "Heat-source axes " + ", ".join(under) + f" span fewer than 2 "
                f"mesh cells ({cell*1000:.2f} mm): the assembled source is "
                f"under-resolved and its shape becomes mesh-dependent (measured "
                f"up to ~+95% quadrature over-count before correction; the run "
                f"forces the injected total back to Pweld but the peak "
                f"temperature stays mesh-limited). Refine the mesh or use "
                f"auto-sized goldak for a mesh-independent spot."
            )
        return applied


    def _heat_source_block(self) -> str:
        """Generate the heat source computation block."""
        p = self.p
        # Safety net: __init__ sizes the axes, but any path that mutates p after
        # construction (GUI/preset post-edit) could leave one None, and a None
        # axis reaches the normalization constants as a TypeError far from the
        # cause. Size here too.
        if any(p.get(k) is None for k in ("af", "ar", "bG", "cG")):
            self._auto_size_source()
        Pweld = p["I_weld"] * p["U_weld"] * p["eta_arc"]
        pi = math.pi

        if p["heat_source"] == "goldak":
            # Energy check (tanh split): the front term integrated over x>xT is
            # Q0f*abc*(pi/3)^1.5/2, so with Q0 = 3*sqrt(3)*f*P/(pi*sqrt(pi)*abc)
            # each side carries f*P/2 and total = (ff+fr)*P/2 = P for ff+fr=2.
            # (The textbook 6*sqrt(3) constant double-counts: it gives f*P per
            #  side, i.e. 2*P total when ff+fr=2.)
            Q0f = 3*math.sqrt(3)*p["ff"]*Pweld / (pi*math.sqrt(pi)*p["af"]*p["bG"]*p["cG"])
            Q0r = 3*math.sqrt(3)*p["fr"]*Pweld / (pi*math.sqrt(pi)*p["ar"]*p["bG"]*p["cG"])
            # Front/rear split smoothing scaled with the SOURCE (not an absolute
            # 1 mm, which swells to >100% of af if the source is laser-sized),
            # floored at ~1/4 element so the tanh spans the mesh.
            hx = p["lx"] / max(p["nx_dep"], 1)
            eps_split = max(0.1 * min(p["af"], p["ar"]), 0.25 * hx)
            return f"""        // Goldak double ellipsoid (normalized: int Q dV = Pweld; ff+fr=2 with Q0=3*sqrt(3)*f*P/(pi*sqrt(pi)*abc))
        {{
            real xT = xTorch; real yT = yTorch; real zT = zTorch;
            real epsSplit = {eps_split:.6e};
            // 3D tangent-aligned moving coordinate system:
            // xi is the longitudinal coordinate along the instantaneous torch travel direction (uDirX, uDirY, uDirZ).
            // rTrans2 is the transverse squared distance perpendicular to the torch path.
            Sh xi = uDirX * (x - xT) + uDirY * (y - yT) + uDirZ * (z - zT);
            Sh frontFrac = 0.5 * (1.0 + tanh(xi / epsSplit));
            Sh rearFrac  = 1.0 - frontFrac;
            Sh rTrans2   = (x - xT - xi * uDirX)^2 + (y - yT - xi * uDirY)^2;
            Tsource = ({Q0f:.6e} * exp(-3.0 * xi^2 / {p['af']}^2) * frontFrac
                     + {Q0r:.6e} * exp(-3.0 * xi^2 / {p['ar']}^2) * rearFrac)
                    * exp(-3.0 * rTrans2 / {p['bG']}^2)
                    * exp(-3.0 * (z - zT)^2 / {p['cG']}^2)
                    * psiActive;
            if((xTorch < 0. || xTorch > {p['lx']}) && nPts == 0) Tsource = 0.;
            if(nPts > 0 && pState < 0.5) Tsource = 0.; // Arc off during rapid travel
        }}"""

        elif p["heat_source"] == "gaussian_vol":
            R = p["R_beam"]
            # int exp(-3 r^2/R^2) dV = (pi R^2/3)^1.5 = R^3*pi*sqrt(pi)/(3*sqrt(3))
            # => Q0 = 3*sqrt(3)*P/(pi*sqrt(pi)*R^3). (The old 6*sqrt(3) constant
            # integrated to 2*P.)
            Q0 = 3*math.sqrt(3)*Pweld / (pi*math.sqrt(pi)*R**3)
            return f"""        // 3D Gaussian volumetric (normalized: int Q dV = Pweld)
        {{
            real xT = xTorch; real yT = yTorch; real zT = zTorch;
            // r2 MUST be a FIELD (Sh): a `real` here evaluates (x,y,z) once at
            // whatever position the last evaluation left them at -- typically a
            // far corner -- making exp(-3*r2/R^2) ~ 1e-221 EVERYWHERE and the
            // branch inject exactly zero energy. Measured: injected_arc = 0 J
            // against 95 kJ intended; Tmax stayed at Tamb for the whole build.
            Sh r2F = (x-xT)^2 + (y-yT)^2 + (z-zT)^2;
            Tsource = {Q0:.6e} * exp(-3.*r2F/{R}^2) * psiActive;
            if((xTorch<0. || xTorch>{p['lx']}) && nPts == 0) Tsource = 0.;
            if(nPts > 0 && pState < 0.5) Tsource = 0.; // Arc off during rapid travel
        }}"""

        elif p["heat_source"] == "gaussian_surf":
            # Surface flux q_s = Q0s*exp(-3 r^2/R^2) with Q0s = 3P/(pi R^2)
            # (plane integral of exp(-3r^2/R^2) = pi R^2/3), spread through the
            # current layer thickness zLayH so the volumetric integral = P.
            R = p["R_spot"]
            Q0s = 3.0 * Pweld / (pi * R * R)
            return f"""        // Gaussian surface source (normalized: int Q dV = Pweld over the layer)
        {{
            real xT = xTorch; real yT = yTorch;
            real Rspot = {R};
            real dzLayer = max(zLayH, 1.e-6);
            // Fields, not reals: see the gaussian_vol note -- scalar r2xy here
            // silently zeroed the whole source.
            Sh r2xyF = (x-xT)^2 + (y-yT)^2;
            Sh inBandF = (z >= zLayBot-1.e-9 && z <= zLayTop+1.e-9) ? 1. : 0.;
            Tsource = {Q0s:.6e}/dzLayer * exp(-3.*r2xyF/(Rspot^2)) * inBandF * psiActive;
            if((xTorch<0. || xTorch>{p['lx']}) && nPts == 0) Tsource = 0.;
            if(nPts > 0 && pState < 0.5) Tsource = 0.; // Arc off during rapid travel
        }}"""

        elif p["heat_source"] in ("p48_surface", "p48_gmaw", "p48"):
            # P48 pragmatic GMAW-WAAM model (ER70S6 / ER316L thin-wall):
            # Literature: Progress in Additive Manufacturing (2025) 10:11647-11663
            # 1. Total arc power decomposed into surface arc flux and droplet impingement:
            #    eta*U*I = Q_arc + Q_drop = (1 - eta_d)*Pweld + eta_d*Pweld
            #    where eta_d ~ 0.25 (25% transferred by droplets, 75% surface flux)
            # 2. Gaussian surface distribution radius sigma_q is current-dependent (Eq. 16):
            #    sigma_q = 6.205e-4 * I_weld^0.28 [m]
            # 3. Direct arc heat flux: q_arc = (1 - eta_d)*Pweld / (pi * sigma_q^2) * exp(-r^2 / sigma_q^2)
            # 4. Droplet impingement enthalpy addition: Q_drop distributed across active pool
            eta_d = float(p.get("eta_drop", 0.25))
            I_weld = float(p.get("I_weld", 150.0))
            sigma_q = 6.205e-4 * (max(I_weld, 10.0) ** 0.28)
            Q_arc = (1.0 - eta_d) * Pweld
            Q_drop = eta_d * Pweld
            q0_arc = Q_arc / (pi * sigma_q * sigma_q)
            return f"""        // P48 GMAW-WAAM Coupled Surface Heat Flux & Droplet Impingement Model
        // Literature: Progress in Additive Manufacturing (2025) 10:11647-11663
        // Partitioning: Q_arc = {1.0 - eta_d:.2f} * P_net ({Q_arc:.1f} W), Q_drop = {eta_d:.2f} * P_net ({Q_drop:.1f} W)
        // Empirical arc radius: sigma_q = 6.205e-4 * I^{{0.28}} = {sigma_q*1000.0:.3f} mm
        {{
            real xT = xTorch; real yT = yTorch;
            real sigQ = {sigma_q:.6e};
            real dzLayer = max(zLayH, 1.e-6);
            // Fields, not reals: see the gaussian_vol note.
            Sh r2xyF = (x-xT)^2 + (y-yT)^2;
            Sh inBandF = (z >= zLayBot-1.e-9 && z <= zLayTop+1.e-9) ? 1. : 0.;
            Sh qArcVolF = ({q0_arc:.6e} / dzLayer) * exp(-r2xyF / (sigQ^2));
            Sh qDropVolF = ({Q_drop:.6e} / (pi * sigQ^2 * dzLayer)) * exp(-r2xyF / (sigQ^2));
            Tsource = (qArcVolF + qDropVolF) * inBandF * psiActive;
            if((xTorch<0. || xTorch>{p['lx']}) && nPts == 0) Tsource = 0.;
            if(nPts > 0 && pState < 0.5) Tsource = 0.; // Arc off during rapid travel
        }}"""

        elif p["heat_source"] == "conical":
            rt, rb, d = p["rt"], p["rb"], p["d_pen"]
            # Normalization: layer power at depth zeta is Q0*pi*Rloc(zeta)^2/3.
            # Q0 = 9P/(pi*d*(rt^2+rt*rb+rb^2)) gives
            #   int_0^d Q0*pi*Rloc^2/3 dz = P  exactly.
            # The old Q0 = P/V form integrated to only P/3 (3x under-power).
            S = rt * rt + rt * rb + rb * rb
            Q0 = 9.0 * Pweld / (pi * d * max(S, 1e-18))
            return f"""        // Conical frustum (normalized: int Q dV = Pweld)
        {{
            real xT = xTorch; real yT = yTorch; real zT = zTorch;
            // Fields, not reals: see the gaussian_vol note.
            Sh zetaF = max(zT - z, 0.);
            Sh RlocF = {rt} + ({rb}-{rt})*min(zetaF/{d}, 1.);
            Sh r2xyF = (x-xT)^2 + (y-yT)^2;
            Tsource = (zetaF <= {d}+1.e-6) ?
                {Q0:.6e} * exp(-3.*r2xyF/(RlocF^2)) * psiActive : 0.;
            if((xTorch<0. || xTorch>{p['lx']}) && nPts == 0) Tsource = 0.;
            if(nPts > 0 && pState < 0.5) Tsource = 0.; // Arc off during rapid travel
        }}"""

        elif p["heat_source"] == "uniform":
            a, b, c = p["a_band"], p["b_band"], p["c_band"]
            Q0 = Pweld / (8*a*b*c)
            return f"""        // Uniform band source
        {{
            real xT = xTorch; real yT = yTorch; real zT = zTorch;
            real epsBox = 0.5e-3;
            // Fields, not reals: see the gaussian_vol note.
            Sh fxPF = 0.5*(1.+tanh((x-(xT-{a}))/epsBox));
            Sh fxNF = 0.5*(1.+tanh(((xT+{a})-x)/epsBox));
            Sh fyPF = 0.5*(1.+tanh((y-(yT-{b}))/epsBox));
            Sh fyNF = 0.5*(1.+tanh(((yT+{b})-y)/epsBox));
            Sh fzPF = 0.5*(1.+tanh((z-(zT-{c}))/epsBox));
            Sh fzNF = 0.5*(1.+tanh(((zT+{c})-z)/epsBox));
            Tsource = {Q0:.6e} * fxPF*fxNF*fyPF*fyNF*fzPF*fzNF * psiActive;
            if((xTorch<0. || xTorch>{p['lx']}) && nPts == 0) Tsource = 0.;
            if(nPts > 0 && pState < 0.5) Tsource = 0.; // Arc off during rapid travel
        }}"""

        elif p["heat_source"] == "prescribed":
            return f"""        // Prescribed temperature (no volumetric source)
        Tsource = 0.;"""

        else:
            raise ValueError(f"Unknown heat source: {p['heat_source']}")

    def _ultrasonic_thermal_block(self) -> str:
        """Generate UVA thermal physics based on paper-derived models.

        Physics from literature:
        - Acoustic intensity: I = rho*c*(2*pi*f*A)^2/2  [P53]
        - Cavitation threshold: I_cav ~ 80 W/cm2 for Mg, ~200 W/cm2 for steel [P53, P49]
        - Streaming enhancement: k_boost from empirical correlation [P56]
        - Absorption: Q = eta * 2*alpha*I*exp(-alpha*z) [P23, P26]
        - Stage-dependent: cavitation enhanced in mushy zone [P49]
        """
        p = self.p
        enable_us = bool(p.get("enable_ultrasonic", False))
        if not enable_us:
            return ""

        freq = float(p.get("ultrasonic_frequency", 0.0))
        amp = float(p.get("ultrasonic_amplitude", 15.0e-6))
        c_sound = float(p.get("ultrasonic_c_sound", 5790.0))
        eta_acou = float(p.get("ultrasonic_coupling_eff", 0.15))
        alpha_atten = float(p.get("ultrasonic_attenuation", 0.12))
        k_stream = float(p.get("ultrasonic_k_stream", 45.0))
        cav_on = bool(p.get("ultrasonic_cavitation", False))
        cav_thresh = float(p.get("ultrasonic_cav_threshold", 1.0e6))
        rho_dep = float(p.get("rho", 7850.0))
        T_liq = float(p.get("T_liq", 1520.0))
        T_sol = float(p.get("T_sol", 1450.0))
        pi = math.pi

        omega_us = 2.0 * pi * freq
        v_us = amp * omega_us
        # Acoustic intensity: I = rho*c*v^2/2 = rho*c*(omega*A)^2/2  [P53]
        i_acou = 0.5 * rho_dep * c_sound * v_us * v_us
        # Acoustic pressure amplitude: P = rho*c*omega*A  [P26]
        pacou_nom = rho_dep * c_sound * omega_us * amp
        # Volumetric dissipation: Q = 2*alpha*I  [P26]
        q_acou_vol = 2.0 * alpha_atten * i_acou
        # Streaming velocity estimate: v_stream ~ 0.1-1 m/s for typical UVA [P56]
        v_stream = 0.15 * (i_acou / (rho_dep * c_sound)) ** 0.5

        lines = []
        lines.append(f"        // --- UVA Acoustic Thermal Physics (paper-derived) ---")
        lines.append(f"        // I = rho*c*(2*pi*f*A)^2/2, P = rho*c*omega*A, Q = 2*alpha*I")
        lines.append(f"        real omegaUS = {omega_us:.6e};")
        lines.append(f"        real vUS = {v_us:.6e};")
        lines.append(f"        real Iacou = {i_acou:.6e};  // [W/m2] acoustic intensity")
        lines.append(f"        real PacouNom = {pacou_nom:.6e};  // [Pa] pressure amplitude")
        lines.append(f"        real QacouVol = {q_acou_vol:.6e};  // [W/m3] volumetric dissipation")
        lines.append(f"        real etaAcou = {eta_acou:.6e};")
        lines.append(f"        real alphaAtten = {alpha_atten:.6e};")
        lines.append(f"        real kStreamUS = {k_stream:.6e};")
        lines.append(f"        real vStreamUS = {v_stream:.6e};  // [m/s] streaming velocity")

        # Acoustic heat generation: localized to deposit wall, exponential decay [P23, P26]
        lines.append(f"        for(int iv=0; iv<Th.nv; iv++){{")
        lines.append(f"            real zv = Th(iv).z;")
        lines.append(f"            if(psiActive[][iv] > 0.5 && zv > HzBase + 1.0e-5){{")
        lines.append(f"                real distZ = zv - HzBase;")
        lines.append(f"                // Exponential attenuation with build height [P23]")
        lines.append(f"                QacouField[][iv] = etaAcou * QacouVol * exp(-alphaAtten * distZ);")
        lines.append(f"            }} else {{")
        lines.append(f"                QacouField[][iv] = 0.0;")
        lines.append(f"            }}")
        lines.append(f"        }}")

        # Streaming conductivity boost in molten pool [P56, P26]
        # Empirical: k_boost proportional to streaming velocity and pool size
        lines.append(f"        for(int iv=0; iv<Th.nv; iv++){{")
        lines.append(f"            real Tv = Temp0[][iv];")
        lines.append(f"            real zv = Th(iv).z;")
        lines.append(f"            if(zv > HzBase + 1.0e-5 && Tv >= TliqMat(zv)){{")
        lines.append(f"                // Streaming enhances effective conductivity in molten pool")
        lines.append(f"                kEff[][iv] += kStreamUS;")
        lines.append(f"            }}")
        lines.append(f"        }}")

        # Stage-dependent cavitation: enhanced in mushy zone [P49]
        if cav_on:
            lines.append(f"        // Cavitation: stage-dependent (enhanced in mushy zone)")
            lines.append(f"        real cavThresh = {cav_thresh:.6e};  // [Pa] threshold pressure")
            lines.append(f"        for(int iv=0; iv<Th.nv; iv++){{")
            lines.append(f"            real zv = Th(iv).z;")
            lines.append(f"            real Tv = Temp0[][iv];")
            lines.append(f"            if(psiActive[][iv] > 0.5 && zv > HzBase + 1.0e-5 && PacouNom > cavThresh){{")
            lines.append(f"                real distZ = zv - HzBase;")
            lines.append(f"                // Mushy zone factor: cavitation enhanced near solidification front")
            lines.append(f"                real mushyFactor = 1.0;")
            lines.append(f"                if(Tv >= {T_sol:.1f} && Tv <= {T_liq:.1f}){{")
            lines.append(f"                    mushyFactor = 2.0;  // Enhanced in mushy zone [P49]")
            lines.append(f"                }}")
            lines.append(f"                real voidFrac = min(0.3, mushyFactor * 0.1 * exp(-alphaAtten * distZ));")
            lines.append(f"                rhoEff[][iv] *= (1.0 - voidFrac);")
            lines.append(f"                QacouField[][iv] *= (1.0 + 2.0 * voidFrac);")
            lines.append(f"            }}")
            lines.append(f"        }}")

        lines.append(f"        real PAcouNow = int3d(Th)(QacouField);")
        lines.append(f"        if(PAcouNow > PacouSeenMax) PacouSeenMax = PAcouNow;")
        lines.append(f"        EarcJ += dt * int3d(Th)(QacouField);")

        return "\n".join(lines)

    def _ultrasonic_mechanical_block(self) -> str:
        """Generate UVA mechanical physics: vibration stress relief + momentum transfer.

        Emits a post-processing pass that computes acoustic stress relief (VSR)
        and acoustic momentum transfer forces. The Blaha softening is already
        applied inline in the J2 return map; this adds the post-hoc VSR truncation
        and the acoustic radiation pressure body force.
        """
        p = self.p
        enable_us = bool(p.get("enable_ultrasonic", False))
        if not enable_us:
            return ""

        freq = float(p.get("ultrasonic_frequency", 0.0))
        amp = float(p.get("ultrasonic_amplitude", 15.0e-6))
        c_sound = float(p.get("ultrasonic_c_sound", 5790.0))
        alpha_atten = float(p.get("ultrasonic_attenuation", 0.12))
        rho_dep = float(p.get("rho", 7850.0))
        pi = math.pi

        omega_us = 2.0 * pi * freq
        v_us = amp * omega_us
        i_acou = 0.5 * rho_dep * c_sound * v_us * v_us
        pacou_nom = omega_us * rho_dep * c_sound * amp
        f_acou = 2.0 * alpha_atten * i_acou / c_sound

        # Cyclic acoustic stress amplitude (empirical: ~65 MPa at 20 kHz, 15 um)
        sigma_vib_amp = 65.0e6

        lines = []
        lines.append(f"        // --- UVA Acoustic Mechanical Physics (VSR + Momentum) ---")
        lines.append(f"        real sigmaVibAmp = {sigma_vib_amp:.6e};")
        lines.append(f"        real PacouNomMech = {pacou_nom:.6e};")
        lines.append(f"        real FacouMech = {f_acou:.6e};")

        # Vibration stress relief: post-hoc yield truncation
        lines.append(f"        for(int iv=0; iv<Th.nv; iv++){{")
        lines.append(f"            real zv = Th(iv).z;")
        lines.append(f"            real sR = sigM[][iv];")
        lines.append(f"            real sY = (zv <= HzBase + 1.e-6) ? sigYieldBase : sigYieldDep;")
        lines.append(f"            real sYsoft = (1.0 - betaUS) * sY;")
        lines.append(f"            real sTotal = sR + sigmaVibAmp;")
        lines.append(f"            if(sTotal > sYsoft){{")
        lines.append(f"                real sRelieved = max(sYsoft - 0.5*sigmaVibAmp, 0.50*sY);")
        lines.append(f"                sigUVA[][iv] = min(sR, sRelieved);")
        lines.append(f"            }} else {{")
        lines.append(f"                sigUVA[][iv] = sR;")
        lines.append(f"            }}")
        lines.append(f"            reliefFrac[][iv] = (sR > 1.0e3) ? (sR - sigUVA[][iv]) / sR : 0.0;")
        lines.append(f"        }}")

        # Acoustic momentum transfer: radiation pressure body force in molten pool
        if bool(p.get("ultrasonic_momentum", False)):
            lines.append(f"        // Acoustic momentum transfer: F = 2*alpha*I/c in molten pool")
            lines.append(f"        for(int iv=0; iv<Th.nv; iv++){{")
            lines.append(f"            real zv = Th(iv).z;")
            lines.append(f"            if(psiActive[][iv] > 0.5 && zv > HzBase + 1.0e-5 && TempM[][iv] >= TliqMat(zv)){{")
            lines.append(f"                real distZ = zv - HzBase;")
            lines.append(f"                real fAcou = FacouMech * exp(-alphaAtten * distZ);")
            lines.append(f"                // Apply as equivalent thermal load (momentum -> heat)")
            lines.append(f"                // Enthalpy form: mass coefficient is rho (not rho*Cp), so")
            lines.append(f"                // divide by rho*Cp to keep the same dT contribution as the")
            lines.append(f"                // temperature-form solver did (Qacou_old = fAcou/Cp).")
            lines.append(f"                QacouField[][iv] += fAcou / max(rhoEff[][iv]*CpEff[][iv], 1.0);")
            lines.append(f"            }}")
            lines.append(f"        }}")

        lines.append(f"        real maxUVAStress = sigUVA[].max;")
        lines.append(f"        real reliefPct = (maxBaselineStress > 1.0) ? (1.0 - maxUVAStress / maxBaselineStress) * 100.0 : 0.0;")
        lines.append(f"        real maxUVADisp = maxBaselineDisp * (1.0 - 0.28 * (reliefPct / 100.0));")

        return "\n".join(lines)

