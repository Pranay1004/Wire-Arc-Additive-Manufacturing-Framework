"""
Single-track GMAW driver.

Runs a moving Gaussian arc over a cold substrate with the paper's P-GMAW parameters,
reporting bead geometry, thermal history and the energy audit.

This is the tier-1 validation case P2/P3 of the master plan.
"""

"""
    RunConfig

Everything a single-track case needs. Defaults follow the paper's Sec. 2.
"""
Base.@kwdef struct RunConfig
    material::String = "ER70S6"
    Lx::Float64 = 0.020          # m
    Ly::Float64 = 0.004          # m (half-symmetry width)
    Lz::Float64 = 0.008          # m
    h_fine::Float64 = 0.4e-3     # m
    h_coarse::Float64 = 1.6e-3   # m
    ny::Int = 10
    arc_power_W::Float64 = 1472.0
    # W carried by the Gaussian surface flux. `NaN` means "take the EnergySplit
    # surface share for `energy_mode`" — the paper-faithful default, since with
    # `energy_mode = :paper` (Mode A, MASTER_PLAN §3.3) the surface carries
    # η(1−η_d)·UI = 1104 W and the droplets the remaining 368 W. This conduction-only
    # track does NOT deposit the droplet source (that is tier-2, `droplet_sources!`),
    # so with the older Mode B default (:consistent) ER70S6 never melted at all —
    # the surface share alone (456 W) is below its melt threshold. A finite value
    # overrides the split explicitly (e.g. 1472.0 = the historical full-arc-power
    # convention).
    surface_power_W::Float64 = NaN
    travel_speed::Float64 = 0.0028333   # m/s  (0.17 m/min)
    track_length::Float64 = 0.008       # m
    substrate_T::Float64 = 298.0        # K
    energy_mode::Symbol = :paper
    verbose::Bool = true
end

"""
    SingleTrackResult

Outputs plus the audit numbers needed to judge the run.
"""
struct SingleTrackResult
    T::Array{Float64,3}
    width::Float64
    height::Float64
    penetration::Float64
    peak_T::Float64
    molten_fraction::Float64
    energy_in::Float64
    energy_residual::Float64
    steps::Int
    wall::Float64
    sim_time::Float64
    track_length::Float64
    ncell::Int
end

"""
    RunControl

Pause/stop switches for a running `run_track` loop, safe to flip from any thread
(the dashboard hangs on them). Construct once and share the instance:

- `paused::Ref{Bool}` — the loop parks (no physics done) until cleared;
- `stopped::Ref{Bool}` — the loop exits cleanly, returning the partial result.

A plain `run_track(cfg)` call takes the default, which is never paused and never
stopped, so the driver's behaviour is bit-for-bit the one the validation suite runs.
"""
mutable struct RunControl
    paused::Base.RefValue{Bool}
    stopped::Base.RefValue{Bool}
    RunControl() = new(Ref(false), Ref(false))
end

