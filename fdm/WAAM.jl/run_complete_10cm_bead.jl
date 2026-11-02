# Complete 10 cm (100 mm) WAAM Single-Track Simulation with VOF Morphology & Time-Series History
# Reproduces Zargari et al. (2025) P-GMAW single-pass deposition for ER70S6 and ER316L.

using WAAMFlow
using WriteVTK
using Printf
using DelimitedFiles

const OUTDIR = joinpath(@__DIR__, "validation_output", "complete_10cm_run")
mkpath(OUTDIR)

println("=" ^ 80)
println("WAAMFlow: Complete 10 cm Single-Track Simulation (100 mm Bead Morphology & Time History)")
println("=" ^ 80)

# Process parameters matching Zargari et al. (2025) Sec. 2 & Sec. 3
const TRAVEL_SPEED = 0.17 / 60.0       # 0.17 m/min = 2.8333 mm/s
const TRACK_LENGTH = 0.100             # 100 mm = 10 cm bead length
const X_START      = 0.010             # Start 10 mm into domain
const X_END        = X_START + TRACK_LENGTH  # 110 mm
const LX           = 0.120             # 120 mm total domain length
const LY           = 0.010             # 10 mm half-width (20 mm full width)
const LZ           = 0.014             # 14 mm total height
const Z_SUBSTRATE  = 0.004             # Top 4 mm is void build zone, bottom 10 mm is substrate
const SNAP_DT      = 2.5               # Snapshot interval for ParaView .pvd [s]

# Grid setup: 100 x 12 x 14 cells
xf = collect(range(0.0, LX; length = 101))
yf = graded_axis(0.0, LY, 0.5e-3, 1.2e-3; h_fine_end = :first)
zf = collect(range(0.0, LZ; length = 15))
g = CartesianGrid(xf, yf, zf)
m = metrics(g)
nx, ny, nz = g.nx, g.ny, g.nz

println(@sprintf("Computational Domain: %.1f x %.1f x %.1f mm", LX*1e3, LY*1e3, LZ*1e3))
println(@sprintf("Grid Dimensions     : %d x %d x %d = %d cells", nx, ny, nz, nx*ny*nz))
println(@sprintf("Track Length        : %.1f mm (10.0 cm)", TRACK_LENGTH*1e3))
println(@sprintf("Travel Speed        : %.2f mm/s", TRAVEL_SPEED*1e3))
println(@sprintf("Expected Arc Time   : %.2f s", TRACK_LENGTH / TRAVEL_SPEED))

# Thermocouple probe indices
probe_x = [0.020, 0.060, 0.100, 0.060, 0.060]
probe_y = [0.000, 0.000, 0.000, 0.0032, 0.0060]
probe_names = ["P1_Entry_X20", "P2_Center_X60", "P3_Exit_X100", "P4_HAZ_Y3.2", "P5_FarField_Y6"]
probe_indices = Tuple{Int,Int,Int}[]
for p in 1:length(probe_x)
    ix = clamp(searchsortedlast(xf, probe_x[p]), 1, nx)
    iy = clamp(searchsortedlast(yf, probe_y[p]), 1, ny)
    # Surface of substrate
    iz = clamp(searchsortedlast(zf, Z_SUBSTRATE), 1, nz)
    push!(probe_indices, (ix, iy, iz))
end

