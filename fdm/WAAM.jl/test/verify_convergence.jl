using Test, WAAMFlow, Statistics

# ===========================================================================
# V21 — grid convergence (observed order)
#
#     The driver is the energy solver on a 1-D conduction problem with a manufactured
#     cosine source. With adiabatic walls the exact steady state is
#
#         T(x) = 300 + A cos(πx/L),    src(x) = k (π/L)² A cos(πx/L)
#
#     because the source exactly balances the conductive flux divergence. The source is
#     smooth and the boundary condition is compatible with the exact solution, so the
#     only error left at steady state is spatial: the cell-centred diffusion operator and
#     its harmonic face conductivities. Refining the mesh must show second-order
#     convergence; an observed order below 2 means the operator (or the linear solve it
#     feeds) is losing accuracy somewhere.
#
#     Marching with a large implicit time step and a constant source is deliberate: at
#     t → large the transient is gone, so the measured error is the steady-state
#     discretisation error and cannot be contaminated by backward-Euler time error.
#     `Richardson` here means the pair orders log(e_n/e_2n)/log 2; both must exceed 1.8.
# ===========================================================================

const _CONV_L = 0.01
const _CONV_A = 100.0
const _CONV_K = 30.0

function _conv_material()
    Tv = [200.0, 3000.0]
    c = PropCurve(Tv, fill(500.0, 2); require_positive = true)
    k = PropCurve(Tv, fill(_CONV_K, 2); require_positive = true)
    Material(name = "ConvRef", Tsol = 1700.0, Tliq = 1701.0, Lf = 272000.0,
             rho_s = 7800.0, rho_l = 7000.0, Cp_s = c, Cp_l = c, k_s = k, k_l = k,
             mu_l = PropCurve(Tv, fill(6.0e-3, 2); require_positive = true),
             beta_T = 1.0e-4, gamma = ConstantGamma(1.0))
end

function _conv_grid(nx::Int)
    CartesianGrid(collect(range(0.0, _CONV_L; length = nx + 1)),
                  collect(range(0.0, _CONV_L / 10; length = 3)),
                  collect(range(0.0, _CONV_L / 10; length = 3)))
end

_conv_exact(x) = 300.0 + _CONV_A * cos(π * x / _CONV_L)

function _conv_steady(nx::Int, mat)
    g = _conv_grid(nx)
    m = metrics(g)
    ws = EnergyWorkspace(g)
    T = zeros(nx, 2, 2)
    Told = similar(T)
    src = zeros(nx, 2, 2)
    @inbounds for k in 1:2, j in 1:2, i in 1:nx
        x = m.xc[i]
        T[i, j, k] = _conv_exact(x)
        src[i, j, k] = _CONV_K * (π / _CONV_L)^2 * _CONV_A * cos(π * x / _CONV_L)
    end
    # Backward Euler is unconditionally stable; 60 steps of 1 s reach the steady state
    # to machine precision (the slowest mode decays as exp(-λt), λ ≈ 0.76 s⁻¹).
    for _ in 1:60
        copyto!(Told, T)
        solve_energy!(ws, T, Told, mat, nothing, src, nothing, nothing, m, g, 1.0)
    end
    ex = [_conv_exact(m.xc[i]) for i in 1:nx]
    sqrt(mean((T[:, 1, 1] .- ex) .^ 2)) / _CONV_A
end

@testset "V21 grid convergence" begin
    mat = _conv_material()
    errs = [_conv_steady(n, mat) for n in (32, 64, 128)]
    @test all(diff(errs) .< 0)

    p1 = log(errs[1] / errs[2]) / log(2)
    p2 = log(errs[2] / errs[3]) / log(2)
    @test p1 > 1.8
    @test p2 > 1.8
end

# ===========================================================================
# V22 — time-step convergence (observed order)
#
#     Same conduction driver, now transient: T(x,0) = 300 + A cos(πx/L) decays as
#     exp(-α(π/L)²t) with α = k/(ρ cp). The grid is fixed at n = 32 so the spatial
#     error is common to every run; halving dt must show the order of the time
#     integrator. The energy solver is backward Euler (see `solve_energy!`), so the
#     observed order is 1 — Crank–Nicolson was deliberately rejected as A-unstable for
#     the phase-change front. The plan's >1.8 target therefore is NOT met by design;
#     this test measures the order honestly (0.9–1.2) instead of asserting a value the
#     scheme cannot deliver. Re-reaching >1.8 needs a 2nd-order A-stable integrator
#     (TR-BDF2/SDIRK), not a tolerance change.
#
#     The metric is self-convergence, E(dt) = ‖T_dt − T_{dt/2}‖, so the spatial error
#     cancels between the two runs and only the temporal component survives.
# ===========================================================================

function _conv_transient(nx::Int, dt::Real, mat; tend::Real = 1.0)
    g = _conv_grid(nx)
    m = metrics(g)
    ws = EnergyWorkspace(g)
    T = zeros(nx, 2, 2)
    Told = similar(T)
    @inbounds for k in 1:2, j in 1:2, i in 1:nx
        T[i, j, k] = _conv_exact(m.xc[i])
    end
    for _ in 1:round(Int, tend / dt)
        copyto!(Told, T)
        solve_energy!(ws, T, Told, mat, nothing, nothing, nothing, nothing, m, g, dt)
    end
    T[:, 1, 1]
end

@testset "V22 time-step convergence" begin
    mat = _conv_material()
    dts = (1.6e-2, 8.0e-3, 4.0e-3, 2.0e-3, 1.0e-3)
    sols = [_conv_transient(32, dt, mat) for dt in dts]
    errs = [sqrt(mean((sols[i] .- sols[i + 1]) .^ 2)) / _CONV_A for i in 1:length(dts) - 1]
    @test all(diff(errs) .< 0)

    orders = [log(errs[i] / errs[i + 1]) / log(2) for i in 1:length(errs) - 1]
    @test orders[end] > 0.9
    @test orders[end] < 1.2
end
