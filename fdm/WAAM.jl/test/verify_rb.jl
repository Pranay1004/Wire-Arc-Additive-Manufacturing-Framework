using Test, WAAMFlow, Statistics

# ===========================================================================
# V14 — Rayleigh–Bénard convection onset
#
#     A fluid layer heated from below, cooled from above, with rigid (no-slip) top and
#     bottom. Below the critical Rayleigh number the conduction state is stable: a small
#     temperature perturbation decays. Above it, buoyancy beats diffusion and the
#     perturbation grows exponentially. The classical linear-stability result for
#     infinite rigid–rigid layers is
#
#         Ra_c = g β ΔT d³ / (ν κ) = 1707.762
#
#     and, crucially, it is independent of the Prandtl number (the marginal state is
#     stationary, so inertia drops out of the marginal condition). That independence is
#     what makes this a clean gating test: the only thing that can move Ra_c is the
#     buoyancy–pressure–diffusion coupling being wrong.
#
#     This test measures the onset in a FINITE box with rigid, adiabatic side walls.
#     Those side walls are not part of the classical result — the true critical Ra of a
#     laterally confined layer is higher, and converges to 1707.76 as the aspect ratio
#     Γ = W/d grows. The measured chain across this suite (same grid, same scheme) is
#
#         Γ = 4:   Ra_c ≈ 1858      Γ = 8:   Ra_c ≈ 1731      Γ = 16:  Ra_c ≈ 1702
#
#     i.e. −0.33 % from the analytic value at Γ = 16. Two other conventions verified
#     here and load-bearing for that accuracy:
#
#       * The momentum walls must use the classical MAC convention (`tangential = :wall`);
#         the frozen `:layer` convention moves the effective no-slip planes half a cell
#         inside and biases Ra_c by O((N/(N−1))⁴) — 27 % against the analytic value at
#         nz = 24 with this same geometry.
#       * The onset is located by the linear growth rate σ(Ra), which is linear in Ra
#         near the marginal point (slope ≈ 7.6e-5 s⁻¹/Ra at ν = κ = 0.01 for the Γ = 16
#         box). The test brackets Ra_c with decay below / growth above and checks
#         both bracketing and the rate magnitudes, rather than solving for the crossing.
#
#     The temperature field is advanced here by a small explicit upwind scheme written
#     for this test rather than through `step_fluid!`: the point of V14 is to verify the
#     momentum/pressure/buoyancy stack against a known threshold, and dragging in the
#     VOF, the arc source and the phase change would only obscure that. `Tsol = -1`,
#     `Tliq = -1e-3` puts every cell in the fully liquid branch so the mushy-zone Darcy
#     drag is identically zero and the buoyancy is pure Boussinesq.
# ===========================================================================

"""Constant-property Boussinesq fluid with `ν = κ = νκ`, `β = 1`."""
function rb_material(νκ::Real)
    Tv = [200.0, 3000.0]
    c = PropCurve(Tv, fill(1.0, 2))
    k = PropCurve(Tv, fill(float(νκ), 2))
    μ = PropCurve(Tv, fill(float(νκ), 2))
    # Tliq just below Ttop (= 0) so every cell is fully liquid, and the buoyancy
    # reference offset gβ(T − Tliq) is negligible while its gradient is gβΔT.
    Material(name = "RBRef", Tsol = -1.0, Tliq = -1e-3, Lf = 1.0,
             rho_s = 1.0, rho_l = 1.0, Cp_s = c, Cp_l = c,
             k_s = k, k_l = k, mu_l = μ, beta_T = 1.0)
end

"""
One explicit temperature step: 3-D diffusion (adiabatic side walls, Dirichlet top and
bottom imposed through ghost cells so the boundary is second-order) plus upwind advection
by the face velocities. Returns nothing; updates `T` in place.
"""
function rb_advance_T!(T, U, κ, dt, g, Tbot, Ttop)
    nx, nz = g.nx, g.nz
    dx = (g.xf[end] - g.xf[1]) / nx
    dz = (g.zf[end] - g.zf[1]) / nz
    Tn = copy(T)
    @inbounds for k in 1:nz, i in 1:nx
        t0 = Tn[i, 1, k]
        TL = i > 1 ? Tn[i - 1, 1, k] : t0          # adiabatic side walls
        TR = i < nx ? Tn[i + 1, 1, k] : t0
        below = k > 1 ? Tn[i, 1, k - 1] : 2Tbot - t0
        above = k < nz ? Tn[i, 1, k + 1] : 2Ttop - t0
        diff = κ * ((TL - 2t0 + TR) / dx^2 + (below - 2t0 + above) / dz^2)

        # upwind advective fluxes; wall-normal faces are no-slip so their flux vanishes
        wlo = U.w[i, 1, k]
        whi = U.w[i, 1, k + 1]
        Tlo = wlo > 0 ? below : t0
        Thi = whi > 0 ? t0 : above
        adv = -(whi * Thi - wlo * Tlo) / dz

        ulo = U.u[i, 1, k]
        uhi = U.u[i + 1, 1, k]
        Tulo = ulo > 0 ? TL : t0
        Tuhi = uhi > 0 ? t0 : TR
        adv -= (uhi * Tuhi - ulo * Tulo) / dx

        T[i, 1, k] = t0 + dt * (diff + adv)
    end
    T