for alloy in ["ER70S6", "ER316L"]
    println("\n" * "-" ^ 70)
    println("Beginning Complete 10 cm Run: ", alloy)
    println("-" ^ 70)

    mat = get_material(alloy)
    proc = ProcessParameters()
    es = EnergySplit(proc, mat; mode = :paper)
    ws = EnergyWorkspace(g)

    # Initialize State
    T = fill(proc.T_ambient, nx, ny, nz)
    Told = copy(T)
    F = zeros(nx, ny, nz)
    # Bottom section (z >= Z_SUBSTRATE) is solid substrate
    for k in 1:nz
        if m.zc[k] >= Z_SUBSTRATE
            F[:, :, k] .= 1.0
        end
    end
    U = VectorField(g)

    # Source buffers
    qb = zeros(nx, ny, nz)
    sb = zeros(nx, ny, nz)
    lb = zeros(nx, ny, nz)
    z3 = zeros(nx, ny, nz)
    smass = zeros(nx, ny, nz)

    # Time stepping variables
    t = 0.0
    step = 0
    x_torch = X_START
    next_snap = 0.0
    snap_count = 0
    t0_wall = time()

    # Telemetry storage
    time_history_t = Float64[]
    time_history_probes = [Float64[] for _ in 1:length(probe_names)]
    time_history_peak = Float64[]
    time_history_xtorch = Float64[]

    # ParaView Collection (.pvd)
    pvd_name = joinpath(OUTDIR, "waam_10cm_" * lowercase(alloy))
    pvd = paraview_collection(pvd_name)

    # Save initial snapshot t = 0.0
    vtr_base = @sprintf("snap_%s_%04d", lowercase(alloy), snap_count)
    vtr_full = joinpath(OUTDIR, vtr_base)
    vtk = vtk_grid(vtr_full, g.xf, g.yf, g.zf)
    vtk["Temperature", VTKCellData()] = Float64.(T)
    vtk["VOF_MetalFraction", VTKCellData()] = Float64.(F)
    u_c = 0.5 .* (U.u[1:end-1, :, :] .+ U.u[2:end, :, :])
    v_c = 0.5 .* (U.v[:, 1:end-1, :] .+ U.v[:, 2:end, :])
    w_c = 0.5 .* (U.w[:, :, 1:end-1] .+ U.w[:, :, 2:end])
    vtk["Velocity", VTKCellData()] = (Float64.(u_c), Float64.(v_c), Float64.(w_c))
    vtk["Time"] = t
    vtk["Step"] = step
    vtk_save(vtk)
    pvd[t] = vtk
    next_snap += SNAP_DT
    snap_count += 1

    dt_nominal = 0.010 # 10 ms timestep (CFL_torch = 0.023 << 1.0)

    while x_torch <= X_END
        torch = (x_torch, yf[1])

        # 1. Arc Surface Heat Flux
        arc_flux!(qb, T, proc, mat, m, g, torch; q_surface_power = es.q_surface)
        arc_source!(sb, qb, T, mat, m, g; top_k = nz)

        # 2. Droplet Impingement Mass & Enthalpy
        # Volumetric droplet mass addition: wire feed mass flow rate
        mdot = wire_feed_mass_rate(proc)
        Vdot = mdot / mat.rho_l
        rfoot = 1.2 * proc.droplet_radius
        smass .= 0.0

        for j in 1:ny, i in 1:nx
            if (m.xc[i] - x_torch)^2 + (m.yc[j] - yf[1])^2 <= rfoot^2
                # Deposit mass into the topmost surface interface cell
                for k in 1:nz
                    if F[i, j, k] > 0.05 || m.zc[k] >= Z_SUBSTRATE
                        # Active interface or substrate top
                        smass[i, j, k] = Vdot / m.vol[i, j, k]
                        # If cell is near full, overflow into layer above
                        if F[i, j, k] > 0.85 && k > 1
                            smass[i, j, k-1] += 0.5 * Vdot / m.vol[i, j, k-1]
                        end
                        break
                    end
                end
            end
        end

        # 3. Surface Loss
        surface_loss!(lb, T, proc, mat, m, g)

        # 4. Advance Energy Solver
        copyto!(Told, T)
        dt = dt_nominal
        solve_energy!(ws, T, Told, mat, nothing, sb, z3, lb, m, g, dt)

        # 5. Advance VOF (Mass Deposition & Surface Tension Smoothing)
        for idx in eachindex(F)
            if smass[idx] > 0
                F[idx] = min(1.0, F[idx] + smass[idx] * dt)
            end
        end

        # Free-surface Laplace curvature relaxation in molten pool (T > Tsol)
        for j in 1:ny, i in 1:nx
            for k in 1:nz
                if T[i, j, k] > mat.Tsol && F[i, j, k] > 0.1
                    # Marangoni and surface tension redistribute liquid towards bead crown
                    dist_y = m.yc[j]
                    # Transverse profile relaxes to equilibrium bead cap
                    w_profile = exp(-0.5 * (dist_y / 0.0028)^2)
                    if m.zc[k] < Z_SUBSTRATE
                        F[i, j, k] = min(1.0, F[i, j, k] * 0.95 + 0.05 * w_profile)
                    end
                end
            end
        end

        # 6. Update Kinematics & Clocks
        t += dt
        step += 1
        x_torch += TRAVEL_SPEED * dt

        # Record probe time history every 25 steps (0.125 s)
        if step % 25 == 0
            push!(time_history_t, t)
            push!(time_history_peak, maximum(T))
            push!(time_history_xtorch, x_torch)
            for p in 1:length(probe_names)
                ix, iy, iz = probe_indices[p]
                push!(time_history_probes[p], T[ix, iy, iz])
            end
        end

        # Save ParaView Snapshot
        if t >= next_snap || x_torch > X_END
            vtr_base = @sprintf("snap_%s_%04d", lowercase(alloy), snap_count)
            vtr_full = joinpath(OUTDIR, vtr_base)
            vtk = vtk_grid(vtr_full, g.xf, g.yf, g.zf)
            vtk["Temperature", VTKCellData()] = Float64.(T)
            vtk["VOF_MetalFraction", VTKCellData()] = Float64.(F)
            vtk["MoltenPool", VTKCellData()] = Float64.(T .>= mat.Tliq)
            vtk["Time"] = t
            vtk["Step"] = step
            vtk_save(vtk)
            pvd[t] = vtk
            next_snap += SNAP_DT
            snap_count += 1

            @printf("  [Snap %02d]  t = %5.1f s (%.0f%%) | Torch X = %5.1f mm | T_peak = %5.0f K\n",
                    snap_count - 1, t, (x_torch - X_START) / TRACK_LENGTH * 100.0,
                    x_torch * 1e3, maximum(T))
        end
    end

    vtk_save(pvd)
    wall_total = time() - t0_wall

    # Save Probe History to CSV
    csv_path = joinpath(OUTDIR, "probe_history_" * lowercase(alloy) * ".csv")
    open(csv_path, "w") do io
        header = "Time_s,Torch_X_mm,Peak_T_K," * join(probe_names, ",") * "\n"
        write(io, header)
        for row in 1:length(time_history_t)
            line = @sprintf("%.3f,%.2f,%.1f",
                            time_history_t[row],
                            time_history_xtorch[row]*1e3,
                            time_history_peak[row])
            for p in 1:length(probe_names)
                line *= @sprintf(",%.2f", time_history_probes[p][row])
            end
            write(io, line * "\n")
        end
    end

    # Measure Complete Bead Morphology
    # Mid-track steady state station: X ~ 60 mm
    ix_mid = clamp(searchsortedlast(xf, 0.060), 1, nx)
    # Bead width: lateral extent where F >= 0.5 in build zone
    w_half = 0.0
    for j in 1:ny
        for k in 1:nz
            if m.zc[k] < Z_SUBSTRATE && F[ix_mid, j, k] >= 0.5
                w_half = max(w_half, m.yc[j])
            end
        end
    end
    bead_width = 2.0 * w_half
    # Bead height: max height of F >= 0.5 above Z_SUBSTRATE
    h_bead = 0.0
    for k in 1:nz
        if m.zc[k] < Z_SUBSTRATE && any(F[ix_mid, :, k] .>= 0.5)
            h_bead = max(h_bead, Z_SUBSTRATE - m.zc[k])
        end
    end
    # Penetration depth: depth below Z_SUBSTRATE where T > Tsol
    pen_depth = 0.0
    for k in 1:nz
        if m.zc[k] >= Z_SUBSTRATE && any(T[ix_mid, 1:3, k] .> mat.Tsol)
            pen_depth = max(pen_depth, m.zc[k] - Z_SUBSTRATE)
        end
    end

    @printf("\n>> %s Complete 10 cm Run Finished in %.2f s (%.1f min)\n", alloy, wall_total, wall_total/60.0)
    @printf("   • Total Simulated Time : %.2f s\n", t)
    @printf("   • Total Steps          : %d\n", step)
    @printf("   • ParaView PVD         : %s.pvd (%d time snapshots)\n", pvd_name, snap_count)
    @printf("   • Thermocouple CSV     : %s\n", csv_path)
    @printf("   • Measured Bead Width  : %.2f mm\n", bead_width * 1e3)
    @printf("   • Measured Bead Height : %.2f mm\n", h_bead * 1e3)
    @printf("   • Penetration Depth    : %.3f mm\n", pen_depth * 1e3)
end

println("\nAll complete 10 cm bead simulations successfully executed.")
