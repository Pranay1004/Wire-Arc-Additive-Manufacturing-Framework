using Test, WAAMFlow, LinearAlgebra, Random, Statistics

@testset "V16 VOF volume conservation" begin
    Random.seed!(4242)
    for trial in 1:6
        n = 12
        g = uniform_grid(n, n, n, 1.0, 1.0, 1.0)
        m = metrics(g)
        U = VectorField(g)
        # a smooth divergence-free-ish velocity field (small amplitude keeps CFL sane
        # but the scheme should not care)
        fill!(U.u, 0.3); fill!(U.v, -0.2); fill!(U.w, 0.1)

        # a spherical blob so the surface is curved and non-trivial
        F = zeros(n, n, n)
        cx = cy = cz = 0.5
        r0 = 0.22
        for k in 1:n, j in 1:n, i in 1:n
            d = sqrt((m.xc[i] - cx)^2 + (m.yc[j] - cy)^2 + (m.zc[k] - cz)^2)
            F[i, j, k] = clamp(0.5 * (r0 - d) / (2 * m.dx[i]), 0, 1)
        end
        V0 = total_volume(F, m)

        dt = 0.05
        for _ in 1:40
            advect_vof!(F, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, dt)
        end
        V1 = total_volume(F, m)
        # Conservative scheme: the volume must be preserved to round-off, NOT merely
        # slowly. A drift here is the single most important VOF property.
        @test abs(V1 - V0) / V0 < 1e-12
    end
end

@testset "V17 VOF boundedness" begin
    Random.seed!(77)
    n = 14
    g = uniform_grid(n, n, n, 1.0, 1.0, 1.0)
    m = metrics(g)
    U = VectorField(g)
    fill!(U.u, 0.5); fill!(U.v, 0.5); fill!(U.w, 0.5)
    F = zeros(n, n, n)
    for k in 1:n, j in 1:n, i in 1:n
        d = sqrt((m.xc[i] - 0.5)^2 + (m.yc[j] - 0.5)^2 + (m.zc[k] - 0.5)^2)
        F[i, j, k] = clamp(0.5 * (0.25 - d) / (2 * m.dx[i]), 0, 1)
    end
    V0 = total_volume(F, m)
    # deliberately violent timesteps: the scheme must stay bounded regardless
    for dt in (0.01, 0.1, 0.5, 2.0, 10.0)
        Fc = copy(F)
        for _ in 1:5
            advect_vof!(Fc, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, dt)
            compress!(Fc, dt)
        end
        mn, mx = field_range(Fc)
        # Boundedness is the guarantee that matters for a volume fraction, and it must
        # hold at any timestep.
        @test mn >= 0.0
        @test mx <= 1.0
        # Compression is a REDISTRIBUTION, not a conservative operator: its weight is a
        # nonlinear function of F so the face differences do not telescope, and at an
        # absurd Courant number (dt = 10 with dx = 1/14) it can drive the fraction to the
        # bounds hard enough to grow the volume several-fold. What must hold
        # unconditionally is BOUNDEDNESS; the drift is documented, not asserted small.
        @test mn >= 0.0
        @test mx <= 1.0

        # ... whereas the advection sweep itself must be exactly conservative at any
        # timestep, including these deliberately violent ones. This is the property the
        # 3400 s case depends on, and it must be round-off, not "small".
        Fa = copy(F)
        for _ in 1:5
            advect_vof!(Fa, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, dt)
        end
        @test abs(total_volume(Fa, m) - V0) / V0 < 1e-12
        @test minimum(Fa) >= 0.0 && maximum(Fa) <= 1.0
    end
end

@testset "VOF transport is not frozen by saturated cells" begin
    # Regression for the global MULES limiter: a saturated cell (F = 1) with any
    # round-off-level inflow has raw = 1 + ε, and the old factor (1 - F)/(raw - F) is
    # then 0, which scales EVERY face flux in the domain to zero and freezes transport.
    # The pressure projection leaves exactly such O(1e-11) divergence every step, so a
    # translating droplet simply never moved. V16 misses it because its smoothed shell
    # never attains F = 1; here a sharp droplet does, and one face carries a 1e-12
    # perturbation standing in for that projection residue.
    n = 16
    g = uniform_grid(n, n, n, 1.0, 1.0, 1.0)
    m = metrics(g)
    F = zeros(n, n, n)
    for k in 1:n, j in 1:n, i in 1:n
        d = sqrt((m.xc[i] - 0.5)^2 + (m.yc[j] - 0.5)^2 + (m.zc[k] - 0.5)^2)
        F[i, j, k] = clamp((0.25 - d) / m.dx[i], 0, 1)
    end
    @test maximum(F) == 1.0
    zc0 = sum(F .* reshape(m.zc, 1, 1, :) .* m.vol) / total_volume(F, m)
    V0 = total_volume(F, m)

    U = VectorField(g)
    fill!(U.w, -0.1)
    U.w[8, 8, 12] += 1.0e-12   # a single O(round-off) divergence, like the projector's
    dt = 0.1
    nsteps = 20
    for _ in 1:nsteps
        advect_vof!(F, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, dt)
    end
    zc1 = sum(F .* reshape(m.zc, 1, 1, :) .* m.vol) / total_volume(F, m)
    # The droplet must actually translate (0.1 * 0.1 * 20 = 0.2), not sit still.
    @test (zc0 - zc1) > 0.15
    @test abs(total_volume(F, m) - V0) / V0 < 1e-12
    mn, mx = field_range(F)
    @test mn >= 0.0 && mx <= 1.0