end

"""
    rb_growth(Ra; νκ, nx, nz, W, nseed, nsteps, seed) -> σ

Linear growth rate of a single Fourier mode at Rayleigh number `Ra`. The base state is
conduction between `Tbot` and `Ttop`; with `g = β = d = 1` and `ν = κ = νκ` (as
`rb_material` builds them, `ρ = Cp = 1`) the Rayleigh number is `Ra = ΔT / νκ²`, so the
test sets `Tbot = Ra·νκ²` to realise a target `Ra`. The seed is
`sin(nseed·π·x/W)·sin(πz)`; `nseed` must match the horizontal wavenumber of the mode
whose onset is being measured (`nseed/W ≈ 3.117` for the marginal infinite-layer mode,
i.e. `nseed = 4` in a `W = 4` box or `nseed = 16` in a `W = 16` box).

The momentum walls use the classical MAC convention (`tangential = :wall`), so the
no-slip planes sit on the domain faces at z = 0 and z = 1. The default layer convention
would hold the adjacent face layers fixed half a cell inside, moving the effective walls
to z = Δz/2 and biasing the onset by O((N/(N−1))⁴) — at nz = 24 that is 27 % in Ra,
far outside anything this test would accept.

The rate is fitted to log(KE) over the last quarter of the run, after the projection
transient (which decays at ≈ κ·π²) has left the window; the second half is not clean
enough at very short runs and the last quarter was verified linear against the previous
quarter across the whole Γ-scan used to characterise this test.
"""
function rb_growth(Ra::Real; νκ::Real = 0.01, nx::Int = 48, nz::Int = 24, W::Real = 4.0,
                   nseed::Int = 4, nsteps::Int = 3000, seed::Real = 1e-6)
    mat = rb_material(νκ)
    g = CartesianGrid(collect(range(0.0, W; length = nx + 1)), [0.0, 1.0],
                      collect(range(0.0, 1.0; length = nz + 1)))
    m = metrics(g)
    ws = MomentumWorkspace(g)
    U = VectorField(g)
    F = fill(1.0, nx, 1, nz)
    κ = float(νκ)
    dx = W / nx
    dz = 1.0 / nz

    # With g = β = d = 1 and ν = κ = νκ (rb_material sets both μ and k to νκ, and
    # ρ = Cp = 1), the Rayleigh number is Ra = ΔT / (ν κ) = ΔT / νκ². The drop that
    # realises a target Ra is therefore ΔT = Ra·νκ², not Ra·νκ.
    Ttop = 0.0
    Tbot = Ra * νκ * νκ
    T = Array{Float64,3}(undef, nx, 1, nz)
    for k in 1:nz, i in 1:nx
        zc = (k - 0.5) * dz
        xc = (i - 0.5) * dx
        # exact discrete conduction state (linear profile, so the ghost-cell Laplacian
        # below reproduces it to round-off) plus a single Fourier mode
        T[i, 1, k] = Tbot + (Ttop - Tbot) * zc +
                     seed * sin(π * zc) * sin(nseed * π * xc / W)
    end

    dt = 0.2 * min(dx^2, dz^2) / max(νκ, 1e-12)
    ts = Float64[]
    kes = Float64[]
    for s in 1:nsteps
        step_momentum!(U, ws, F, T, mat, m, g, dt; gmag = 1.0, tol = 1e-12,
                       tangential = :wall)
        rb_advance_T!(T, U, κ, dt, g, Tbot, Ttop)
        if s > 50 && s % 10 == 0          # skip the initial projection transient
            push!(ts, s * dt)
            push!(kes, sum(abs2, U.u) + sum(abs2, U.v) + sum(abs2, U.w))
        end
    end

    # fit log(KE) over the last quarter, where the mode is purely linear
    q3 = 3 * length(ts) ÷ 4
    w = q3+1:length(ts)
    x = ts[w] .- ts[w[1]]
    y = log.(max.(kes[w], 1e-300))
    length(w) < 5 && return 0.0
    linreg(x, y)[1] / 2                 # KE ~ e^{2σt}
end

