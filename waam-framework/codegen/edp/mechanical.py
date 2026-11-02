"""
3D thermo-elasto-plasticity, J2 radial return, and springback solver mixin.
"""

import math


class EDPMechanicalMixin:
    """Constitutive engine, incremental Newton-Raphson solver, and springback."""

    def _derive_fixture_stiffness(self) -> None:
        """Derive the fixture spring stiffness from the plate bending stiffness.

        The isostatic fixture is modelled as a Robin (penalty) spring on the
        bottom face with volumetric stiffness k_spring [N/m^3]; the total spring
        is k_spring * A_face. For that restraint to be meaningful it must be
        comparable to the substrate's own bending stiffness

            k_bend = E * t^3 / (12 * (1 - nu^2))     [N/m per unit width]

        so we express the fixture as a multiple of k_bend * L (the stiffness of
        a strip one plate-length wide). Doing this makes the fixture strength
        independent of alloy and plate thickness, and keeps the assembled
        condition number small enough for the Picard iteration to converge.

        Explicit k_spring_z / k_spring_xy values always take precedence, so any
        existing preset or user override keeps working unchanged.
        """
        p = self.p
        if p.get("k_spring_z") is not None and p.get("k_spring_xy") is not None:
            return  # user override - leave untouched

        db = self._load_db()
        base_name = p.get("material_base", p.get("substrate_material", "ER70S-6"))
        entry = self._resolve_material_entry(base_name, db) or {}

        nu = float(entry.get("poisson_ratio", p.get("nu", 0.3)))
        t = float(p["hz_base"])                       # substrate thickness [m]
        lx = float(p["lx"])
        ly = float(p.get("ly_base", lx))

        # Young's modulus at ambient from the tabulated E(T) if available.
        e_amb = None
        e_tab = (entry.get("elastic_modulus") or {}).get("E") if isinstance(
            entry.get("elastic_modulus"), dict) else None
        t_tab = (entry.get("elastic_modulus") or {}).get("T") if isinstance(
            entry.get("elastic_modulus"), dict) else None
        if e_tab and t_tab:
            try:
                j = min(range(len(t_tab)), key=lambda i: abs(float(t_tab[i]) - float(p["T_amb"])))
                e_amb = float(e_tab[j])
            except (ValueError, TypeError, IndexError):
                e_amb = None
        if not e_amb:
            e_amb = 200.0e9                              # generic steel fallback

        k_bend = e_amb * t ** 3 / (12.0 * (1.0 - nu ** 2))   # N/m per unit width
        span = 0.5 * (lx + ly)                          # characteristic face width [m]

        ratio_z = float(p.get("fixture_stiffness_ratio_z", 1.0e6))
        ratio_xy = float(p.get("fixture_stiffness_ratio_xy", 1.0e6))

        if p.get("k_spring_z") is None:
            p["k_spring_z"] = ratio_z * k_bend / max(span * span, 1e-12)
        if p.get("k_spring_xy") is None:
            p["k_spring_xy"] = ratio_xy * k_bend / max(span * span, 1e-12)

        # Guard: a fixture that is effectively rigid makes the linear system
        # ill-conditioned and the equilibrium iteration will not converge, which
        # produced meaningless (yet silently reported) springback numbers.
        # Calibrated: 4/4 solves converged at ratio 1e5, 2/4 at 1e6.
        for key, ratio in (("k_spring_z", ratio_z), ("k_spring_xy", ratio_xy)):
            if ratio > 1.0e5:
                self.warnings.append(
                    f"fixture_stiffness_ratio ({ratio:.1e} -> {key}) exceeds the "
                    "well-conditioned range: the equilibrium iteration is unlikely "
                    "to converge and any springback figure would be iteration error "
                    "rather than physics. Use 1e5 or lower."
                )


    def _mech_fe(self) -> str:
        """Fespace family for mechanics: P1 normally, P2 with mechanics_order=2."""
        return "P2" if int(self.p.get("mechanics_order", 1)) == 2 else "P1"

    def _mech_order(self) -> int:
        """Mechanics fespace order (1 or 2), validated."""
        o = int(self.p.get("mechanics_order", 1))
        if o not in (1, 2):
            raise ValueError(f"mechanics_order must be 1 or 2, got {o}")
        return o

    def _mechanical_stage_setup(self) -> str:
        p = self.p
        mo = self._mech_order()
        # Gravity body force for the mechanics load. Uses the z-dispatched
        # density already declared in the script (rhoBase/rhoDep) and psiM so
        # only activated material carries weight.
        if bool(p.get("mech_gravity", True)):
            g_val = float(p.get("gravity_m_s2", 9.81))
            # rho must be a FIELD, not the ternary that used to be written
            # inside the varf: a step in z evaluated at quadrature points is a
            # discontinuous coefficient smeared over the interface elements,
            # and it disagreed with the nodal rhoEff the thermal stage uses.
            # rhoM is the interpolated copy of rhoEff, updated every increment.
            grav_term = "int3d(Th)(rhoM * psiM * %f * (-vz))" % g_val
        else:
            grav_term = "0."
        bc_mode = p.get("mechanical_bc", "isostatic").lower()
        if bc_mode == "fixture_clamped":
            bc_code = "+ on(1, ux=0., uy=0., uz=0.) + on(2, ux=0., uy=0., uz=0.)"
        elif bc_mode == "cantilever":
            bc_code = "+ on(1, ux=0., uy=0., uz=0.)"
        else:
            bc_code = ""

        use_consistent = bool(p.get("mech_use_consistent_tangent", True))
        # Extra fields/varf for the consistent-tangent Newton path. In OFF mode
        # both expand to nothing, so the emitted script is byte-identical to
        # the pre-toggle generator output (strongest possible regression gate
        # for the validated Picard path).
        mech_tan_fields_eol = ("Mh muTan, thetaC;  // consistent-tangent "
                               "shear + return scale (Newton path only)"
                               if use_consistent else "")
        if use_consistent:
            amech_tan_varf = f"""
// Consistent-tangent stiffness (mech_use_consistent_tangent=1). Identical to
// aMech except the shear field: muTan = mu*theta carries the radial-return
// consistent shear (theta = 1-3*mu*dGamma/seq, floored), so yielded zones
// assemble their true (softened) stiffness instead of the elastic one and the
// Newton correction is correctly scaled. The volumetric response needs no
// correction -- J2 plastic flow is deviatoric, so lambdaL is already the
// exact consistent bulk response. First Newton pass has theta = 1 everywhere
// (elastic predictor); subsequent passes soften where the return flowed.
varf aMechTan([ux,uy,uz],[vx,vy,vz]) =
    int3d(Th)(
        lambdaL*(dx(ux)+dy(uy)+dz(uz))*(dx(vx)+dy(vy)+dz(vz))
      + 2.*muTan*(
            dx(ux)*dx(vx) + dy(uy)*dy(vy) + dz(uz)*dz(vz)
          + 0.5*(dy(ux)+dx(uy))*(dy(vx)+dx(vy))
          + 0.5*(dz(ux)+dx(uz))*(dz(vx)+dx(vz))
          + 0.5*(dz(uy)+dy(uz))*(dz(vy)+dy(vz))
        )
    )
    + int2d(Th, 1)(
        (clampActive*clampKz + (1.-clampActive)*clampKz*sbReg)*uz*vz
      + (clampActive*clampKxy + (1.-clampActive)*clampKxy*sbReg)*(ux*vx + uy*vy)
    )
    {bc_code};"""
        else:
            amech_tan_varf = ""
        # _validate() -> _derive_fixture_stiffness() guarantees these are set,
        # either from the plate bending stiffness or from a user override.
        k_spring_z = float(p["k_spring_z"])
        k_spring_xy = float(p["k_spring_xy"])
        sb_reg = float(p.get("springback_regularization", 1.0e-6))
        if not (0.0 < sb_reg < 1.0e-3):
            raise ValueError(
                f"springback_regularization={sb_reg:g} outside (0, 1e-3): "
                f"larger values restrain the part, zero reintroduces the "
                f"singular released system.")

        return f"""
// --- 3D NONLINEAR THERMO-ELASTO-PLASTIC CONSTITUTIVE ENGINE ---
// Mechanical state lives in Mh (P1 or P2 per mechanics_order), NEVER in Sh:
// Th.nv-indexed access is only valid for P1, so every mechanical loop below is
// dof-indexed (nDofM) with coordinates and temperature read from fields that
// exist at every dof under both orders. xxM/yyM/zzM are exact (coordinate
// interpolation reproduces node positions); TempM is the P1 temperature sampled
// at the mechanical dofs (exact: a P1 field is determined by its vertex
// values); psiM copies the binary activation (an edge midpoint straddling the
// front interpolates to exactly 0.5 and counts as active -- half a cell of
// early activation, conservative and documented).
Mh Emod, lambdaL, muL, alphaL;{mech_tan_fields_eol}
Mh epsThXX, epsThYY, epsThZZ;
Mh epsTrXX, epsTrYY, epsTrZZ, epsTrXY, epsTrXZ, epsTrYZ; // TRIP strain tensor
Mh epsPx, epsPy, epsPz, epsPxy, epsPxz, epsPyz;          // Plastic strain tensor
Mh peeq;                                                 // Equivalent plastic strain
Mh fMartOld, fBainOld;                                   // Phase history for TRIP
Mh sigInhXX, sigInhYY, sigInhZZ, sigInhXY, sigInhXZ, sigInhYZ;
Mh sigYY, sigZZ, sigXY, sigXZ, sigYZ;                    // Cauchy stress tensor components (sigXX, sigM, dispM are pre-declared)
Mh xxM = x, yyM = y, zzM = z;  // dof coordinates (exact under both orders)
Mh TempM, psiM;                // temperature / activation sampled at mech dofs
Mh rhoM;                       // density sampled at mech dofs (see grav_term)
Mh fMartM, fBainM;             // phase fractions sampled at mech dofs
int nDofM = Emod.n;

// --- Newton state (kept across incremental solves) ---
int  newtonDone = 0;        // 1 if the last solve converged
real lastNewtonResid = 0.;  // final relative force residual
real lastNewtonDres = 0.;   // final relative displacement residual
int  lastNewtonIts = 0;     // iterations used in the last solve
int mechOrderCur = {mo}; // fespace order tag for checkpoint guard
int  FinalSolidConverged = 0; // frozen verdict for the reported structural state
real warpageClampedFinal = 0.;  // uz [mm], clamped build state
real dispMaxClampedFinal = 0.;  // max displacement [mm], clamped build state
real sigMMaxClampedFinal = 0.;  // peak von Mises [MPa], clamped build state
real residFrozen = 1., dresFrozen = 1.; // Newton residuals of the reported state
int itsFrozen = 0;                      // Newton iterations of the reported state

real clampKz = {k_spring_z};
real clampKxy = {k_spring_xy};
real clampActive = 1.0; // 1.0 during welding, 0.0 post-weld (clamp release)
// Released-state regularisation, fraction of the fixture stiffness (see the
// varf comment). Parameterised: 1e-9 leaves near-nullspace modes the Picard
// iteration cannot settle (measured: free re-solve unconverged at 150 iters);
// 1e-6 settles them while restraining six orders below the fixture.
real sbReg = {sb_reg};

// J2 iteration tracing (mech_j2_debug): diagnostic only, off by default. Prints
// the state of the node with the largest plastic increment each iteration,
// which is what tells a diverging hardening law from a singular stiffness.
bool j2Debug = {str(bool(p.get("mech_j2_debug", False))).lower()};
real lastResidPrev = 1.;

// Live Variational Forms for 3D Mechanics with dynamic Robin spring clamping
// Fixture surface. Label convention follows the FreeFEM cube() ordering that
// the structured mesh reproduces: 1 = zmin (plate underside), 5 = zmax,
// 2/4 = xmax/xmin, 3/6 = ymax/ymin. A build plate rests on its table, so the
// isostatic restraint belongs on label 1 (the underside). It used to be applied
// to label 5, i.e. to the TOP of the bead plus the plate's upper face outside
// the track. That let the plate rigid-body translate and rotate almost freely:
// the bead is hot and soft, so the spring carried almost nothing, the stiffness
// matrix went nearly singular, and the Picard iteration oscillated
// (Fresid 0.34 -> 0.17, Dresid 0.47 -> 0.25) instead of converging.
varf aMech([ux,uy,uz],[vx,vy,vz]) =
    int3d(Th)(
        lambdaL*(dx(ux)+dy(uy)+dz(uz))*(dx(vx)+dy(vy)+dz(vz))
      + 2.*muL*(
            dx(ux)*dx(vx) + dy(uy)*dy(vy) + dz(uz)*dz(vz)
          + 0.5*(dy(ux)+dx(uy))*(dy(vx)+dx(vy))
          + 0.5*(dz(ux)+dx(uz))*(dz(vx)+dx(vz))
          + 0.5*(dz(uy)+dy(uz))*(dz(vy)+dy(vz))
        )
    )
    // Clamp release vs singularity. The old code kept a 1e2 N/m^3 baseline alive
    // after release, so the "free" springback solve reported a spring-supported
    // part. Removing it entirely makes the released system SINGULAR instead --
    // the isostatic mode carries no Dirichlet conditions, so the direct solver
    // returns an arbitrary nullspace combination (measured: 2.1e7 mm "warpage",
    // i.e. kilometres, with a converged residual). The middle path below keeps
    // a regularization spring at 1e-9 of the fixture stiffness, active ONLY in
    // the released state: nine orders below the restraint it replaces, so its
    // pull on the deformation is negligible, while the six rigid modes gain
    // finite (if soft) eigenvalues and the solve is unique. The defined proper
    // fix is a 3-2-1 isostatic point support; until that lands, this term is
    // labelled for what it is and the reported delta is guarded below against
    // rigid-body runaway.
    + int2d(Th, 1)(
        (clampActive*clampKz + (1.-clampActive)*clampKz*sbReg)*uz*vz
      + (clampActive*clampKxy + (1.-clampActive)*clampKxy*sbReg)*(ux*vx + uy*vy)
    )
    {bc_code};
{amech_tan_varf}
varf lMech([ux,uy,uz],[vx,vy,vz]) =
    int3d(Th)(
        sigInhXX*dx(vx) + sigInhYY*dy(vy) + sigInhZZ*dz(vz)
      + sigInhXY*(dy(vx)+dx(vy))
      + sigInhXZ*(dz(vx)+dx(vz))
      + sigInhYZ*(dz(vy)+dy(vz))
    )
    // Self-weight. REQUIRED to capture melt-pool sagging, blow-through and loss
    // of wall height (the defects in the reference figure): with no body force
    // molten metal has nothing pushing it down, so it keeps the shape of the bead
    // it was born in no matter how far above liquidus it gets. The solver had NO
    // gravity term at all, which made those defects unmodellable by construction.
    // rho is z-dispatched and psiM is the same activation field the stiffness
    // uses, so only material that exists carries weight, and melted metal
    // (full weight, no strength) sags.
    + {grav_term}
    ;
"""

    def _mechanical_stage_solve(self) -> str:
        """Entry point: run one incremental mechanics step.

        Kept as the public name because it is spliced into the generated script at
        the inter-pass and final-cooling call sites. All the work happens in
        _mechanical_stage_increment(), which _mechanical_stage_springback() also
        reuses after releasing the fixture.
        """
        p = self.p
        enable_us = bool(p.get("enable_ultrasonic", False))
        freq = float(p.get("ultrasonic_frequency", 0.0)) if enable_us else 0.0
        softening_factor = 1.0 - min(0.3, freq / 100000.0) if (enable_us and freq > 0) else 1.0
        nlgeom = bool(p.get("nlgeom", False))

        inc = self._mechanical_stage_increment()
        mo = self._mech_order()
        uva_mech = self._ultrasonic_mechanical_block()

        # Final bookkeeping / VTU dump, shared by every increment.
        tail = f"""
        dispM = sqrt(ux^2+uy^2+uz^2);
        cout << "  -> Transient Peak Displacement: " << dispM[].max*1000. << " mm | Vertical Warpage (Uz): " << uz[].max*1000. << " mm | Peak Stress: " << sigM[].max/1.e6 << " MPa" << endl;
        cout << "  -> Equilibrium: " << lastNewtonIts << " Newton iterations, "
             << "force resid " << lastNewtonResid << ", disp resid " << lastNewtonDres
             << (newtonDone ? "  [CONVERGED]" : "  [NOT CONVERGED - max iters]") << endl;

        // Feature 4: Geometric Nonlinearity (NLGEOM)
        if ({1 if nlgeom else 0} == 1) {{
            Th = movemesh3(Th, transfo=[x + ux, y + uy, z + uz]);
            cout << "  -> NLGEOM: mesh coordinates updated with current displacement field." << endl;
        }}

        // UVA mechanical physics (vibration stress relief + momentum transfer)
        {uva_mech}

        string numM;
        if      (frame<   10) numM="000"+frame;
        else if (frame<  100) numM="00" +frame;
        else if (frame< 1000) numM="0"  +frame;
        else                  numM=""   +frame;
        
        {{
            int mechOrd = {mo};
            int[int] ord=[mechOrd,mechOrd,mechOrd,mechOrd,mechOrd,mechOrd,mechOrd,mechOrd,mechOrd,mechOrd];
            savevtk(visdir+"waam_mech_"+numM+".vtu", Th,
                ux, uy, uz, dispM, Tpeak, peeq, sigM, sigXX, epsPx, epsPy,
                dataname="Ux Uy Uz DispMag Tpeak PEEQ vonMises_Pa Sxx_Pa EpsP_xx EpsP_yy",
                order=ord);
        }}
        {{
            int[int] ord2 = [1,1,1,1,1,1,1];
            savevtk(visdir+"waam_uva_"+numM+".vtu", Th,
                sigUVA, reliefFrac, QacouField,
                dataname="SigUVA_Pa ReliefFrac QacouField_W_m3",
                order=ord2);
        }}
"""
        return inc + tail

    def _mechanical_stage_increment(self) -> str:
        """Emit one incremental thermo-elasto-plastic equilibrium solve.

        Method: elastic predictor / plastic corrector with a Newton loop on the
        global residual. Each iteration (a) forms the trial elastic stress from
        the total strain minus the committed eigenstrain/plastic strain, (b)
        performs the J2 radial return to obtain the updated plastic strain and
        Cauchy stress, and (c) rebuilds the internal-force RHS. Convergence is
        measured on BOTH the residual force norm (R = F_ext - F_int) and the
        incremental displacement norm, which is the same criterion Abaqus uses
        for its equilibrium check. When "mech_use_consistent_tangent" is on, the
        elastic predictor is scaled by the standard radial-return consistent
        moduli so Newton converges quadratically near the solution instead of
        only linearly.
        """
        p = self.p
        enable_us = bool(p.get("enable_ultrasonic", False))
        freq = float(p.get("ultrasonic_frequency", 0.0)) if enable_us else 0.0
        softening_factor = 1.0 - min(0.3, freq / 100000.0) if (enable_us and freq > 0) else 1.0
        enable_j2 = bool(p.get("enable_j2_plasticity", True))
        enable_j2_str = "1" if enable_j2 else "0"
        h_prime = float(p.get("h_prime_iso", 1.5e9))
        j2_relax = float(p.get("mech_j2_relax", 1.0))
        dgamma_max = float(p.get("mech_dgamma_max", 1.0))
        peeq_limit = float(p.get("peeq_limit", 0.25))
        plastic_tol = float(p.get("mech_plastic_tol", 1.0e-3))
        max_newton = max(1, int(p.get("mech_max_newton_iter", 12)))
        newton_tol = float(p.get("mech_newton_tol", 1.0e-6))
        newton_tol_f = float(p.get("mech_newton_tol_force", 1.0e-6))
        trip_beta = float(p.get("trip_beta", 0.011))

        mo = self._mech_order()

        use_consistent = bool(p.get("mech_use_consistent_tangent", True))
        OFF_VECS_TXT = f"""        bool vecSized = false;
        real[int] Kux(0), fPrev(0), uCur(0), uPrev(0);"""
        OFF_SIGINH_TXT = f"""            // 2a. Internal force from the committed plastic + eigenstrain
            for(int iv=0; iv<nDofM; iv++){{
                real lam = lambdaL[][iv];
                real muu = muL[][iv];
                real eXX = epsPx[][iv] + epsThXX[][iv] + epsTrXX[][iv];
                real eYY = epsPy[][iv] + epsThYY[][iv] + epsTrYY[][iv];
                real eZZ = epsPz[][iv] + epsThZZ[][iv] + epsTrZZ[][iv];
                real trE = eXX + eYY + eZZ;
                sigInhXX[][iv] = lam*trE + 2.*muu*eXX;
                sigInhYY[][iv] = lam*trE + 2.*muu*eYY;
                sigInhZZ[][iv] = lam*trE + 2.*muu*eZZ;
                sigInhXY[][iv] = 2.*muu*(epsPxy[][iv] + epsTrXY[][iv]);
                sigInhXZ[][iv] = 2.*muu*(epsPxz[][iv] + epsTrXZ[][iv]);
                sigInhYZ[][iv] = 2.*muu*(epsPyz[][iv] + epsTrYZ[][iv]);
            }}

"""
        OFF_SOLVE_TXT = f"""            // 2b. Tangent and internal-force vector
            matrix KM = aMech(Vh, Vh);
            set(KM, solver={self.solver_kw});
            real[int] fEig = lMech(0, Vh);
            if(!vecSized){{
                Kux.resize(fEig.n); fPrev.resize(fEig.n);
                uCur.resize(fEig.n); uPrev.resize(fEig.n);
                uPrev = uCur; vecSized = true;
            }}

            // 2c. Solve the linearised equilibrium K u = f_int(eps_p_current)
            ux[] = KM^-1 * fEig;

            // 2d. Out-of-balance force against the PREVIOUS iterate's internal
            //     force: R_n = K u_n - f_int(u_prev). Using f_int(u_n) instead
            //     would give R == 0 identically (since u_n solves exactly that
            //     linearised system) and the force test would be vacuous.
            //     f_int(u_prev) is already in fPrev from the previous pass.
            real Rnorm = 0.;
            Kux = KM*ux[];
            if(nIter == 0){{
                // No previous iterate yet: seed with the elastic predictor so
                // Fref reflects the initial out-of-balance magnitude.
                for(int i=0; i<fEig.n; i++) Rnorm += fEig[i]*fEig[i];
                fPrev = fEig;
            }} else {{
                for(int i=0; i<fEig.n; i++){{
                    real ri = Kux[i] - fPrev[i];
                    Rnorm += ri*ri;
                }}
                fPrev = fEig;
            }}
            Rnorm = sqrt(Rnorm);
            if(nIter == 0) Fref = max(Rnorm, 1.);

            // 2e. Displacement change since the previous iterate, measured in
            //     flat dof space (component slices of a vector fespace cannot be
            //     used as scalar fields in FreeFEM, so this is done on dofs).
            uCur = ux[];
            real Dnorm = 0.;
            for(int i=0; i<uCur.n; i++){{
                real di = uCur[i] - uPrev[i];
                if(abs(di) > Dnorm) Dnorm = abs(di);
            }}
            uPrev = uCur;

"""
        OFF_J2_TXT = f"""            // 2f. J2 return map on the stress implied by the new displacement,
            //     updating the committed plastic strain (this is what makes the
            //     next iteration's internal force different).

            real maxDpeeq = 0.0;
            real maxPeeqTotal = 0.0;
            real dbgMu=0., dbgSigY=0., dbgFY=0., dbgDG=0., dbgSeq=0., dbgT=0., dbgPe=0.;
            int dbgIv=0;
            for(int iv=0; iv<nDofM; iv++){{
                real px = xxM[][iv], py = yyM[][iv], pz = zzM[][iv];
                if(psiM[][iv] < 0.5 || TempM[][iv] >= TsolMat(pz)) continue;
                real exx = dx(ux)(px,py,pz);
                real eyy = dy(uy)(px,py,pz);
                real ezz = dz(uz)(px,py,pz);
                real exy = 0.5*(dy(ux)(px,py,pz) + dx(uy)(px,py,pz));
                real exz = 0.5*(dz(ux)(px,py,pz) + dx(uz)(px,py,pz));
                real eyz = 0.5*(dz(uy)(px,py,pz) + dy(uz)(px,py,pz));

                real eeXX = exx - epsPx[][iv] - epsThXX[][iv] - epsTrXX[][iv];
                real eeYY = eyy - epsPy[][iv] - epsThYY[][iv] - epsTrYY[][iv];
                real eeZZ = ezz - epsPz[][iv] - epsThZZ[][iv] - epsTrZZ[][iv];
                real eeXY = exy - epsPxy[][iv] - epsTrXY[][iv];
                real eeXZ = exz - epsPxz[][iv] - epsTrXZ[][iv];
                real eeYZ = eyz - epsPyz[][iv] - epsTrYZ[][iv];

                real trEe = eeXX + eeYY + eeZZ;
                real devXX = eeXX - trEe/3.0;
                real devYY = eeYY - trEe/3.0;
                real devZZ = eeZZ - trEe/3.0;

                real muu = muL[][iv];
                real lam = lambdaL[][iv];
                real sTrialXX = 2.*muu*devXX;
                real sTrialYY = 2.*muu*devYY;
                real sTrialZZ = 2.*muu*devZZ;
                real sTrialXY = 2.*muu*eeXY;
                real sTrialXZ = 2.*muu*eeXZ;
                real sTrialYZ = 2.*muu*eeYZ;

                real J2 = 0.5*(sTrialXX*sTrialXX + sTrialYY*sTrialYY + sTrialZZ*sTrialZZ)
                        + sTrialXY*sTrialXY + sTrialXZ*sTrialXZ + sTrialYZ*sTrialYZ;
                real seqTrial = sqrt(3.0 * max(J2, 0.0));

                real sigY0 = (pz <= HzBase + 1.e-6) ? sigYieldBase : sigYieldDep;
                real Tfact = max(0.05, 1.0 - 0.85 * min(1.0, max(0.0, (TempM[][iv]-Tamb)/(TsolMat(pz)-Tamb))));
                // Acoustic softening acts on the flow stress: sigY is the
                // critical resolved shear at which plasticity starts, so a
                // vibrated bead yields earlier without any change to E.
                real sigY = (sigY0 * Tfact + HprimeIso * peeq[][iv]) * softenF;
                real fYield = seqTrial - sigY;

                if({enable_j2_str} == 1 && fYield > 0.0){{
                    // Successive under-relaxation of the plastic increment.
                    // The Picard/Jacobi update re-derives dGamma from the current
                    // displacement every iteration; with sharp P2 strain gradients
                    // the full step overshoots and limit-cycles (measured: force
                    // resid pinned at 0.37 over 150 iterations where P1 converges).
                    // Scaling the APPLIED increment by j2Relax < 1 damps the cycle
                    // without moving the fixed point (at convergence fYield = 0
                    // so dGamma = 0 whatever the factor). Default 1.0 (validated
                    // P1 path); P2 runs need ~0.5.
                    // Trust region on the plastic step. With sharp P2 strain
                    // gradients the raw dGamma is enormous and successive iterates
                    // chase hotspot-to-hotspot without settling (measured force
                    // resid pinned at 0.37 over 150 iterations). Capping the
                    // APPLIED step does not move the fixed point: at convergence
                    // fYield -> 0 so dGamma -> 0, below any cap. It only bounds
                    // the transient path, like any trust-region method. Default
                    // 1.0 = off (validated P1 path untouched); P2 needs ~0.005.
                    real dGamma = min(j2Relax * fYield / (3.0 * muu + HprimeIso),
                                      dGammaMax);
                    // Plastic flow must be bounded per node. The Picard loop
                    // re-evaluates the trial stress from the current displacement
                    // every iteration and adds a FRESH dGamma onto the accumulated
                    // peeq, so an uncapped accumulator diverges: measured peeq
                    // 0.68 -> 1.23 over 16 iterations at T=879 C, with the
                    // hardening modulus feeding itself (sigY 1126 -> 1959 MPa) and
                    // never reaching a fixed point. A weld bead cannot absorb 123%
                    // plastic strain; beyond ~peeq_limit the material has localised
                    // and failed, which Abaqus represents with *DEFORMATION
                    // PLASTICITY damage rather than unbounded flow. Past the cap
                    // the node stops accumulating and stops hardening.
                    real dGamEff = dGamma;
                    if(peeq[][iv] >= peeqLimit) dGamEff = 0.;
                    // The APPLIED increment is dGamEff. The old line advanced the
                    // state by the raw dGamma while tracking dGamEff for the
                    // convergence measure, so a node at the cap kept hardening
                    // (and kept accumulating) while the monitor reported a
                    // zero increment.
                    peeq[][iv] = min(peeq[][iv] + dGamEff, peeqLimit);
                    if(dGamEff > maxDpeeq){{
                        maxDpeeq = dGamEff; dbgIv = iv; dbgMu = muu; dbgSigY = sigY;
                        dbgFY = fYield; dbgDG = dGamEff; dbgSeq = seqTrial;
                        dbgT = TempM[][iv]; dbgPe = peeq[][iv];
                    }}

                    real nFactor = 1.5 * dGamEff / max(seqTrial, 1.0);
                    epsPx[][iv] += nFactor * sTrialXX;
                    epsPy[][iv] += nFactor * sTrialYY;
                    epsPz[][iv] += nFactor * sTrialZZ;
                    epsPxy[][iv] += nFactor * sTrialXY;
                    epsPxz[][iv] += nFactor * sTrialXZ;
                    epsPyz[][iv] += nFactor * sTrialYZ;

                    real scaleS = max(0.0, 1.0 - 3.0*muu*dGamEff/max(seqTrial, 1.0));
                    real pHyd = lam*trEe;
                    sigXX[][iv] = pHyd + scaleS*sTrialXX;
                    sigYY[][iv] = pHyd + scaleS*sTrialYY;
                    sigZZ[][iv] = pHyd + scaleS*sTrialZZ;
                    sigXY[][iv] = scaleS*sTrialXY;
                    sigXZ[][iv] = scaleS*sTrialXZ;
                    sigYZ[][iv] = scaleS*sTrialYZ;
                    sigM[][iv]  = sigY + HprimeIso*dGamEff;
                }} else {{
                    real pHyd = lam*trEe;
                    sigXX[][iv] = pHyd + sTrialXX;
                    sigYY[][iv] = pHyd + sTrialYY;
                    sigZZ[][iv] = pHyd + sTrialZZ;
                    sigXY[][iv] = sTrialXY;
                    sigXZ[][iv] = sTrialXZ;
                    sigYZ[][iv] = sTrialYZ;
                    sigM[][iv]  = seqTrial;
                }}
            }}

            for(int iv=0; iv<nDofM; iv++)
                if(peeq[][iv] > maxPeeqTotal) maxPeeqTotal = peeq[][iv];

            if(j2Debug){{
                cout << "    [J2] it=" << nIter
                     << " Tres=" << lastResidPrev
                     << " mu=" << dbgMu/1.e9
                     << " sigY=" << dbgSigY/1.e6
                     << " seq=" << dbgSeq/1.e6
                     << " fY=" << dbgFY/1.e6
                     << " dGam=" << dbgDG
                     << " peeq=" << dbgPe
                     << " T=" << dbgT
                     << " (node " << dbgIv << ")" << endl;
            }}

"""
        ON_J2_TXT = f"""            // 2f. J2 return map on the stress implied by the new displacement,
            //     updating the committed plastic strain (this is what makes the
            //     next iteration's internal force different).

            real maxDpeeq = 0.0;
            real maxPeeqTotal = 0.0;
            real dbgMu=0., dbgSigY=0., dbgFY=0., dbgDG=0., dbgSeq=0., dbgT=0., dbgPe=0.;
            int dbgIv=0;
            for(int iv=0; iv<nDofM; iv++){{
                real px = xxM[][iv], py = yyM[][iv], pz = zzM[][iv];
                if(psiM[][iv] < 0.5 || TempM[][iv] >= TsolMat(pz)) continue;
                real exx = dx(ux)(px,py,pz);
                real eyy = dy(uy)(px,py,pz);
                real ezz = dz(uz)(px,py,pz);
                real exy = 0.5*(dy(ux)(px,py,pz) + dx(uy)(px,py,pz));
                real exz = 0.5*(dz(ux)(px,py,pz) + dx(uz)(px,py,pz));
                real eyz = 0.5*(dz(uy)(px,py,pz) + dy(uz)(px,py,pz));

                real eeXX = exx - epsPx[][iv] - epsThXX[][iv] - epsTrXX[][iv];
                real eeYY = eyy - epsPy[][iv] - epsThYY[][iv] - epsTrYY[][iv];
                real eeZZ = ezz - epsPz[][iv] - epsThZZ[][iv] - epsTrZZ[][iv];
                real eeXY = exy - epsPxy[][iv] - epsTrXY[][iv];
                real eeXZ = exz - epsPxz[][iv] - epsTrXZ[][iv];
                real eeYZ = eyz - epsPyz[][iv] - epsTrYZ[][iv];

                real trEe = eeXX + eeYY + eeZZ;
                real devXX = eeXX - trEe/3.0;
                real devYY = eeYY - trEe/3.0;
                real devZZ = eeZZ - trEe/3.0;

                real muu = muL[][iv];
                real lam = lambdaL[][iv];
                real sTrialXX = 2.*muu*devXX;
                real sTrialYY = 2.*muu*devYY;
                real sTrialZZ = 2.*muu*devZZ;
                real sTrialXY = 2.*muu*eeXY;
                real sTrialXZ = 2.*muu*eeXZ;
                real sTrialYZ = 2.*muu*eeYZ;

                real J2 = 0.5*(sTrialXX*sTrialXX + sTrialYY*sTrialYY + sTrialZZ*sTrialZZ)
                        + sTrialXY*sTrialXY + sTrialXZ*sTrialXZ + sTrialYZ*sTrialYZ;
                real seqTrial = sqrt(3.0 * max(J2, 0.0));

                real sigY0 = (pz <= HzBase + 1.e-6) ? sigYieldBase : sigYieldDep;
                real Tfact = max(0.05, 1.0 - 0.85 * min(1.0, max(0.0, (TempM[][iv]-Tamb)/(TsolMat(pz)-Tamb))));
                // Acoustic softening acts on the flow stress: sigY is the
                // critical resolved shear at which plasticity starts, so a
                // vibrated bead yields earlier without any change to E.
                real sigY = (sigY0 * Tfact + HprimeIso * peeq[][iv]) * softenF;
                real fYield = seqTrial - sigY;

                if({enable_j2_str} == 1 && fYield > 0.0){{
                    // Successive under-relaxation of the plastic increment.
                    // The Picard/Jacobi update re-derives dGamma from the current
                    // displacement every iteration; with sharp P2 strain gradients
                    // the full step overshoots and limit-cycles (measured: force
                    // resid pinned at 0.37 over 150 iterations where P1 converges).
                    // Scaling the APPLIED increment by j2Relax < 1 damps the cycle
                    // without moving the fixed point (at convergence fYield = 0
                    // so dGamma = 0 whatever the factor). Default 1.0 (validated
                    // P1 path); P2 runs need ~0.5.
                    // Trust region on the plastic step. With sharp P2 strain
                    // gradients the raw dGamma is enormous and successive iterates
                    // chase hotspot-to-hotspot without settling (measured force
                    // resid pinned at 0.37 over 150 iterations). Capping the
                    // APPLIED step does not move the fixed point: at convergence
                    // fYield -> 0 so dGamma -> 0, below any cap. It only bounds
                    // the transient path, like any trust-region method. Default
                    // 1.0 = off (validated P1 path untouched); P2 needs ~0.005.
                    real dGamma = min(j2Relax * fYield / (3.0 * muu + HprimeIso),
                                      dGammaMax);
                    // Plastic flow must be bounded per node. The Picard loop
                    // re-evaluates the trial stress from the current displacement
                    // every iteration and adds a FRESH dGamma onto the accumulated
                    // peeq, so an uncapped accumulator diverges: measured peeq
                    // 0.68 -> 1.23 over 16 iterations at T=879 C, with the
                    // hardening modulus feeding itself (sigY 1126 -> 1959 MPa) and
                    // never reaching a fixed point. A weld bead cannot absorb 123%
                    // plastic strain; beyond ~peeq_limit the material has localised
                    // and failed, which Abaqus represents with *DEFORMATION
                    // PLASTICITY damage rather than unbounded flow. Past the cap
                    // the node stops accumulating and stops hardening.
                    real dGamEff = dGamma;
                    if(peeq[][iv] >= peeqLimit) dGamEff = 0.;
                    // The APPLIED increment is dGamEff. The old line advanced the
                    // state by the raw dGamma while tracking dGamEff for the
                    // convergence measure, so a node at the cap kept hardening
                    // (and kept accumulating) while the monitor reported a
                    // zero increment.
                    peeq[][iv] = min(peeq[][iv] + dGamEff, peeqLimit);
                    if(dGamEff > maxDpeeq){{
                        maxDpeeq = dGamEff; dbgIv = iv; dbgMu = muu; dbgSigY = sigY;
                        dbgFY = fYield; dbgDG = dGamEff; dbgSeq = seqTrial;
                        dbgT = TempM[][iv]; dbgPe = peeq[][iv];
                    }}

                    real nFactor = 1.5 * dGamEff / max(seqTrial, 1.0);
                    epsPx[][iv] += nFactor * sTrialXX;
                    epsPy[][iv] += nFactor * sTrialYY;
                    epsPz[][iv] += nFactor * sTrialZZ;
                    epsPxy[][iv] += nFactor * sTrialXY;
                    epsPxz[][iv] += nFactor * sTrialXZ;
                    epsPyz[][iv] += nFactor * sTrialYZ;

                    real scaleS = max(0.0, 1.0 - 3.0*muu*dGamEff/max(seqTrial, 1.0));
                    thetaC[][iv] = max(0.05, scaleS);  // consistent-tangent scale
                    real pHyd = lam*trEe;
                    sigXX[][iv] = pHyd + scaleS*sTrialXX;
                    sigYY[][iv] = pHyd + scaleS*sTrialYY;
                    sigZZ[][iv] = pHyd + scaleS*sTrialZZ;
                    sigXY[][iv] = scaleS*sTrialXY;
                    sigXZ[][iv] = scaleS*sTrialXZ;
                    sigYZ[][iv] = scaleS*sTrialYZ;
                    sigM[][iv]  = sigY + HprimeIso*dGamEff;
                }} else {{
                    real pHyd = lam*trEe;
                    sigXX[][iv] = pHyd + sTrialXX;
                    sigYY[][iv] = pHyd + sTrialYY;
                    sigZZ[][iv] = pHyd + sTrialZZ;
                    sigXY[][iv] = sTrialXY;
                    sigXZ[][iv] = sTrialXZ;
                    sigYZ[][iv] = sTrialYZ;
                    sigM[][iv]  = seqTrial;
                    thetaC[][iv] = 1.0;  // elastic: full shear stiffness
                }}
            }}

            for(int iv=0; iv<nDofM; iv++)
                if(peeq[][iv] > maxPeeqTotal) maxPeeqTotal = peeq[][iv];

            if(j2Debug){{
                cout << "    [J2] it=" << nIter
                     << " Tres=" << lastResidPrev
                     << " mu=" << dbgMu/1.e9
                     << " sigY=" << dbgSigY/1.e6
                     << " seq=" << dbgSeq/1.e6
                     << " fY=" << dbgFY/1.e6
                     << " dGam=" << dbgDG
                     << " peeq=" << dbgPe
                     << " T=" << dbgT
                     << " (node " << dbgIv << ")" << endl;
            }}

"""
        if use_consistent:
            newton_vecs = ("real[int] Rv(0), duv(0);\n"
                           "        bool nvecSized = false;\n")
            tangent_init = "        // Consistent-tangent state reset (Newton path): theta = 1\n        // (elastic) until the first return pass writes the yielded values.\n        for(int iv=0; iv<nDofM; iv++){\n            thetaC[][iv] = 1.0;\n            muTan[][iv] = muL[][iv];\n        }\n"
            kela_assembly = f"""// Elastic stiffness assembled ONCE per increment: E(T) is fixed
        // for the whole solve, so Kela never changes. It serves the true
        // residual R = F_load - Kela*u every iteration (one matvec each, no
        // refactorisation).
        matrix Kela = aMech(Vh, Vh);
        set(Kela, solver={self.solver_kw});
        """
            solve_block = f"""            // 2b. TRUE OUT-OF-BALANCE from the current state.
            //     R = F_load - Kela*u, with F_load from the eigenstress
            //     refreshed from this pass's return just below. No lagged
            //     previous-iterate force: the old test compared against fPrev,
            //     which made it vacuous whenever the load barely moved.
            real[int] fLoad = lMech(0, Vh);
            real[int] KuEla = Kela*ux[];
            if(!nvecSized){{ 
                Rv.resize(fLoad.n); duv.resize(fLoad.n);
                nvecSized = true;
            }}
            real Rnorm = 0.;
            for(int i=0; i<fLoad.n; i++){{ 
                Rv[i] = fLoad[i] - KuEla[i];
                Rnorm += Rv[i]*Rv[i];
            }}
            Rnorm = sqrt(Rnorm);
            if(nIter == 0) Fref = max(Rnorm, 1.);

            // 2c. CONSISTENT-TANGENT Newton correction: Ktan*du = R.
            //     Ktan carries muTan = mu*theta (radial-return consistent
            //     shear; the volumetric response is exact for J2). First pass
            //     has theta = 1 everywhere: the elastic predictor.
            matrix Ktan = aMechTan(Vh, Vh);
            set(Ktan, solver={self.solver_kw});
            duv = Ktan^-1*Rv;

            // 2d. Apply the correction; incremental-displacement norm.
            real Dnorm = 0.;
            for(int i=0; i<duv.n; i++){{ 
                ux[][i] = ux[][i] + duv[i];
                if(abs(duv[i]) > Dnorm) Dnorm = abs(duv[i]);
            }}"""

            solve_block = solve_block + "\n"
            tangent_update = "        // Consistent shear from this pass's return: mu_tan = mu*theta.\n        // Volumetric response needs no correction (J2 flow is deviatoric).\n        for(int iv=0; iv<nDofM; iv++){\n            muTan[][iv] = muL[][iv]*thetaC[][iv];\n        }\n"
            # The Newton residual is R = f_eigen - Kela*u, so the load vector
            # MUST carry the committed inelastic eigenstrain. This was left
            # empty, so lMech() returned gravity alone and the whole mechanical
            # solve was a self-weight problem: both the elastic baseline and
            # the J2 run reported ~0.001 MPa peak stress with identical
            # results. Refreshed at the top of every Newton pass from the
            # eps_p / eps_tr updated by the previous pass's return map, which
            # is the same fixed-point equation the linear path solves
            # (K u = f_int(eps_p, eps_th, eps_tr)) with a consistent-tangent
            # correction matrix.
            siginh_block = OFF_SIGINH_TXT
            j2_block = ON_J2_TXT
        else:
            newton_vecs = OFF_VECS_TXT + "\n"
            tangent_init = ""
            kela_assembly = ""
            solve_block = OFF_SOLVE_TXT
            tangent_update = ""
            siginh_block = OFF_SIGINH_TXT
            j2_block = OFF_J2_TXT
        return f"""
        // --- Incremental thermo-elasto-plastic equilibrium solve ---
        real softenF = {softening_factor};
        real HprimeIso = {h_prime};      // Isotropic hardening modulus [Pa]
        real j2Relax = {j2_relax};        // Picard damping on dGamma (see above)
        real dGammaMax = {dgamma_max};    // trust-region cap (see above)
        real peeqLimit = {peeq_limit};   // strain-localisation cap [dimensionless]
        real plasticTol = {plastic_tol};  // relative plastic-increment tolerance
        real betaTrans = {trip_beta};    // Austenite -> Martensite/Bainite volumetric expansion ratio
        // Reference scale for the relative-convergence test. It must NOT be taken
        // from the current displacement: on the first solve u is still zero, which
        // collapses the denominator and produces a meaningless ratio. Instead we
        // use the natural displacement magnitude of this problem -- the free
        // thermal expansion of the peak temperature over the model size -- which
        // is known before the solve starts.
        real alphaPeak = max(alphaMat(Tpeak[].max, HzBase/2.), 1.e-9);
        real uChar = max(alphaPeak * max(Tpeak[].max - Tamb, 0.) * HzTot, 1.e-11);
        // Sample P1 fields onto the mechanical dofs. Exact for Temp (a P1
        // field is fixed by its vertex values) and for coordinates; phase
        // fractions and activation interpolate linearly (documented above).
        TempM = Temp; psiM = psiActive; rhoM = rhoEff;
        fMartM = fMartensite; fBainM = fBainite;
        real uRef = max(abs(ux[].max) + abs(ux[].min), uChar);
        real Fref = 0.;                                        // reference internal-force scale

        // 1. Annealing, eigenstrain (thermal + TRIP), and modulus update.
        // Dof-indexed (order-agnostic): coordinates, temperature and activation
        // come from the sampled fields, never from Th(iv) / Th.nv.
        for(int iv=0; iv<nDofM; iv++){{
            real zv = zzM[][iv];
            real Tv = TempM[][iv];
            real TsolNode = TsolMat(zv);
            real psiEff = max(psiM[][iv], 1.e-4);

            // Feature 2: High-Temperature Annealing & Plastic Memory Loss
            if(Tv >= TsolNode){{
                peeq[][iv]    = 0.0;
                epsPx[][iv]   = 0.0; epsPy[][iv]   = 0.0; epsPz[][iv]   = 0.0;
                epsPxy[][iv]  = 0.0; epsPxz[][iv]  = 0.0; epsPyz[][iv]  = 0.0;
                epsTrXX[][iv] = 0.0; epsTrYY[][iv] = 0.0; epsTrZZ[][iv] = 0.0;
                epsTrXY[][iv] = 0.0; epsTrXZ[][iv] = 0.0; epsTrYZ[][iv] = 0.0;
                sigXX[][iv]   = 0.0; sigYY[][iv]   = 0.0; sigZZ[][iv]   = 0.0;
                sigXY[][iv]   = 0.0; sigXZ[][iv]   = 0.0; sigYZ[][iv]   = 0.0;
                // Liquid/slurry cutoff. Above solidus the node is treated as a
                // very soft 'slurry' so it cannot carry load. It must not be
                // SOFT that it is effectively unrestrained though: at 1e6 Pa the
                // node contributes ~3.8e5 Pa of shear stiffness, i.e. a nearly
                // free-floating dof that sits in the stiffness matrix and in the
                // load vector while the J2 loop skips it. That singular dof is
                // what pinned the equilibrium iteration at Dresid ~0.57 in the
                // layer-2 solve (Tmax 1485 C > Tsol 1450 C). A small fraction of
                // the surrounding solid stiffness keeps the dof well posed
                // without letting the melted region carry meaningful stress.
                real EmodSolid = EMat(TsolMat(zv)-1., zv);
                Emod[][iv]    = max(1.e6, 0.02*EmodSolid); // 2% of solid stiffness
            }} else {{
                // NOTE: no softenF here. The elastic modulus is a
                // lattice-elastic quantity and is not what ultrasonic
                // assistance reduces -- softening the modulus would lower the
                // bending stiffness and change the whole stress field, not the
                // plastic limit. The factor is applied to the yield surface
                // inside the J2 return below.
                Emod[][iv]    = EMat(Tv, zv)*psiEff;
            }}

            // Feature 3: Thermal Expansion Strain
            real alph = alphaMat(Tv, zv);
            real deltaT = Tv - Tamb;
            if(psiM[][iv] > 0.5){{
                epsThXX[][iv] = alph * deltaT;
                epsThYY[][iv] = alph * deltaT;
                epsThZZ[][iv] = alph * deltaT;
            }} else {{
                epsThXX[][iv] = 0.0; epsThYY[][iv] = 0.0; epsThZZ[][iv] = 0.0;
            }}

            // Feature 3: TRIP (Transformation-Induced Plasticity) & Volumetric Dilation
            real dFmart = max(0.0, fMartM[][iv] - fMartOld[][iv]);
            real dFbain = max(0.0, fBainM[][iv] - fBainOld[][iv]);
            real dFtrans = dFmart + dFbain;
            fMartOld[][iv] = fMartM[][iv];
            fBainOld[][iv] = fBainM[][iv];

            if(dFtrans > 1.e-4 && psiM[][iv] > 0.5 && Tv < TsolNode){{
                real epsVol = (1.0/3.0) * betaTrans * dFtrans;
                real sigYNode = (zv <= HzBase + 1.e-6) ? sigYieldBase : sigYieldDep;
                real tripCoeff = (5.0/6.0) * (betaTrans / max(sigYNode, 1.e6)) * dFtrans;
                real meanS = (sigXX[][iv] + sigYY[][iv] + sigZZ[][iv]) / 3.0;
                epsTrXX[][iv] += tripCoeff * (sigXX[][iv] - meanS) + epsVol;
                epsTrYY[][iv] += tripCoeff * (sigYY[][iv] - meanS) + epsVol;
                epsTrZZ[][iv] += tripCoeff * (sigZZ[][iv] - meanS) + epsVol;
                epsTrXY[][iv] += tripCoeff * sigXY[][iv];
                epsTrXZ[][iv] += tripCoeff * sigXZ[][iv];
                epsTrYZ[][iv] += tripCoeff * sigYZ[][iv];
            }}
        }}

        lambdaL = Emod*nuS/((1.+nuS)*(1.-2.*nuS));
        muL     = Emod/(2.*(1.+nuS));

        newtonDone = 0; lastNewtonIts = 0; lastNewtonResid = 1.; lastNewtonDres = 1.;

        // 2. Equilibrium iteration on the thermo-elasto-plastic problem.
        //
        //    The eigenstrain (thermal expansion + TRIP) is a TOTAL quantity and
        //    so is the plastic strain, so the equilibrium equation to solve is
        //        K(u) u = f_int(eps_th, eps_p(u))
        //    i.e. it is nonlinear only through the plastic strain. The natural
        //    iteration is therefore a Jacobi/Picard iteration on eps_p, which is
        //    what we do: each iteration (a) assembles the internal force from the
        //    current committed plastic + eigenstrain, (b) solves K u = f_int, and
        //    (c) return-maps the trial stress to update eps_p.
        //
        //    What this adds over the previous implementation, which simply ran a
        //    fixed number of iterations and only watched the plastic increment,
        //    is a genuine equilibrium test on the two quantities Abaqus checks:
        //      * the out-of-balance force  R_n = K u_n - f_int(u_n-1)
        //      * the displacement change   du = u_n - u_n-1
        //    so a run now reports CONVERGED / NOT CONVERGED honestly instead of
        //    silently stopping after N iterations.
        //
        //    The verdict is frozen into FinalSolidConverged here, at the end of
        //    THIS solve, instead of being read from newtonDone at write-out time.
        //    The springback stage re-solves and overwrites newtonDone, so a failed
        //    clamped solve followed by a converged unclamped re-solve used to
        //    report mechanics_converged=true and publish warpage and stress that
        //    were pure iteration error.
        // The Picard iteration converges LINEARLY and slowly here: the plastic
        // field must relax across the whole plate before the out-of-balance force
        // settles. Measured on the bonded 2-layer benchmark the layer-2 solve
        // needed 145 iterations to reach Fresid 5.6e-5; at the previous default
        // of 40 it stalled at 0.39 and the run published iteration error as a
        // result. 150 is the measured requirement for that case, not a guess.
        int maxNewt = {max_newton};
{newton_vecs}{tangent_init}{kela_assembly}        for(int nIter=0; nIter<maxNewt; nIter++){{
{siginh_block}{solve_block}{j2_block}{tangent_update}            // 2e. Convergence: force residual AND incremental displacement.
            real relR = Rnorm / max(Fref, 1.);
            real relD = Dnorm / max(uRef, 1.e-12);
            lastNewtonResid = relR; lastNewtonDres = relD; lastNewtonIts = nIter + 1;

            lastResidPrev = relR;
            // Plastic-flow criterion. An ABSOLUTE bound on the plastic increment
            // is the wrong test for a Picard iteration: the last node still
            // shedding plasticity decays as ~1/n, so it would need hundreds of
            // iterations to fall under 1e-5 even while the force and
            // displacement residuals are already ~1e-4. Abaqus instead compares
            // the increment to the ACCUMULATED equivalent plastic strain (a
            // relative PCTOL), which asks the physical question: has plastic flow
            // stopped relative to how much strain the node has already taken?
            bool plasticSettled = (maxDpeeq <= plasticTol * max(maxPeeqTotal, 1.e-4));
            if(relR < {newton_tol_f} && relD < {newton_tol} && plasticSettled){{
                newtonDone = 1;
                break;
            }}
        }}

        FinalSolidConverged = newtonDone;
        residFrozen = lastNewtonResid; dresFrozen = lastNewtonDres; itsFrozen = lastNewtonIts;
        warpageClampedFinal = uz[].max*1000.;
        dispMaxClampedFinal = dispM[].max*1000.;
        sigMMaxClampedFinal = sigM[].max/1.e6;

        if(!newtonDone)
            cout << "  [WARN] Mechanics did not converge in " << maxNewt
                 << " iterations (Fresid=" << lastNewtonResid
                 << ", Dresid=" << lastNewtonDres << "). Results may be unconverged." << endl;
"""

    def _mechanical_stage_springback(self) -> str:
        """Release the fixture and re-solve to obtain the true springback.

        This is the Abaqus "unclamping" benchmark from the WAAM literature: with
        the clamp springs removed, the elastically-strained plate redistributes
        its residual stress into additional deflection. The delta between the
        clamped and unclamped warpage is the springback, reported separately.
        """
        return f"""
        // --- Springback: release the fixture and re-equilibrate ---
        // Springback is only valid if BOTH the clamped and the unclamped state
        // reached equilibrium. An unconverged unclamped re-solve produces a
        // large apparent "springback" that is pure iteration error, so we gate
        // the reported delta on the convergence flag.
        {{
            int sbClampedConverged = newtonDone;
            real warpageClamped = uz[].max*1000.;
            real dispMaxClamped = dispM[].max*1000.;
            real sigMMaxClamped = sigM[].max/1.e6;
            int sbSavedConverged = FinalSolidConverged;
            real residSaved = residFrozen, dresSaved = dresFrozen; int itsSaved = itsFrozen;
            clampActive = 0.0;    // release the fixture springs
            cout << "  [SPRINGBACK] Releasing fixture (clampActive=0) and re-solving..." << endl;
            {self._mechanical_stage_increment()}
            int sbFreeConverged = newtonDone;
            real warpageUnclamped = uz[].max*1000.;
            // Rigid-body runaway guard: a free warpage larger than ten model
            // diagonals is not deformation but an unsuppressed nullspace mode
            // (the convergence test alone cannot see it -- K*u=f holds along
            // the nullspace). Report divergence, not kilometres.
            real modelDiagMm = sqrt(LxW^2+LyBase^2+HzTot^2)*1000.;
            int sbRunaway = (abs(warpageUnclamped) > 10.*modelDiagMm) ? 1 : 0;
            if(sbClampedConverged == 1 && sbFreeConverged == 1 && sbRunaway == 0){{
                cout << "  [SPRINGBACK] Warpage clamped  = " << warpageClamped << " mm" << endl;
                cout << "  [SPRINGBACK] Warpage free     = " << warpageUnclamped << " mm" << endl;
                cout << "  [SPRINGBACK] Springback delta = "
                     << (warpageUnclamped - warpageClamped) << " mm" << endl;
            }} else {{
                cout << "  [SPRINGBACK] NOT REPORTED - equilibrium did not converge "
                     << "(clamped converged=" << sbClampedConverged
                     << ", free converged=" << sbFreeConverged
                     << ", rigid runaway=" << sbRunaway << ")." << endl;
                cout << "  [SPRINGBACK] A delta computed from an unconverged re-solve is "
                     << "iteration error, not springback. Lower the fixture stiffness "
                     << "ratio or raise mech_max_newton_iter." << endl;
            }}
            clampActive = 1.0;    // restore for any later re-use
            // The unclamped re-solve overwrote newtonDone and the displacement
            // and stress fields. Restore the verdict and the frozen clamped
            // numbers, so the reported build state is the clamped one and not
            // the springback configuration.
            FinalSolidConverged = sbSavedConverged;
            residFrozen = residSaved; dresFrozen = dresSaved; itsFrozen = itsSaved;
            warpageClampedFinal = warpageClamped;
            dispMaxClampedFinal = dispMaxClamped;
            sigMMaxClampedFinal = sigMMaxClamped;
        }}
"""