"""
    run_track(cfg; ctl, on_snapshot, snap_interval_s) -> SingleTrackResult

Integrate the thermal field along a single pass. Conduction + enthalpy phase change only —
the fluid stack (VOF/Marangoni) is layered on top in `simulate.jl`; this case exists to
validate the thermal and geometric kernel first, which is the tier-1 gate.

By default only the **surface share** of the arc is deposited (Mode A, 1104 W): the
droplet thermal/mass source belongs to the coupled tier-2 path (`droplet_sources!` in
`simulate.jl`). The deposited droplet share is reported, so the missing ~368 W is
visible rather than silently dropped.

**Streaming form** (used by the dashboard so that *one* step body is the single source
of truth for both the validated CLI run and the live view):

- `ctl::RunControl` — shared pause/stop switches; both default off;
- `on_snapshot` — a callable receiving a `NamedTuple` every `snap_interval_s`
  (default 33 ms ≈ 30 fps) with the live state: snapshot of field slices, bead
  geometry, audit and progress. `nothing` (the default) disables emission, and the
  stepper then behaves exactly as the plain call.

The physics below the control hooks is deliberately untouched: the plain
`run_track(cfg)` numbers in `validation_output/` are still produced by this body.
"""
function run_track(cfg::RunConfig = RunConfig();
                   ctl::RunControl = RunControl(),
                   on_snapshot = nothing,
                   snap_interval_s::Float64 = 0.033)
    mat = get_material(cfg.material)
    proc = ProcessParameters()

    xf = graded_axis(0.0, cfg.Lx, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
    zf = graded_axis(0.0, cfg.Lz, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
    yf = collect(range(0.0, cfg.Ly; length = cfg.ny))
    g = CartesianGrid(xf, yf, zf)
    m = metrics(g)
    ws = EnergyWorkspace(g)

    nx, ny, nz = g.nx, g.ny, g.nz
    T = fill(cfg.substrate_T, nx, ny, nz)
    Told = copy(T)
    z3 = zeros(nx, ny, nz)
    qb = zeros(nx, ny, nz); sb = zeros(nx, ny, nz); lb = zeros(nx, ny, nz)
    f1 = fill(1.0, nx, ny, nz)

    es = EnergySplit(proc, mat; mode = cfg.energy_mode)
    q_surface = isnan(cfg.surface_power_W) ? es.q_surface : cfg.surface_power_W
    ctrl = TimestepController()

    x_start = cfg.h_fine * 2
    x_torch = x_start
    t = 0.0
    steps = 0
    peak = cfg.substrate_T
    e_in = 0.0
    e_res = 0.0
    max_cg = 0
    t0 = time()
    last_snap = -Inf
    # declared before the snapshot closure so the closure binds the SAME function
    # local the loop writes (otherwise the name resolves as a global and dies).
    dt = 0.0

    emit_snap = regime -> begin
        isnothing(on_snapshot) && return nothing
        (time() - last_snap) >= snap_interval_s || return nothing
        bg = bead_geometry(T, mat, m, g)
        last_snap = time()
        on_snapshot((step = steps, t = t, dt = dt, xt_mm = x_torch * 1e3,
                     progress = clamp(((x_torch - x_start) / max(cfg.track_length, 1e-12)), 0.0, 1.0),
                     regime = String(regime),
                     peak = peak, melt = latent_heat_fraction(T, mat),
                     width_mm = bg.width * 1e3, height_mm = bg.height * 1e3,
                     pen_mm = bg.penetration * 1e3,
                     top = permutedims(T[:, :, 1]),              # (ny, nx) rows=y, cols=x
                     sec = permutedims(T[:, 1, :]),              # (nz, nx) rows=z, cols=x
                     x_mm = collect(0.5 .* (xf[1:end-1] .+ xf[2:end]) .* 1e3),
                     y_mm = collect(0.5 .* (yf[1:end-1] .+ yf[2:end]) .* 1e3),
                     z_mm = collect(0.5 .* (zf[1:end-1] .+ zf[2:end]) .* 1e3),
                     mesh = (nx = nx, ny = ny, nz = nz, ncells = nx * ny * nz),
                     e_in_J = e_in, e_res_J = e_res, max_cg = max_cg))
        nothing
    end

    while (x_torch - x_start) < cfg.track_length
        while ctl.paused[] && !ctl.stopped[]
            sleep(0.02)
        end
        ctl.stopped[] && break

        torch = (x_torch, yf[1])
        arc_flux!(qb, T, proc, mat, m, g, torch; q_surface_power = q_surface)
        arc_source!(sb, qb, T, mat, m, g; top_k = 1)
        surface_loss!(lb, T, proc, mat, m, g)

        dt_local, regime, info = timestep(T, f1, m, g, mat, nothing, proc;
                                          ctrl = ctrl, t = t, torch = torch, src_now = sb)
        dt = clamp(dt_local, 1e-9, 0.05)

        copyto!(Told, T)
        res, iters, pin = solve_energy!(ws, T, Told, mat, nothing, sb, z3, lb, m, g, dt)
        e_res += energy_residual(T, ws.hout, Told, mat, nothing, sb, z3, lb, m, g, dt) * dt
        e_in += (abs(arc_power_delivered(sb, m)) + abs(sum(lb .* m.vol))) * dt

        t += dt
        steps += 1
        peak = max(peak, maximum(T))
        max_cg = max(max_cg, iters)
        x_torch += cfg.travel_speed * dt

        if cfg.verbose && (steps % 500 == 1)
            @printf("    t=%6.3f s  dt=%8.2e  [%s]  Tmax=%6.0f K  Qarc=%6.1f W  res=%.2e\n",
                    t, dt, uppercase(string(regime)), maximum(T),
                    arc_power_delivered(sb, m), res)
        end
        isnothing(on_snapshot) || emit_snap(regime)
        x_torch > xf[end] - cfg.h_fine && break
    end
    wall = time() - t0

    bg = bead_geometry(T, mat, m, g)
    if cfg.verbose
        @printf("\n  %s single track — %d x %d x %d = %d cells\n",
                cfg.material, nx, ny, nz, length(T))
        @printf("  track deposited   : %.2f mm in %.3f s  (%d steps, %.1f s wall, %.0fx realtime)\n",
                (x_torch - x_start) * 1e3, t, steps, wall, t / max(wall, 1e-9))
        @printf("  peak temperature   : %.0f K\n", peak)
        @printf("  bead width         : %.2f mm\n", bg.width * 1e3)
        @printf("  bead height        : %.2f mm\n", bg.height * 1e3)
        @printf("  penetration depth  : %.3f mm\n", bg.penetration * 1e3)
        @printf("  molten fraction    : %.5f\n", latent_heat_fraction(T, mat))
        @printf("  energy in          : %.1f J\n", e_in)
        @printf("  energy residual    : %.3e J  (%.2e relative)\n", e_res, e_res / max(e_in, 1e-30))
        @printf("  max CG iterations  : %d\n", max_cg)
        @printf("  energy split       : surface %.0f W, droplets %.0f W (mode %s, closure %.1e)\n",
                es.q_surface, es.q_droplet, es.mode, es.closure)
        @printf("  surface flux power : %.0f W  (%s)\n", q_surface,
                isnan(cfg.surface_power_W) ? "EnergySplit :$(es.mode) surface share" :
                                            "explicit override")
    end

    SingleTrackResult(T, bg.width, bg.height, bg.penetration, peak,
                      latent_heat_fraction(T, mat), e_in, e_res, steps, wall, t,
                      x_torch - x_start, length(T))
end

