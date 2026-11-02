"""
Default parameter dictionary and solver setup mixin for EDPBuilder.
"""

from pathlib import Path


class EDPDefaultsMixin:
    """Provides parameter schema, defaults, and solver backend configuration."""

    _BOOL_KEYS = (
        "enable_j2_plasticity", "enable_mechanical", "enable_microstructure",
        "enable_radiation", "enable_boiling_cap", "mech_gravity",
        "dynamic_clamping", "springback_solve", "nlgeom", "multi_material",
        "mech_use_consistent_tangent", "restart_resume", "inherent_strain_fallback",
        "auto_source_sizing", "nz_dep_follows_layers",
    )

    # Keys the builder reads that are NOT in default_params() (drivers, GUI,
    # multi-material zones, alloy-composition overrides). Unknown-key warnings
    # must not fire on these.
    _EXTRA_KEYS = frozenset((
        "C", "Cr", "Mn", "Mo", "Ni", "Si",
        "H_build_target_mm", "deposit_material", "substrate_material",
        "layer_height_mm", "mpi_safe", "step_mesh", "step_mesh_size",
        "stl_file", "target_nodes", "toolpath_provided",
        "wire_diameter", "wire_diameter_mm",
        "wire_feed_speed", "wire_feed_speed_m_min",
        "zones", "zonea_layers", "zonea_material", "zoneb_material",
    ))

    @staticmethod
    def solver_setup(solver: str) -> tuple:
        """
        Map a requested solver to (freefem_load_statement, set() keyword).

        MUMPS is the only backend here that factors a 249k-DoF 3D elasticity
        system within 16 GB (6.7 GB peak; UMFPACK OOMs). In FreeFem 4.15 the
        plugin registers itself *as* `sparsesolver`, so `solver=MUMPS` inside
        set() is a compile error — we must `load "MUMPS"` and then ask for
        `sparsesolver`.
        """
        name = str(solver or "UMFPACK").strip()
        key = name.upper()
        if key == "MUMPS":
            return 'load "MUMPS"', "sparsesolver"
        if key == "SPARSESOLVER":
            return "", "sparsesolver"
        if key in ("UMFPACK", "CG", "GMRES"):
            return "", key
        return "", name

    @property
    def solver_kw(self) -> str:
        return self.solver_setup(self.p.get("solver", "UMFPACK"))[1]

    @property
    def solver_load(self) -> str:
        return self.solver_setup(self.p.get("solver", "UMFPACK"))[0]

    @staticmethod
    def default_params() -> dict:
        """Return the full default parameter dictionary."""
        return {
            # --- Geometry (Substrate 150x150x5mm, Build Height 150mm) ---
            "lx": 0.150,           # deposit/substrate length X [m]
            "ly_base": 0.150,      # substrate width Y [m]
            "hz_base": 0.005,      # substrate thickness Z [m]  (5 mm: thin-plate DED case)
            "ty_dep": 0.008,       # deposit width Y [m]
            "h_bead": 0.004,       # first layer height Z [m]
            "h_bead_first": 0.004, # first layer height Z [m]
            "remelt_ratio": 0.80,  # subsequent layer fusion / remelt ratio (e.g. 0.80 = 80%)
            "h_bead_subseq": 0.0032, # subsequent layer height Z [m] (0.80 * 4mm = 3.2mm)
            "n_layers": 26,        # number of layers
            "deposition_pattern": "bidirectional", # "bidirectional" (zigzag) or "unidirectional"
            "enable_ultrasonic": False, # ultrasonic physics evaluation flag

            # --- Process ---
            "I_weld": 200.0,       # welding current [A]
            "U_weld": 24.0,        # voltage [V]
            "eta_arc": 0.8,        # arc efficiency
            "v_scan": 10.0e-3,     # scan speed [m/s]
            "v_wire": 5.0,         # wire feed speed [m/min]
            "d_wire": 1.2e-3,      # wire diameter [m] (1.2 mm)
            "t_wait": 60.0,        # inter-pass cooling time [s] (used when
                                   # interpass_cooling_mode == "time")

            # --- Inter-pass cooling control ---
            # "time":  cool for a fixed t_wait (legacy default; the dwell is
            #           whatever the user guessed).
            # "target": cool until the peak temperature of the part falls to
            #           `interpass_target_temp_C`, then stop. This is the Ansys
            #           "Iterative Cooldown" idea: a fixed dwell gives
            #           uncontrolled heat accumulation, which is why published
            #           interpass temperatures for the same build span 596 C
            #           (intermittent) to 1329 C (continuous).
            "interpass_cooling_mode": "time",
            "interpass_target_temp_C": 400.0,
            # Iteration cap on target-mode cooling. It must be generous enough to
            # actually reach the target on a thin, hot build: a fixed small cap
            # just produces the uncontrolled accumulation target mode is meant to
            # prevent. 0 = derive the cap from the cooling time step and a
            # generous dwell budget instead of a hard-coded count.
            "interpass_max_iters": 0,         # 0 = auto
            "interpass_converge_pct": 0.1,   # % change in peak T that counts as converged
            "interpass_time_step": 10.0,     # [s] per cooling iteration
            "interpass_max_cool_s": 900.0,   # [s] budget for one inter-pass cooldown

            # --- Heat Source ---
            "heat_source": "goldak",   # goldak, gaussian_vol, gaussian_surf,
                                       # conical, uniform, prescribed
            "af": None,            # Goldak front length [m]; None -> auto-sized
            "auto_source_sizing": True,  # derive bG/cG/af/ar from ty_dep/h_bead/layer
            "source_fidelity_floor": 0.90,  # warn when the discrete injection
                                            # fidelity drops below this before
                                            # the exact rescale (0.90 = warn
                                            # beyond +/-10% of Pweld; raise to
                                            # 0.98 to warn at 2%)
            "nz_dep_min_per_layer": 0,  # >0: force this many cells per layer
            "nz_dep_follows_layers": True,  # False: let nz_dep be the TOTAL deposit cells
            "ar": None,            # Goldak rear length [m]; None -> auto-sized
            "bG": None,            # Goldak width [m]; None -> auto-sized from ty_dep
            "cG": None,            # Goldak depth [m]; None -> auto-sized from h_bead
            "eta_drop": 0.25,      # P48 literature droplet thermal fraction [-]
            "T_drop": 1627.0,      # Droplet superheat temperature [°C] (1900 K)
            "ff": 0.6,             # front fraction (ff+fr=2)
            "fr": 1.4,             # rear fraction
            "R_beam": 5.0e-3,      # Gaussian beam radius [m]
            "R_spot": 3.0e-3,      # Surface spot radius [m]
            "rt": 3.0e-3,          # Conical top radius [m]
            "rb": 1.0e-3,          # Conical bottom radius [m]
            "d_pen": 5.0e-3,       # Conical penetration depth [m]
            "a_band": 10.0e-3,     # Uniform half-length [m]
            "b_band": 5.0e-3,      # Uniform half-width [m]
            "c_band": 3.0e-3,      # Uniform half-depth [m]
            "R_activate": 10.0e-3, # Prescribed T activation radius [m]

            # --- Material ---
            "material": "SS308L",
            "material_base": "SS316L",
            "material_dep": "SS308L",
            "rho": 7850.0,
            "T_sol": 1450.0,
            "T_liq": 1520.0,
            "T_amb": 25.0,
            "latent_heat": 270000.0,
            "emissivity": 0.7,
            "h_conv": 15.0,
            "h_bot": 50.0,
            "nu": 0.3,
            "T_mech": 800.0,      # mechanical melting T for inherent strain

            # --- Default Mesh (Deposit Z: >= 1 element per layer for psi/Goldak) ---
            "nx_base": 25, "ny_base": 8, "nz_base": 2,
            "nx_dep": 25,  "ny_dep": 3,   "nz_dep": 26,
            "mesh_source": "parametric",  # parametric, cad_file, gmsh_file
            "mesh_file": "",

            # --- Solver ---
            "theta": 1.0,         # time integration (1.0=Backward Euler)
            "dt_weld": 0.333,     # welding timestep [s]
            "dt_wait": 10.0,      # inter-pass timestep [s]
            "dt_cool": 120.0,     # final cooling timestep [s]
            "n_cool_steps": 20,   # number of final cooling steps
            "solver": "MUMPS",  # MUMPS (249k DoF @ 6.7GB, works), UMFPACK (OOMs >100k DoF), CG
            # --- Adaptive time stepping ---
            # "fourier": limit the diffusion (Fourier) number per step so dt is
            #            chosen from the material diffusivity and the local
            #            element size. Fixes the accuracy of the thermal field
            #            independently of the user's dt guess.
            "adaptive_dt": "off",
            "adaptive_fo_target": 0.45,   # target diffusion number Fo = alpha*dt/dx^2
            "adaptive_dt_min": 1.0e-4,    # [s] floor
            "adaptive_dt_max": 5.0,       # [s] ceiling
            "src_travel_fraction": 8.0,  # dt cap: torch advance <= src_width/N per step

            # --- Structured output / history (Abaqus-equivalent) ---
            # Field output already goes to .vtu/.pvd. These control HISTORY
            # output: point and path probes sampled by the solver itself and
            # written to CSV with the true time, instead of the post-processor
            # guessing where to sample or scraping printed numbers.
            #
            # probe_points: [[x,y,z], ...] in metres. Sampled every step.
            # probe_paths:  [[x0,y0,z0, x1,y1,z1, ...], ...]
            #               Each entry is a polyline; sampled at `path_samples`
            #               evenly spaced arc-length stations.
            # probe_interval: write every N solver steps (1 = every step).
            "probe_points": [],
            "probe_paths": [],
            "probe_interval": 1,
            "path_samples": 40,

            # --- Restart / checkpoint ---
            # "off":    no checkpointing (default)
            # "layer":  checkpoint after each completed layer
            # "step":   checkpoint every `restart_every` solver steps
            # A checkpoint stores the full thermal + mechanical state plus the
            # loop counters, so a killed run resumes mid-deposition instead of
            # restarting from zero.
            "restart": "off",
            "restart_every": 25,
            "restart_resume": True,   # resume from the newest checkpoint if present

            # --- Physics Modules ---
            "enable_radiation": True,
            "k_liq_factor": 1.0,     # multiply k above liquidus (1.0=off; 2-5 = effective convective pool conductivity)
            "enable_mechanical": True,
            "enable_microstructure": True,
            # NOTE: "mechanical_model" / "chi_x" / "chi_y" / "chi_z" (anisotropic
            # inherent-strain) were previously declared but never read by the
            # emitted solve -- they only reached a header comment, so the GUI
            # exposed controls that did nothing. The solver now uses J2
            # thermo-elasto-plasticity, which supersedes the inherent-strain
            # shortcut. The keys are accepted and ignored for backwards
            # compatibility with older presets; set "inherent_strain_fallback"
            # below to re-enable the legacy chi_*-driven eigenstrain.
            "inherent_strain_fallback": False,
            "chi_x": 1.2,          # Legacy. Longitudinal inherent strain ratio (used only if fallback on)
            "chi_y": 0.4,          # Legacy. Transverse inherent strain ratio
            "chi_z": 0.0,          # Legacy. Through-thickness inherent strain ratio
            "mechanical_bc": "isostatic",  # isostatic, fixture_clamped, cantilever
            "enable_j2_plasticity": True,
            "thermal_correctors": 3,   # iterate properties/hrad to convergence (max passes)
            "thermal_corr_tol_C": 0.5,  # stop when max nodal change < this [C]
            "cp_spike_smooth_K": 2.0,   # latent-spike edge ramp half-width [K]
            "mechanics_order": 1,        # 1 = P1 tets, 2 = P2 (C3D10-like, warpage-grade)
            "mech_gravity": True,       # self-weight: required for melt-pool sag/blow-through
            "gravity_m_s2": 9.81,       # gravitational acceleration [m/s^2]
            "thermal_rect_debug": False,  # TEMPORARY rectifier diagnostic
            "mech_j2_debug": False,  # trace the J2 iteration (diagnostic only)
            "h_prime_iso": 1.5e9,          # Isotropic hardening modulus [Pa]
            "mech_j2_relax": 1.0,         # Picard damping on plastic increment (P2 needs ~0.5)
            "mech_dgamma_max": 1.0,        # trust-region cap on dGamma (1.0 = off; P2 needs ~0.005)
            "peeq_limit": 0.25,          # max equivalent plastic strain per node
            "mech_plastic_tol": 1.0e-3, # plastic increment vs accumulated peeq (relative)
            "max_plas_iter": 5,            # Max plasticity equilibrium iterations per step
            # TRIP (transformation-induced plasticity) volumetric expansion
            # coefficient for austenite -> martensite/bainite. Documented here
            # because it is read by the emitted mechanical stage; previously it
            # had no entry, so it could only ever be changed by hand.
            "trip_beta": 0.011,
            # Ultrasonic vibration assist (UVA-WAAM). Only the frequency was
            # plumbed through, and it softened the MODULUS (an elastic, not a
            # plastic, effect) while the amplitude -- which is what actually
            # drives the Blaha/de Wolff effect -- was never read at all. The
            # emitted stage now documents both and uses them on the yield
            # surface, not on E.
            "ultrasonic_frequency": 0.0,     # [Hz]; 0 = off
            "ultrasonic_amplitude": 15.0e-6, # [m] half-amplitude (Blaha effect is amplitude-driven)
            # --- UVA physics modules (all default OFF; enable_ultrasonic gates all) ---
            # Acoustic streaming: boosts effective thermal conductivity in the
            # molten pool (k_eff += k_stream when T >= T_liq). Models the
            # stirring effect of acoustic streaming on heat transfer.
            "ultrasonic_streaming": False,
            "ultrasonic_k_stream": 45.0,     # [W/m/K] streaming conductivity boost
            # Acoustic heat generation: volumetric dissipation of acoustic
            # energy as heat, localized to the deposit wall above the substrate.
            # Q_acou = eta_acou * 2 * alpha_atten * I_acou * exp(-alpha_atten * distZ)
            "ultrasonic_heat_gen": False,
            "ultrasonic_coupling_eff": 0.15, # [-] mechanical->thermal coupling efficiency
            "ultrasonic_attenuation": 0.12,  # [1/m] acoustic attenuation coefficient
            # Acoustic cavitation: when acoustic pressure exceeds the cavitation
            # threshold, void fraction reduces local density and enhances heat
            # generation. Models cavitation bubble collapse energy concentration.
            "ultrasonic_cavitation": False,
            "ultrasonic_cav_threshold": 1.0e6, # [Pa] cavitation threshold pressure
            # Acoustic momentum transfer: acoustic radiation pressure as a body
            # force in the molten pool. F_acou = 2 * alpha_atten * I_acou / c_sound
            "ultrasonic_momentum": False,
            "ultrasonic_c_sound": 5790.0,    # [m/s] longitudinal sound speed in steel
            # --- Incremental mechanics / nonlinear control ---
            # "interpass": solve once per layer (cheap, legacy default)
            # "layer_n":   solve every N weld steps within a layer
            # "weld":      solve at EVERY weld step (Abaqus-like, most accurate/slowest)
            "mech_solve_cadence": "interpass",
            "mech_solve_every_n_weld": 5,
            "mech_max_newton_iter": 150,    # Max global equilibrium (Picard/Newton) iterations
            # Convergence tolerances, expressed as RELATIVE changes. Defaults
            # chosen to be achievable by the Jacobi/Picard iteration used here
            # while still being tight enough for residual-stress work
            # (Abaqus' own defaults are 5e-3 force / 1e-5 displacement).
            "mech_newton_tol": 1.0e-4,     # max relative displacement change
            "mech_newton_tol_force": 1.0e-4,  # max relative out-of-balance force
            "mech_use_consistent_tangent": True,   # Consistent-tangent Newton (verified); False = legacy Picard
            "nlgeom": False,               # Updated Lagrangian geometric nonlinearity (movemesh)
            "dynamic_clamping": True,      # Clamp release after weld to capture springback
            "springback_solve": True,      # Unclamp and re-solve to report true springback
            # Released-state regularisation, as a FRACTION of the fixture
            # stiffness (see the aMech varf comment). The released system has
            # no Dirichlet conditions, so exactly zero is singular (measured:
            # 2.1e7 mm of nullspace reported as "warpage"); 1e-9 leaves modes
            # the Picard iteration cannot settle (free re-solve unconverged at
            # 150 iters on the 1-layer probe case). 1e-6 settles them while
            # restraining six orders below the fixture. Larger values would
            # start to hold the part themselves; see the _validate() guard.
            "springback_regularization": 1.0e-6,
            # Fixture spring stiffness as a MULTIPLE of the substrate's own
            # bending stiffness, k_bend = E*t^3/(12*(1-nu^2)) [N/m per unit width].
            #
            # The previous absolute default (1e4 N/m^3) was physically meaningless:
            # integrated over a 150 mm plate it gives ~225 N/m total, against a
            # substrate bending stiffness of order 1e6 N/m. The "isostatic"
            # fixture therefore restrained essentially nothing, which is why the
            # advertised springback always came out ~0. Calibrating to a multiple
            # of k_bend makes the fixture strength meaningful and mesh/material
            # independent, and keeps the condition number low enough for the
            # Picard iteration to converge (kz=1e13 absolute does NOT converge).
            #
            # k_fixture_z = fixture_stiffness_ratio_z * k_bend
            #
            # Calibrated empirically against the equilibrium solver: springback
            # scales monotonically with this ratio and every solve converges up
            # to 1e5, which is therefore the default. At 1e6 the fixture is so
            # stiff that the Picard iteration stops converging and the reported
            # springback becomes iteration error (verified: 4/4 converged at 1e5,
            # 2/4 at 1e6). Values above ~1e5 are flagged in _validate().
            "fixture_stiffness_ratio_z": 1.0e5,   # dimensionless
            "fixture_stiffness_ratio_xy": 1.0e5,  # dimensionless
            "k_spring_z": None,   # [N/m^3] override; None -> derived from ratio
            "k_spring_xy": None,  # [N/m^3] override; None -> derived from ratio
            "enable_boiling_cap": True,  # Cap T at Tboil (evaporation sink; prevents 5000+ C overheat)
            "enable_yield_truncation": False, # Obsolete post-hoc clipping, replaced by true Cauchy equilibrium

            # --- Output ---
            "output_dir": str((Path(__file__).resolve().parents[2] / "waam_output").resolve()) + "/",
            "save_every_n_weld": 8,   # ~10 frames/layer; 3 wrote 22 MB VTUs every 1 s of sim time (16+ GB/run)
            "save_every_n_cool": 5,

            # --- Multi-material ---
            # NOTE: "material_schedule" was declared here but never read by the
            # generator -- per-layer alloy switching is driven by material_base /
            # material_dep (zonal split by height) only. It is accepted and
            # ignored so older presets still load. Multi-material deposit
            # layering (per-layer alloy) is NOT yet implemented.
            "multi_material": False,
            "material_schedule": [],  # Legacy/unused. See note above.
        }