end

@testset "VOF exact translation of a uniform slab" begin
    # A slab in a periodic-like box advected by a constant velocity must translate
    # exactly (upwind is exact for a piecewise-constant profile).
    n = 16
    g = uniform_grid(n, 1, 1, 1.0, 1.0, 1.0)
    m = metrics(g)
    U = VectorField(g)
    fill!(U.u, 0.1); fill!(U.v, 0.0); fill!(U.w, 0.0)
    F = zeros(n, 1, 1)
    for i in 1:n
        F[i, 1, 1] = (i >= 5 && i <= 9) ? 1.0 : 0.0
    end
    V0 = total_volume(F, m)
    # 1 cell per step (dt*u/dx = 1)
    for _ in 1:3
        advect_vof!(F, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, 10.0)
    end
    @test total_volume(F, m) ≈ V0 rtol = 1e-12
    lo = [Tuple(I)[1] for I in findall(x -> x > 0.5, F)]
    @test minimum(lo) == 8
    @test maximum(lo) == 12
end

@testset "VOF source term adds exactly the expected volume" begin
    n = 8
    g = uniform_grid(n, n, n, 1.0, 1.0, 1.0)
    m = metrics(g)
    U = VectorField(g)     # zero velocity
    F = zeros(n, n, n)
    dt = 0.1
    src = fill(1.0, n, n, n)          # 1/s volumetric generation everywhere
    for _ in 1:10
        advect_vof!(F, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g, dt; source = src)
    end
    expect = dt * 10 * sum(m.vol)
    @test total_volume(F, m) ≈ expect rtol = 1e-10
    @test all(x -> 0 <= x <= 1, F)
    # A saturated domain stops at exactly 1 (no overflow past the bound)
    @test field_range(F)[2] >= 1 - 1e-12
end

@testset "VOF divergence consistency" begin
    # The divergence used for the pressure coupling must be built from the SAME face
    # interpolation the advection uses, so that a uniform velocity field gives exactly
    # zero divergence of the interface flux.
    n = 10
    g = uniform_grid(n, n, n, 1.0, 1.0, 1.0)
    m = metrics(g)
    U = VectorField(g)
    fill!(U.u, 0.7); fill!(U.v, 0.0); fill!(U.w, 0.0)
    F = fill(0.5, n, n, n)
    d = zeros(n, n, n)
    vof_divergence!(d, F, U.u, U.v, U.w, m.ax, m.ay, m.az, m, g)
    @test maximum(abs, d) < 1e-12     # F constant => ∇·(F u) = F ∇·u = 0
end

@testset "interface_cells" begin
    n = 6
    F = zeros(n, n, n)
    F[3, 3, 3] = 1.0
    F[2, 3, 3] = 0.5
    B = interface_cells(F)
    @test B[2, 3, 3]      # the fractional cell is on the interface
    @test !B[3, 3, 3]     # a saturated interior cell is NOT
    @test !B[5, 5, 5]     # far field is not
    # ... but a saturated cell adjacent to a fractional one is captured by a wider band
    @test count(B) == 1
end
# ---------------------------------------------------------------------------
# V12 — Static droplet / Laplace pressure jump
# ---------------------------------------------------------------------------

"""
    laplace_droplet(n, R, L, sigma)

Build a smoothed spherical droplet of radius `R` on an `n^3` uniform grid over `[0,L]^3`,
with constant surface tension `sigma`. Returns the grid, metrics, volume fraction and the
analytic total curvature `2/R` for a sphere.
"""
function laplace_droplet(n::Int, R::Real, L::Real, sigma::Real)
    Tv = [200.0, 3000.0]
    c = PropCurve(Tv, fill(1000.0, 2); require_positive = true)
    k = PropCurve(Tv, fill(30.0, 2); require_positive = true)
    mu = PropCurve(Tv, fill(6.0e-3, 2); require_positive = true)
    mat = Material(name = "LaplaceRef", Tsol = 1700.0, Tliq = 1701.0, Lf = 272000.0,
                   rho_s = 1000.0, rho_l = 1000.0, Cp_s = c, Cp_l = c,
                   k_s = k, k_l = k, mu_l = mu, beta_T = 1e-4,
                   gamma = ConstantGamma(sigma))
    g = CartesianGrid(collect(range(0.0, L; length = n + 1)),
                      collect(range(0.0, L; length = n + 1)),
                      collect(range(0.0, L; length = n + 1)))
    m = metrics(g)
    cx = cy = cz = L / 2
    dx = L / n
    F = zeros(n, n, n)
    @inbounds for k in 1:n, j in 1:n, i in 1:n
        d = sqrt((m.xc[i] - cx)^2 + (m.yc[j] - cy)^2 + (m.zc[k] - cz)^2)
        F[i, j, k] = clamp((R + 2 * dx - d) / (4 * dx), 0.0, 1.0)
    end
    (mat = mat, g = g, m = m, F = F, sigma = sigma, R = Float64(R), k_expected = 2.0 / Float64(R))
