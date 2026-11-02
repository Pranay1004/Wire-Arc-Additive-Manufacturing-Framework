"""
Simulation staging, checkpoint restart, probe paths, and microstructure postprocessing.
"""

import math
from core.multimaterial.alloy_metallurgy import get_alloy_category, get_alloy_scheme


class EDPStagesMixin:
    """Handles checkpointing, restart state restoration, probe histories, and kinetics."""

    def _checkpoint_call_layer(self) -> str:
        """Emit the layer-boundary checkpoint (the authoritative resume point)."""
        if str(self.p.get("restart", "off")).lower() in ("off", "0", "false", "none", ""):
            return ""
        return """
    // Checkpoint at the layer boundary. This is the only point at which the state
    // is fully consistent (whole layer deposited + inter-pass cooled + mechanical
    // solve complete), so resuming from here is exact rather than approximate.
    saveCheckpoint(t, iL+1, frame, histCounter,
                   EarcJ, EintJ, ElossJ, EquietJ, EcapJ, newtonDone, EprescJ);
    cout << " [RESTART] Checkpoint written after layer " << iL+1
         << " (t=" << t << "s)" << endl;"""

    def _checkpoint_call(self, indent: int = 8) -> str:
        """Emit the intra-layer checkpoint call, or nothing when restart is off.

        saveCheckpoint() only exists when checkpointing is enabled, so referring
        to it in a disabled run is a compile error rather than a no-op.
        """
        if str(self.p.get("restart", "off")).lower() in ("off", "0", "false", "none", ""):
            return ""
        pad = " " * indent
        return f"""{pad}// Intra-layer checkpoint. The resume unit is a whole layer (the
{pad}// layer-boundary checkpoint is the authoritative, exactly-consistent one),
{pad}// so this only exists to bound the work lost if a run dies mid-layer.
{pad}if(histCounter % restartEvery == 0){{
{pad}    saveCheckpoint(t+tLocal, iL, frame, histCounter,
{pad}                   EarcJ, EintJ, ElossJ, EquietJ, EcapJ, newtonDone, EprescJ);
{pad}}}"""

    # ---------------------------------------------------------- restart
    def _restart_block(self) -> str:
        """Emit checkpoint save/restore for the full thermal + mechanical state.

        Abaqus-equivalent restart: a long WAAM build can be resumed from the last
        completed layer instead of restarting from scratch. The checkpoint stores
        every field that defines the state, plus the loop counters and energy
        accumulators, so the resumed run continues with identical physics.

        Writing and reading FE fields must happen in separate scopes so the
        ofstream is flushed before the ifstream opens -- FreeFEM does not flush
        eagerly and reading a still-open file fails.
        """
        p = self.p
        mode = str(p.get("restart", "off")).lower()
        resume = 1 if p.get("restart_resume", True) else 0
        every = max(1, int(p.get("restart_every", 25)))
        has_mech = bool(p.get("enable_mechanical", True))
        if mode in ("off", "0", "false", "none", ""):
            # The deposition loop references these globals unconditionally, so
            # they must exist even when checkpointing is disabled.
            return """
// --- Checkpoint / restart: DISABLED ---
string ckptFile = outdir + "checkpoint.bin";
int useRestart = 0;
int restartEvery = {every};
int doResume = 0;
int resumeOk = 0;
int resumeFromLayer = 0;
real ckptTime = 0.; int ckptFrame = 0; int ckptHist = 0;
real ckptEarc = 0.; real ckptEint = 0.; real ckptEloss = 0.;
real ckptEquiet = 0.; real ckptEcap = 0.; real ckptEpresc = 0.;
""".format(every=every)
        m_fields = ""
        m_load = ""
        m_tmp_decl = ""
        if has_mech:
            m_fields = ("\n        f << Emod[]; f << epsPx[]; f << epsPy[]; f << epsPz[];"
                        "\n        f << epsPxy[]; f << epsPxz[]; f << epsPyz[];"
                        "\n        f << peeq[]; f << fMartOld[]; f << fBainOld[];"
                        "\n        f << ux[]; f << uy[]; f << uz[];")
            # NOTE: Mh/Vh are order-selected, so resume buffers match the
            # run's order by construction; cross-order resume is refused by the
            # stored order tag (v3) instead of silently misaligning dofs.
            m_tmp_decl = ("\nMh rEmod, rEpsPx, rEpsPy, rEpsPz, rEpsPxy, rEpsPxz,"
                          "\n   rEpsPyz, rPeeq, rFM, rFB;\nVh [rUx, rUy, rUz];")
            m_load = ("\n        g >> rEmod[]; g >> rEpsPx[]; g >> rEpsPy[]; g >> rEpsPz[];"
                      "\n        g >> rEpsPxy[]; g >> rEpsPxz[]; g >> rEpsPyz[];"
                      "\n        g >> rPeeq[]; g >> rFM[]; g >> rFB[];"
                      "\n        g >> rUx[]; g >> rUy[]; g >> rUz[];"
                      "\n        Emod[] = rEmod[]; epsPx[] = rEpsPx[]; epsPy[] = rEpsPy[];"
                      "\n        epsPz[] = rEpsPz[]; epsPxy[] = rEpsPxy[];"
                      "\n        epsPxz[] = rEpsPxz[]; epsPyz[] = rEpsPyz[];"
                      "\n        peeq[] = rPeeq[]; fMartOld[] = rFM[]; fBainOld[] = rFB[];"
                      "\n        ux[] = rUx[]; uy[] = rUy[]; uz[] = rUz[];")

        return f"""
// --- Checkpoint / restart ---
// The binary header already carries the loop counters, so a single file is the
// whole checkpoint. (A text sidecar was tried first and removed: FreeFEM cannot
// reliably extract `string` tokens from a stream, and a mixed chained
// `>> s >> r >> s` aborts with "file not good in read array".)
string ckptFile = outdir + "checkpoint.bin";
int useRestart = 1;
int restartEvery = {every};
int doResume = {resume};
// Scalars populated by loadCheckpoint() (FreeFEM functions cannot return several
// values, so the loaded header is published through globals).
real ckptTime = 0.; int ckptFrame = 0; int ckptHist = 0; int resumeFromLayer = 0;
real ckptEarc = 0.; real ckptEint = 0.; real ckptEloss = 0.;
real ckptEquiet = 0.; real ckptEcap = 0.; real ckptEpresc = 0.;
{m_tmp_decl}

func int saveCheckpoint(real tSave, int layerDone, int frameSave, int histSave,
                       real eA, real eI, real eL, real eQ, real eC, int mechConv,
                       real eP){{
    // Format version 2: appends the prescribed-T imposed energy eP after the
    // field block. Version 1 files (no eP) still load, with EprescJ = 0.
    // Format version 3: appends the mechanics fespace order after eP. A P1
    // checkpoint resumed into a P2 run (or vice versa) would silently misalign
    // every mechanical dof, so the loader refuses it instead.
    // Format version 4: appends the enthalpy state Hfield[]/H0[] (the thermal
    // primary unknown); older files reconstruct H from the stored T.
    int[int] hdr = [4, layerDone, frameSave, histSave, 0, 0, 0, 0, 0, 0,
                     mechConv, Th.nv, int(HzTot*1.e6), Nlayers];
    hdr[4] = int(tSave*1000.);          // ms
    hdr[5] = int(eA); hdr[6] = int(eI); hdr[7] = int(eL);
    hdr[8] = int(eQ); hdr[9] = int(eC);
    {{
        ofstream f(ckptFile, binary);
        f << hdr;
        f << Temp[]; f << Temp0[]; f << Hfield[]; f << H0[];
        f << Tpeak[]; f << psiActive[];
        f << dTdt[]; f << TdotCool[]; f << dt85Track[]; f << tEnter800[];
        f << nReheat[];{m_fields}
        f << eP;
        f << mechOrderCur;
    }}
    return 1;
}}

// Returns 1 if a compatible checkpoint was loaded (fields restored).
func int loadCheckpoint(){{
    if(doResume == 0) return 0;
    // NOTE: constructing an ifstream on a missing file is FATAL in FreeFEM (it
    // aborts before .good() can be consulted), so existence must be tested
    // first with system("test -f ...") -- the same guard the toolpath reader uses.
    if(system("test -f '" + ckptFile + "'") != 0) return 0;
    int ok = 0;
    {{
        ifstream g(ckptFile, binary);
        if(g.good()){{
            int[int] hdr(14);
            g >> hdr;
            // Version + node-count guard: a checkpoint from a DIFFERENT MESH must
            // not be applied, since the dof ordering would be meaningless. The
            // layer count is deliberately NOT part of the guard -- a checkpoint
            // written by a shorter run is exactly the normal case when resuming a
            // longer build, and the saved "layer done" counter drives how much of
            // the deposition loop is skipped.
            if(hdr[0] >= 1 && hdr[0] <= 4 && hdr[11] == Th.nv){{
                g >> Temp[]; g >> Temp0[];
                if(hdr[0] >= 4){{
                    g >> Hfield[]; g >> H0[];
                }} else {{
                    // Pre-enthalpy checkpoints: reconstruct H from the stored T
                    // with the same exact H(T) the solver uses.
                    for(int iv=0; iv<Th.nv; iv++){{
                        Hfield[][iv] = Hcp(Temp[][iv], Th(iv).z);
                        H0[][iv]     = Hcp(Temp0[][iv], Th(iv).z);
                    }}
                }}
                g >> Tpeak[]; g >> psiActive[];
                g >> dTdt[]; g >> TdotCool[]; g >> dt85Track[]; g >> tEnter800[];
                g >> nReheat[];{m_load}
                real ePload = 0.;
                if(hdr[0] >= 2) g >> ePload;
                ckptEpresc = ePload;
                int ordLoad = 1;
                if(hdr[0] >= 3) g >> ordLoad;
                if(ordLoad != mechOrderCur){{
                    cout << " [RESTART] REFUSED: checkpoint mechanics order "
                         << ordLoad << " != run order " << mechOrderCur
                         << " (P1 vs P2 dofs do not align). Not resuming."
                         << endl;
                    return 0;
                }}
                // Publish the loop counters AND the energy-audit accumulators so
                // the caller can skip finished work and keep the energy balance
                // continuous across the restart. Without restoring these the
                // resumed run reports EarcJ counting only the post-restart
                // deposition, which makes the energy audit nonsense.
                resumeFromLayer = hdr[1];
                ckptFrame = hdr[2];
                ckptHist = hdr[3];
                ckptTime = real(hdr[4])/1000.;
                EprescJ = ckptEpresc;
                ckptEarc = real(hdr[5]);
                ckptEint = real(hdr[6]);
                ckptEloss = real(hdr[7]);
                ckptEquiet = real(hdr[8]);
                ckptEcap = real(hdr[9]);
                // srcMask is derived from psiActive, so it is recomputed rather
                // than stored; without this a resumed run would source from a
                // stale (zero) mask until the next activation update.
                {self._srcmask_step}
                // Re-prime the enthalpy linearization for the first step after
                // the restart: Hiter must equal the restored H, or the first
                // solve linearizes about a stale state.
                Hiter[] = Hfield[];
                for(int iv=0; iv<Th.nv; iv++){{
                    CpLin[][iv] = max(CpMat(Temp[][iv], Th(iv).z), 1.);
                    invCpLin[][iv] = 1./CpLin[][iv];
                }}
                ok = 1;
                bornMask = max(srcMask, bornFloor);
            }}
        }}
    }}
    return ok;
}}

int resumeOk = loadCheckpoint();
if(resumeOk == 1){{
    cout << " [RESTART] Resumed state from checkpoint: layer " << resumeFromLayer
         << ", t=" << ckptTime << " s, frame " << ckptFrame << endl;
}} else {{
    cout << " [RESTART] No compatible checkpoint found - starting from layer 0" << endl;
}}

"""

    def _probe_setup(self) -> str:
        """Emit probe-point and probe-path definitions plus the CSV writers.

        This is the Abaqus `*OUTPUT, HISTORY` equivalent. Previously the only
        history available was five hard-coded thermocouples at X=Y=75 mm that the
        post-processor sampled itself, with a guessed time axis. Here the SOLVER
        samples the fields it has actually computed and writes them, tagged with
        the true simulated time, so nothing downstream has to guess.

        Emitted:
          - probe_points.csv : t, phase, layer, point, x, y, z, Temp, Tpeak,
                               CoolingRate, Activation
          - probe_paths.csv  : t, phase, layer, path, station, s_arc, x, y, z,
                               Temp, Tpeak, CoolingRate
        The mechanical fields (PEEQ, vonMises) are appended by the mechanics stage
        when it exists, because those fields do not exist in a thermal-only run.
        """
        p = self.p
        pts = list(p.get("probe_points") or [])
        paths = list(p.get("probe_paths") or [])
        n_samples = max(2, int(p.get("path_samples", 40)))
        interval = max(1, int(p.get("probe_interval", 1)))

        if not pts and not paths:
            # Still emit a no-op writeHistory so the call sites in the thermal
            # loops always resolve: FreeFEM requires a function to be defined
            # before it is used, so omitting it is a compile error, not a no-op.
            return """
// (no probe points/paths requested - history output disabled)
int probeInterval = 1;
int nProbePts = 0;
int nProbePaths = 0;
int nPathSamples = 0;
int nPathStations = 0;
// Pst must exist even here: FreeFEM parses the WHOLE script, so the guarded
// `Pst[...]` references below still need the symbol. Probe POINTS alone used to
// take this early return and leave Pst undeclared -> "syntax error ... Pst" ->
// the run never compiled. In FreeFEM++, real[int] declares an array of reals indexed by integers.
real[int] Pst(4);
    Pst = [0.0, 0.0, 0.0, 0.0];

func int writeHistory(real tNow, int phaseCode, int layerNum, int stepCounter){
    return 0;
}
"""

        def fmt(v):
            return f"{float(v):.9g}"

        # --- Build the emitted arrays ---
        pt_lines = []
        for i, q in enumerate(pts):
            if len(q) < 3:
                continue
            pt_lines.append("    {:s}, {:s}, {:s}".format(fmt(q[0]), fmt(q[1]), fmt(q[2])))

        # Paths: resample each polyline at n_samples equal-arc-length stations.
        # All stations go into ONE flat array Pst[s*4+0..3] = (s_arc, x, y, z),
        # with path ip owning stations [ip*n_samples, (ip+1)*n_samples). This
        # keeps the runtime indexing trivial instead of needing per-path strides.
        station_rows = []
        n_paths = 0
        for path in paths:
            pts2 = [(float(path[k]), float(path[k + 1]), float(path[k + 2]))
                    for k in range(0, len(path) - 2, 3)]
            if len(pts2) < 2:
                continue
            seg = []
            total = 0.0
            for k in range(len(pts2) - 1):
                d = math.dist(pts2[k], pts2[k + 1])
                seg.append(d)
                total += d
            if total <= 0.0:
                continue
            for s in range(n_samples):
                target = total * s / float(n_samples - 1)
                acc = 0.0
                for k, d in enumerate(seg):
                    if acc + d >= target or k == len(seg) - 1:
                        frac = 0.0 if d <= 0 else (target - acc) / d
                        frac = min(max(frac, 0.0), 1.0)
                        x = pts2[k][0] + frac * (pts2[k + 1][0] - pts2[k][0])
                        y = pts2[k][1] + frac * (pts2[k + 1][1] - pts2[k][1])
                        z = pts2[k][2] + frac * (pts2[k + 1][2] - pts2[k][2])
                        station_rows.append("    {:s}, {:s}, {:s}, {:s}".format(
                            fmt(target), fmt(x), fmt(y), fmt(z)))
                        break
                    acc += d
            n_paths += 1

        # FreeFEM has no 2-D real arrays: `real[3,2]`, `real[len*4]` and
        # `real[len]` are all syntax errors. Probe coordinates therefore go into
        # flat real[int] arrays sized explicitly, indexed as 3*i+k / 4*slot+k.
        arr_pt = ""
        if pt_lines:
            arr_pt = "real[int] Ppt = [\n{}\n    ];".format(",\n".join(pt_lines))

        # Pst must ALWAYS be declared, even with no probe paths: the path
        # writer below is emitted unconditionally (FreeFEM needs the function to
        # exist at every call site) and indexes Pst. Leaving it undeclared made
        # every run WITHOUT --probe-path fail to COMPILE with
        # "syntax error ... Pst" -- i.e. probe points broke the whole solver.
        arr_st = "real[int] Pst(4);\n    Pst = [0.0, 0.0, 0.0, 0.0];"
        if station_rows:
            # FreeFEM array declaration for real floats is real[int] (real elements indexed by int).
            arr_st = ("real[int] Pst(%d);\n    Pst = [\n%s\n    ];"
                      % (4 * len(station_rows), ",\n".join(station_rows)))

        n_stations = len(station_rows)

        return f"""
// === HISTORY OUTPUT: PROBE POINTS AND PATHS ===
// Sampled by the solver from the fields it actually computed, tagged with the
// true simulated time. Replaces the previous approach of five hard-coded
// thermocouples sampled by the post-processor against a guessed time axis.
//
// CAVEAT worth knowing: a probe is interpolated from the FE solution, so a probe
// placed inside a coarse element reports an element average, not a material-point
// value. With nz_base=1 the whole substrate is a single element, so a probe
// at z=2 mm returns something between the z=0 and z=15 node temperatures. Place
// probes on nodes, or refine the mesh, for point-accurate thermocouple data.
int probeInterval = {interval};
int nProbePts = {len(pt_lines)};
int nProbePaths = {n_paths};
int nPathSamples = {n_samples};
int nPathStations = {n_stations};

{arr_pt}
{arr_st}

if(nProbePts > 0){{
    ofstream hPts(outdir+"probe_points.csv");
    hPts << "t_s,phase,layer,point,x_m,y_m,z_m,Temp_C,Tpeak_C,CoolingRate_C_per_s,Activation"
         << endl;
}}
if(nProbePaths > 0){{
    ofstream hPth(outdir+"probe_paths.csv");
    hPth << "t_s,phase,layer,path,station,s_arc_m,x_m,y_m,z_m,Temp_C,Tpeak_C,CoolingRate_C_per_s"
         << endl;
}}

// Append one history sample for the current state. FreeFEM has no string type,
// so phaseCode is an integer tag: 1 = welding, 2 = inter-pass, 3 = cooling.
// NOTE: FreeFEM functions must return a value (`func void` is a syntax error), so
// this returns the number of CSV rows written.
func int writeHistory(real tNow, int phaseCode, int layerNum, int stepCounter){{
    if(stepCounter % probeInterval != 0) return 0;
    string phaseStr = (phaseCode == 1) ? "WELDING" : ((phaseCode == 2) ? "INTERPASS" : "COOLING");
    int rows = 0;

    if(nProbePts > 0){{
        ofstream hp(outdir+"probe_points.csv", append);
        for(int i=0; i<nProbePts; i++){{
            real qx = min(max(Ppt[3*i+0], 0.), LxW);
            real qy = min(max(Ppt[3*i+1], 0.), LyBase);
            real qz = min(max(Ppt[3*i+2], 0.), HzTot);
            if(abs(qx-Ppt[3*i+0]) > 1.e-9 || abs(qy-Ppt[3*i+1]) > 1.e-9
               || abs(qz-Ppt[3*i+2]) > 1.e-9)
                cout << " [WARN] Probe " << i << " requested at ("
                     << Ppt[3*i+0]*1000. << "," << Ppt[3*i+1]*1000. << ","
                     << Ppt[3*i+2]*1000. << ") mm lies OUTSIDE the domain; "
                     << "clamped to (" << qx*1000. << "," << qy*1000. << ","
                     << qz*1000. << ") mm. The history column reports the "
                     << "LOCATION ACTUALLY SAMPLED, not the one requested."
                     << endl;
            hp << tNow << "," << phaseStr << "," << layerNum << "," << i << ","
               << qx << "," << qy << "," << qz << ","
               << Temp(qx,qy,qz) << "," << Tpeak(qx,qy,qz) << ","
               << dTdt(qx,qy,qz) << "," << psiActive(qx,qy,qz) << endl;
            rows++;
        }}
    }}

    if(nProbePaths > 0 && nPathStations > 0){{
        ofstream hf(outdir+"probe_paths.csv", append);
        for(int ip=0; ip<nProbePaths; ip++)
            for(int is=0; is<nPathSamples; is++){{
                int slot = ip*nPathSamples + is;
                if(slot < 0 || slot >= nPathStations) continue;
                real sT = Pst[4*slot+0];
                real qx = min(max(Pst[4*slot+1], 0.), LxW);
                real qy = min(max(Pst[4*slot+2], 0.), LyBase);
                real qz = min(max(Pst[4*slot+3], 0.), HzTot);
                if(abs(qx-Pst[4*slot+1]) > 1.e-9 || abs(qy-Pst[4*slot+2]) > 1.e-9
                   || abs(qz-Pst[4*slot+3]) > 1.e-9)
                    cout << " [WARN] Probe path " << ip << " station " << is
                         << " requested outside the domain; clamped to ("
                         << qx*1000. << "," << qy*1000. << "," << qz*1000.
                         << ") mm." << endl;
                hf << tNow << "," << phaseStr << "," << layerNum << "," << ip << ","
                   << is << "," << sT << "," << qx << "," << qy << "," << qz << ","
                   << Temp(qx,qy,qz) << "," << Tpeak(qx,qy,qz)
                   << "," << dTdt(qx,qy,qz) << endl;
                rows++;
            }}
    }}
    return rows;
}}
"""

    def _microstructure_stage(self) -> str:
        """Generate alloy-specific microstructure phase kinetics and discrete hardness indentation test."""
        p = self.p
        mat_base = p.get("material_base", p.get("substrate_material", "ER70S-6"))
        mat_dep = p.get("material_dep", p.get("deposit_material", p.get("material", "ER70S-6")))
        base_scheme = get_alloy_scheme(mat_base)
        dep_scheme = get_alloy_scheme(mat_dep)

        base_defs = base_scheme.get("base_default_phases", [85.0, 0.0, 0.0, 15.0])
        base_p1 = base_defs[0] / 100.0
        base_p2 = base_defs[1] / 100.0
        base_p3 = base_defs[2] / 100.0
        base_p4 = base_defs[3] / 100.0
        base_hv = base_scheme.get("base_hardness_HV", 145.0)

        dep_defs = dep_scheme.get("base_default_phases", [85.0, 0.0, 0.0, 15.0])
        dep_p1 = dep_defs[0] / 100.0
        dep_p2 = dep_defs[1] / 100.0
        dep_p3 = dep_defs[2] / 100.0
        dep_p4 = dep_defs[3] / 100.0
        dep_base_hv = dep_scheme.get("base_hardness_HV", 160.0)

        alloy_kinetics = self._get_alloy_kinetics_freefem_code(mat_dep)
        cat_dep = get_alloy_category(mat_dep)
        if cat_dep in ["Austenitic Stainless Steel", "Nickel Superalloy"]:
            sdas_code = "real sdasVal = 45.0 * (crEff)^(-0.33); SDAS[][iv] = sdasVal;"
        elif cat_dep == "Aluminium Alloy":
            sdas_code = "real sdasVal = 18.0 * (crEff)^(-0.30); SDAS[][iv] = sdasVal;"
        elif cat_dep == "Titanium Alloy":
            sdas_code = "real sdasVal = 12.0 * (crEff)^(-0.25); SDAS[][iv] = sdasVal;"
        else:
            sdas_code = "real sdasVal = 50.0 * (crEff)^(-0.33); SDAS[][iv] = sdasVal;"

        return f"""
// === MICROSTRUCTURE & HARDNESS STAGE ===
cout << " === MICROSTRUCTURE & HARDNESS STAGE ===" << endl;
cout << " Alloy Kinetic Model: {mat_dep} ({dep_scheme['family']})" << endl;

// Microstructure phase kinetics dispatch
SDAS = 0.; dt85 = 0.;
fFerrite = 0.; fBainite = 0.; fMartensite = 0.; fPearlite = 0.; HVmap = 0.;
for(int iv=0; iv<Th.nv; iv++){{
    real Tp = Tpeak[][iv];
    real zv = Th(iv).z;
    real crEff = max(TdotCool[][iv], 0.5);
    real dtC = (dt85Track[][iv] > 0.05) ? dt85Track[][iv] : ((800.0 - 500.0) / crEff);
    dt85[][iv] = dtC;

    if(Tp > TsolMat(zv) && psiActive[][iv] > 0.5){{
        {sdas_code}
        {alloy_kinetics}
    }} else {{
        SDAS[][iv] = 0.;
        if (zv <= HzBase + 1.e-6) {{
            fFerrite[][iv]    = {base_p1};
            fBainite[][iv]    = {base_p2};
            fMartensite[][iv] = {base_p3};
            fPearlite[][iv]   = {base_p4};
            HVmap[][iv]       = {base_hv};
        }} else {{
            fFerrite[][iv]    = {dep_p1};
            fBainite[][iv]    = {dep_p2};
            fMartensite[][iv] = {dep_p3};
            fPearlite[][iv]   = {dep_p4};
            HVmap[][iv]       = {dep_base_hv};
        }}
    }}
}}

cout << "  Predicted Vickers Hardness: " << HVmap[].min << " to " << HVmap[].max << " HV" << endl;



// === DISCRETE HARDNESS TEST INDENTATION LOCATIONS (CSV Output) ===
cout << " === EXTRACTING DISCRETE HARDNESS TEST LOCATIONS ACROSS LAYERS ===" << endl;
{{
    ofstream fH(outdir+"hardness_test_locations.csv");
    fH << "Indent_ID,Layer_Name,Region,X_mm,Y_mm,Z_mm,Vickers_HV,SDAS_um,Phase1_pct,Phase2_pct,Phase3_pct,Phase4_pct,Tpeak_C,CoolingRate_C_s,ReheatCycles" << endl;

    real xMid = LxW / 2.0;
    real yMid = LyBase / 2.0;
    int indId = 0;

    // 1. Substrate Base Indents (Proportional Depth Stations across HzBase)
    for(int is=0; is<3; is++){{
        real zTest = (is + 1.0) * HzBase / 4.0;
        indId++;
        real hvVal = HVmap(xMid, yMid, zTest);
        real sdasVal = SDAS(xMid, yMid, zTest);
        real p1 = fFerrite(xMid, yMid, zTest)*100.0;
        real p2 = fBainite(xMid, yMid, zTest)*100.0;
        real p3 = fMartensite(xMid, yMid, zTest)*100.0;
        real p4 = fPearlite(xMid, yMid, zTest)*100.0;
        real TpVal = Tpeak(xMid, yMid, zTest);
        real CrVal = TdotCool(xMid, yMid, zTest);
        real nrVal = nReheat(xMid, yMid, zTest);

        fH << indId << ",Substrate,BaseMetal,"
           << xMid*1000. << "," << yMid*1000. << "," << zTest*1000. << ","
           << hvVal << "," << sdasVal << "," << p1 << "," << p2 << "," << p3 << "," << p4 << ","
           << TpVal << "," << CrVal << "," << nrVal << endl;
    }}

    // 2. Fusion Boundary / HAZ Indent
    {{
        indId++;
        real zTest = HzBase;
        real hvVal = HVmap(xMid, yMid, zTest);
        real sdasVal = SDAS(xMid, yMid, zTest);
        real p1 = fFerrite(xMid, yMid, zTest)*100.0;
        real p2 = fBainite(xMid, yMid, zTest)*100.0;
        real p3 = fMartensite(xMid, yMid, zTest)*100.0;
        real p4 = fPearlite(xMid, yMid, zTest)*100.0;
        real TpVal = Tpeak(xMid, yMid, zTest);
        real CrVal = TdotCool(xMid, yMid, zTest);
        real nrVal = nReheat(xMid, yMid, zTest);

        fH << indId << ",Fusion_Line,HAZ,"
           << xMid*1000. << "," << yMid*1000. << "," << zTest*1000. << ","
           << hvVal << "," << sdasVal << "," << p1 << "," << p2 << "," << p3 << "," << p4 << ","
           << TpVal << "," << CrVal << "," << nrVal << endl;
    }}

    // 3. Layer-by-Layer Deposited Wall Indents (Layer 1 to Nlayers)
    for(int iL=0; iL<Nlayers; iL++){{
        indId++;
        real zTest = (iL == 0) ? (HzBase + hBead1/2.) : (HzBase + hBead1 + (iL-1)*hBeadSub + hBeadSub/2.);
        real hvVal = HVmap(xMid, yMid, zTest);
        real sdasVal = SDAS(xMid, yMid, zTest);
        real p1 = fFerrite(xMid, yMid, zTest)*100.0;
        real p2 = fBainite(xMid, yMid, zTest)*100.0;
        real p3 = fMartensite(xMid, yMid, zTest)*100.0;
        real p4 = fPearlite(xMid, yMid, zTest)*100.0;
        real TpVal = Tpeak(xMid, yMid, zTest);
        real CrVal = TdotCool(xMid, yMid, zTest);
        real nrVal = nReheat(xMid, yMid, zTest);

        fH << indId << ",Layer_" << (iL+1) << ",Deposit,"
           << xMid*1000. << "," << yMid*1000. << "," << zTest*1000. << ","
           << hvVal << "," << sdasVal << "," << p1 << "," << p2 << "," << p3 << "," << p4 << ","
           << TpVal << "," << CrVal << "," << nrVal << endl;
    }}
}}

// 4. Detailed 1D Vertical Hardness Line Profile across Z (for ParaView Plot Over Line)
{{
    ofstream fZ(outdir+"hardness_profile_z.csv");
    fZ << "Z_mm,X_mm,Y_mm,Vickers_HV,SDAS_um,Tpeak_C,CoolingRate_C_s" << endl;
    real xMid = LxW / 2.0;
    real yMid = LyBase / 2.0;
    int nZSamples = 100;
    for(int k=0; k<=nZSamples; k++){{
        real zP = (k * HzTot) / nZSamples;
        real hvP = HVmap(xMid, yMid, zP);
        real sdasP = SDAS(xMid, yMid, zP);
        real tpP = Tpeak(xMid, yMid, zP);
        real crP = TdotCool(xMid, yMid, zP);
        fZ << zP*1000. << "," << xMid*1000. << "," << yMid*1000. << ","
           << hvP << "," << sdasP << "," << tpP << "," << crP << endl;
    }}
}}

// 5. Automatic Native 2D Matplotlib Postprocessing Engine
system("python3 postprocess/plot_generator.py " + outdir + " 2>/dev/null || python3 WAAM-Framework/postprocess/plot_generator.py " + outdir + " 2>/dev/null || true");
"""
