"""
Coupled fluid driver: the operator-split step that advances momentum, volume fraction
and energy together.

The single-track driver (`single_track.jl`) is thermal-only, which is the right tier-1
gate but cannot produce a free surface. This module is the tier-2 gate: it wires the
three verified kernels — `step_momentum!` (V13), `advect_vof!` (V16/V17) and
`solve_energy!` (V11/V12) — into one step and holds every buffer so a 3400 s run does
not allocate per step.

The split is explicit and ordered:

1. **momentum** — predict `U` from the current `F` and `T`;
2. **VOF** — advect `F` with the new `U`, then compress;
3. **energy** — deposit the arc/droplet/loss sources and advance `T` with the new `U`.

Each sub-step reads the state written by the previous one, so the coupling is
first-order in time and the sub-steps can be verified independently before the whole is
trusted.
"""

"""
    FluidWorkspace{T}

Preallocated buffers for the coupled step: the energy workspace, the momentum workspace,
and the arc/droplet/loss source arrays.

Reusing these matters more than it looks — a 3400 s run is hundreds of thousands of
steps, and allocating the source arrays per step makes the garbage collector the
bottleneck rather than the physics.
"""
struct FluidWorkspace{T<:AbstractFloat}
    e::EnergyWorkspace{T}
    m::MomentumWorkspace{T}
    qsurf::Array{T,3}
    src_arc::Array{T,3}
    src_drop::Array{T,3}
    src_loss::Array{T,3}
    smass::Array{T,3}
    smom::Array{T,3}
    sh::Array{T,3}
end

function FluidWorkspace(g::CartesianGrid)
    T = Float64
    nx, ny, nz = g.nx, g.ny, g.nz
    z3() = zeros(T, nx, ny, nz)
    FluidWorkspace{T}(EnergyWorkspace(g), MomentumWorkspace(g),
                      z3(), z3(), z3(), z3(), z3(), z3(), z3())
end

"""
    step_fluid!(fw, U, F, T, Told, mat, m, g, dt; ...) -> (U, F, T)

Advance the coupled fluid state by one step.

`p` supplies the process parameters, `torch = (x, y)` the arc position (both the arc
heat and the droplet source follow it), and `lid` an optional moving-wall condition for
the momentum projection (the cavity test uses it; a free-surface WAAM pool passes
`nothing`). `surface_tension` turns on the CSF body force.
"""
function step_fluid!(fw::FluidWorkspace{Tf}, U::VectorField{Tf}, F::Array{Tf,3},
                     T::Array{Tf,3}, Told::Array{Tf,3}, mat::Material,
                     m::GridMetrics, g::CartesianGrid, dt::Real;
                     p::ProcessParameters = ProcessParameters(),
                     torch = nothing,
                     lid = nothing,
                     mode::PressureMode = PartialVoid(),
                     p_amb::Real = 0.0, f_void::Real = 1e-3,
                     rho_amb::Real = 1000.0,
                     surface_tension::Bool = false,
                     do_compress::Bool = true) where {Tf<:AbstractFloat}
    # --- 1. momentum: predict U from the current F and T ---
    step_momentum!(U, fw.m, F, T, mat, m, g, dt; mode = mode, p_amb = p_amb,
                   f_void = f_void, rho_amb = rho_amb, lid = lid,
                   surf_tension_coeff = surface_tension ? 1.0 : 0.0)

    # --- 2. VOF: advect the free surface with the new U ---
    advect_vof!(F, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, dt)
    do_compress && compress!(F, dt)

    # --- 3. sources, then energy ---
    if torch !== nothing
        arc_flux!(fw.qsurf, T, p, mat, m, g, torch)
        arc_source!(fw.src_arc, fw.qsurf, T, mat, m, g; top_k = 1)
        droplet_sources!(fw.smass, fw.smom, fw.sh, p, mat, T, m, g, torch)
    else
        fill!(fw.src_arc, zero(Tf))
        fill!(fw.sh, zero(Tf))
    end
    surface_loss!(fw.src_loss, T, p, mat, m, g)

    solve_energy!(fw.e, T, Told, mat, U, fw.src_arc, fw.sh, fw.src_loss, m, g, dt)
    (U, F, T)
end

"""
    simulate_track(cfg::RunConfig = RunConfig(); nsteps::Int = 100, dt::Real = 1e-4, ...) -> NamedTuple

Run a multi-step coupled simulation (momentum + VOF + energy) of a moving WAAM arc.
"""
function simulate_track(cfg::RunConfig = RunConfig();
                        nsteps::Int = 100,
                        dt::Real = 1.0e-4,
                        surface_tension::Bool = true,
                        do_compress::Bool = true,
                        mode::PressureMode = PartialVoid())
    mat = get_material(cfg.material)
    proc = ProcessParameters()
    xf = graded_axis(0.0, cfg.Lx, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
    zf = graded_axis(0.0, cfg.Lz, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
    yf = collect(range(0.0, cfg.Ly; length = cfg.ny))
    g = CartesianGrid(xf, yf, zf)
    m = metrics(g)

    nx, ny, nz = g.nx, g.ny, g.nz
    fw = FluidWorkspace(g)
    U = VectorField(g)
    F = zeros(nx, ny, nz)
    # Bottom half is initial solid plate
    F[:, :, 1:max(1, nz ÷ 2)] .= 1.0
    T = fill(cfg.substrate_T, nx, ny, nz)
    Told = copy(T)

    x_start = cfg.h_fine * 2
    x_torch = x_start
    t = 0.0

    for step in 1:nsteps
        copyto!(Told, T)
        torch = (x_torch, yf[1])
        step_fluid!(fw, U, F, T, Told, mat, m, g, dt;
                    p = proc, torch = torch, mode = mode,
                    surface_tension = surface_tension,
                    do_compress = do_compress)
        t += dt
        x_torch += cfg.travel_speed * dt
        (x_torch - x_start) >= cfg.track_length && break
    end

    bg = bead_geometry(T, mat, m, g)
    (U = U, F = F, T = T, grid = g, metrics = m, time = t,
     peak_T = maximum(T), bead = bg)
end