end

@testset "V12 Static droplet / Laplace pressure jump" begin
    # A static droplet: the interface curvature must reproduce the Young-Laplace law
    # Δp = σ·κ with κ = 2/R for a sphere, and surface_tension_pressure! must compute
    # P_st = σ·κ exactly. A smeared/droplet with `kappa` far from 2/R means the surface
    # force (and hence the pressure jump) is wrong.
    n, R, L, sigma = 64, 0.15, 1.0, 1.0
    d = laplace_droplet(n, R, L, sigma)
    Fs = similar(d.F)
    smooth_fraction!(Fs, d.F, 2)
    kappa = zeros(n, n, n)
    curvature!(kappa, Fs, d.m, d.g)
    Pst = zeros(n, n, n)
    surface_tension_pressure!(Pst, kappa, fill(1700.0, n, n, n), d.mat)

    # Interface cells: smeared transition zone (0.1 < F < 0.9).
    idxs = findall(x -> 0.1 < x < 0.9, d.F)
    @test !isempty(idxs)
    ks = [abs(kappa[I]) for I in idxs]
    psts = [abs(Pst[I]) for I in idxs]
    k_mean = mean(ks)

    # Mean curvature at the interface must match the analytic sphere value 2/R within
    # the tolerance. This *is* the Laplace pressure jump Δp = σ·κ being correct.
    @test isapprox(k_mean / d.k_expected, 1.0; atol = 0.015)

    # P_st = σ·κ exactly (surface_tension_pressure! is a pointwise multiplication).
    for I in idxs
        @test Pst[I] ≈ d.sigma * kappa[I]
    end

    # Sign consistency: a liquid droplet (F high inside) has inward normal, so
    # κ = -∇·n̂ > 0 and P_st > 0 at the interface.
    @test all(kappa[I] > 0 for I in idxs)
    @test all(Pst[I] > 0 for I in idxs)

    # Mesh convergence: refining the grid must drive the curvature error down.
    d_coarse = laplace_droplet(32, R, L, sigma)
    Fs_c = similar(d_coarse.F)
    smooth_fraction!(Fs_c, d_coarse.F, 2)
    kappa_c = zeros(32, 32, 32)
    curvature!(kappa_c, Fs_c, d_coarse.m, d_coarse.g)
    idxs_c = findall(x -> 0.1 < x < 0.9, d_coarse.F)
    kc_mean = mean(abs.(kappa_c[I] for I in idxs_c))
    @test abs(k_mean / d.k_expected - 1.0) < abs(kc_mean / d.k_expected - 1.0)

    # Spurious currents: the plan's second V12 criterion is max‖u‖ < 1e-3 σ/√(ρR) at
    # steady state. Step the same droplet with CSF and measure. This is a KNOWN GAP, so
    # it is recorded as @test_broken: the Laplace jump is right (above), but the
    # face-centred CSF force is not a discrete gradient because the diffuse-band
    # curvature varies across the band (Pst ≈ 20 → 12 → 0), leaving a solenoidal
    # residual that accelerates the interface band. The measured current grows linearly
    # and is ~19× the bound after 200 steps (0.9× at step 10, where it is still just the
    # force impulse). A balanced face stencil and Pst smoothing only buy ~25 %. Meeting
    # the bound needs a κ that is constant along the interface normal (or a sharper
    # interface); with μ = 100 the steady state does reach 0.89×, but the physical
    # μ = 6e-3 case is transient-dominated and the criterion is not made honest by
    # choosing a viscous fluid. Remove @test_broken when the κ reconstruction is fixed.
    Tfield = fill(1800.0, n, n, n)
    U = VectorField(d.g)
    ws = MomentumWorkspace(d.g)
    for _ in 1:200
        step_momentum!(U, ws, d.F, Tfield, d.mat, d.m, d.g, 2.0e-4;
                       mode = CSF(), rho_amb = 1000.0, surf_tension_coeff = 1.0)
    end
    umax = max(maximum(abs, U.u), maximum(abs, U.v), maximum(abs, U.w))
    uref = 1.0e-3 * d.sigma / sqrt(1000.0 * d.R)
    @test_broken umax < uref
end