"""
    rb_thermal_decay(; νκ, nx, nz, W, nsteps) -> σ_T

Pure-diffusion decay rate of the temperature perturbation with buoyancy disabled
(`gmag = 0`, so the velocity stays exactly zero and `rb_advance_T!` becomes a plain
linear diffusion step). The seed `cos(πx/W)·sin(πz)` is the first mixed x-Neumann /
z-Dirichlet mode; its sampled discrete rate is −0.10491 s⁻¹ (the neat cell-centred
value −0.10485 sits 6e-5 relative away, well inside the budget). A sampled half-wave
`sine(πx/W)` seed is deliberately NOT used here: its x-average is 2/π, and the
x-constant mode ( κπ² ≈ 0.0987, slower ) would then dominate the asymptote and the
measured rate would read −0.0988 instead. This is a cheap calibration of the thermal
diffusion stencil and the ghost-cell Dirichlet convention, independent of momentum.
"""
function rb_thermal_decay(; νκ::Real = 0.01, nx::Int = 48, nz::Int = 24, W::Real = 4.0,
                          nsteps::Int = 3000, seed::Real = 1e-6)
    mat = rb_material(νκ)
    g = CartesianGrid(collect(range(0.0, W; length = nx + 1)), [0.0, 1.0],
                      collect(range(0.0, 1.0; length = nz + 1)))
    m = metrics(g)
    ws = MomentumWorkspace(g)
    U = VectorField(g)
    F = fill(1.0, nx, 1, nz)
    κ = float(νκ)
    dx = W / nx
    dz = 1.0 / nz
    Tbot = 0.0
    Ttop = 0.0
    T = Array{Float64,3}(undef, nx, 1, nz)
    for k in 1:nz, i in 1:nx
        zc = (k - 0.5) * dz
        xc = (i - 0.5) * dx
        T[i, 1, k] = seed * sin(π * zc) * cos(π * xc / W)
    end
    dt = 0.2 * min(dx^2, dz^2) / max(νκ, 1e-12)
    ts = Float64[]
    q2 = Float64[]
    for s in 1:nsteps
        step_momentum!(U, ws, F, T, mat, m, g, dt; gmag = 0.0, tol = 1e-12,
                       tangential = :wall)
        rb_advance_T!(T, U, κ, dt, g, Tbot, Ttop)
        if s > 50 && s % 10 == 0
            push!(ts, s * dt)
            q = 0.0
            for k in 1:nz, i in 1:nx
                q += T[i, 1, k]^2              # mean stays zero by symmetry
            end
            push!(q2, max(q, 1e-300))
        end
    end
    q3 = 3 * length(ts) ÷ 4
    w = q3+1:length(ts)
    x = ts[w] .- ts[w[1]]
    y = log.(q2[w])
    length(w) < 5 && return 0.0
    linreg(x, y)[1] / 2                 # Σθ² ~ e^{2σ_T t}
end

"Slope/intercept of a least-squares line, computed without Statistics' fitting helpers."
function linreg(x, y)
    n = length(x)
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((xi - mx)^2 for xi in x)
    sxy = sum((x[i] - mx) * (y[i] - my) for i in 1:n)
    (sxy / sxx, my - (sxy / sxx) * mx)
end

# ===========================================================================
# Assertions. The bracket magnitudes follow the measured linear law
#     σ(Ra) ≈ 7.6e-5 · (Ra − 1702)
# (Γ = 16, ν = κ = 0.01) with generous room for the coarser test grid
# (nx = 128 vs the characterisation runs at nx = 192) and platform variation.
# A regression that breaks the buoyancy–pressure–viscous coupling moves σ
# by factors of several and trips both the brackets and the magnitude bands;
# the frozen `:layer` wall convention (the original failure mode this test
# was written to catch) gives σ(1740) ≈ −3e-3, i.e. zero bracket growth and
# a magnitude trip on the growth side.
# ===========================================================================
@testset "V14 Rayleigh–Bénard onset" begin
    @info "V14: onset brackets — two ~3 min runs on a 128×24 grid, not run per-commit"
    lo = rb_growth(1660.0; nx = 128, nz = 24, W = 16.0, nseed = 16, nsteps = 10000)
    @info "V14: σ(Ra = 1660) = $lo  (expect ≈ −3e-3)"
    hi = rb_growth(1740.0; nx = 128, nz = 24, W = 16.0, nseed = 16, nsteps = 10000)
    @info "V14: σ(Ra = 1740) = $hi  (expect ≈ +3e-3)"
    @test -6e-3 < lo < -1.2e-3
    @test +8e-4 < hi < +6e-3

    σT = rb_thermal_decay()
    @info "V14: pure-thermal decay σ_T = $σT  (theory −0.10485)"
    @test -0.1075 < σT < -0.1022
end
