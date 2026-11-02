"""
Momentum equation, interface capture and free-surface pressure coupling.

Solves the paper's Eq. (2):

```
∂V/∂t + V·∇V = −∇p/ρ + (1/ρ)∇·(μ∇V) − k_d V + G_b + (ṁ_s/ρ)(V_s − V)
```

with the forcing terms that decide a WAAM melt pool:

| Term | Paper | Implementation |
| --- | --- | --- |
| Darcy mushy drag | (5) | `k_d = s_d f_s^2/((1−f_s)³+ε₀)` on the momentum diagonal |
| Boussinesq buoyancy | (15) | `G_b = −g β_T (T − T_liq)` |
| Marangoni stress | (14) | `μ ∂u_t/∂n = −(∂γ/∂T)∇_s T` as a face stress |
| Surface tension | — | `κ = −∇·n̂`, force `γ(T)κ ∇F`, and `P_st = γ(T)κ` |

## Staggered, not collocated

A **staggered MAC** layout is used rather than the collocated grid with Rhie–Chow the
original plan proposed. Rhie–Chow is a fix for checkerboarding in *single-phase* pressure
solves; here the checkerboard-prone cells are exactly the interface cells, so suppressing
it there fights the physics. MAC removes the problem structurally and puts fluxes on faces
where they belong.

## Pressure

- `PartialVoid` (default, paper-faithful): cells with `F < F_void` are removed from the
  pressure system and pinned to ambient; surface tension enters as the interface
  condition.
- `CSF`: a single global Poisson solve with `σ κ ∇F` as a body force.
"""
abstract type PressureMode end
struct PartialVoid <: PressureMode end
struct CSF <: PressureMode end

"""
    MomentumWorkspace

Preallocated buffers for `step_fluid!`. Reused every step; a 3400 s run performs
hundreds of thousands of steps and allocating per step makes the collector the bottleneck.
"""
struct MomentumWorkspace{T<:AbstractFloat}
    u0::Array{T,3}; v0::Array{T,3}; w0::Array{T,3}     # face-shaped snapshots
    uu::Array{T,3}; vv::Array{T,3}; ww::Array{T,3}     # face velocity candidates
    rhofx::Array{T,3}                                   # x-face density (nx+1, ny, nz)
    rhofy::Array{T,3}                                   # y-face density
    rhofz::Array{T,3}                                   # z-face density
    drag::Array{T,3}                                    # Darcy drag [1/s]
    buoy::Array{T,3}                                    # Boussinesq acceleration
    px::Array{T,3}; py::Array{T,3}; pz::Array{T,3}      # face pressure conductance
    p::Array{T,3}
    rhs::Array{T,3}
    divU::Array{T,3}
    kappa::Array{T,3}
    Pst::Array{T,3}
    fx::Array{T,3}; fy::Array{T,3}; fz::Array{T,3}      # CSF body force [Pa/m]
    fxf::Array{T,3}; fyf::Array{T,3}; fzf::Array{T,3}   # CSF face force [Pa/m]
    alpha::Array{T,3}
    fixed::BitArray{3}
    fixedvals::Array{T,3}
    Fs::Array{T,3}                                      # smoothed F, for curvature
    visc::Array{T,3}                                    # kinematic viscosity per cell
end

function MomentumWorkspace(g::CartesianGrid)
    T = Float64
    nx, ny, nz = g.nx, g.ny, g.nz
    z3() = zeros(T, nx, ny, nz)
    ux3() = zeros(T, nx + 1, ny, nz)
    vy3() = zeros(T, nx, ny + 1, nz)
    wz3() = zeros(T, nx, ny, nz + 1)
    # Positional construction, in FIELD ORDER. Getting this out of alignment is silent
    # and vicious: the inner constructor happily converts a cell-shaped array into a
    # face-shaped field, so the pressure solver then reads one element past the end of a
    # cell array on every boundary face instead of erroring.
    MomentumWorkspace{T}(
        ux3(), vy3(), wz3(),           # u0, v0, w0 (face-shaped snapshots)
        ux3(), vy3(), wz3(),           # uu, vv, ww (face-shaped candidates)
        ux3(), vy3(), wz3(),           # rhofx, rhofy, rhofz (face density)
        z3(),                          # drag
        z3(),                          # buoy
        ux3(), vy3(), wz3(),           # px, py, pz (face conductance)
        z3(), z3(), z3(), z3(), z3(),  # p, rhs, divU, kappa, Pst
        z3(), z3(), z3(),              # fx, fy, fz (CSF body force)
        ux3(), vy3(), wz3(),           # fxf, fyf, fzf (CSF face force)
        z3(),                          # alpha
        BitArray(undef, nx, ny, nz),   # fixed
        z3(),                          # fixedvals
        z3(),                          # Fs
        z3())                          # visc
end

# ---------------------------------------------------------------------------
# Interface geometry
# ---------------------------------------------------------------------------

"""
    gradF(F, m, g, i, j, k) -> (gx, gy, gz)

Central-difference gradient of the volume fraction, second-order in the interior with
one-sided closures at the boundaries and correct half-distances on a graded axis.
"""
@inline function gradF(F::AbstractArray{T,3}, m::GridMetrics, g::CartesianGrid, i, j, k) where {T}
    nx, ny, nz = g.nx, g.ny, g.nz
    gx = if i > 1 && i < nx
        (F[i + 1, j, k] - F[i - 1, j, k]) / (m.dxf[i] + m.dxf[i + 1])
    elseif i == 1
        (F[2, j, k] - F[1, j, k]) / m.dxf[2]
    else
        (F[nx, j, k] - F[nx - 1, j, k]) / m.dxf[nx]
    end
    gy = if j > 1 && j < ny
        (F[i, j + 1, k] - F[i, j - 1, k]) / (m.dyf[j] + m.dyf[j + 1])
    elseif j == 1
        (F[i, 2, k] - F[i, 1, k]) / m.dyf[2]
    else
        (F[i, ny, k] - F[i, ny - 1, k]) / m.dyf[ny]
    end
    gz = if k > 1 && k < nz
        (F[i, j, k + 1] - F[i, j, k - 1]) / (m.dzf[k] + m.dzf[k + 1])
    elseif k == 1
        (F[i, j, 2] - F[i, j, 1]) / m.dzf[2]
    else
        (F[i, j, nz] - F[i, j, nz - 1]) / m.dzf[nz]
    end
    (T(gx), T(gy), T(gz))
end

"""
    curvature!(kappa, Fs, m, g) -> kappa

Mean curvature `κ = −∇·n̂` with `n̂ = ∇F/|∇F|`, evaluated by second-order central
differences of the unit normal.

`Fs` must already be **smoothed**. Curvature is a second derivative of a field that is
only piecewise smooth, so differentiating the raw fraction yields a saw-toothed κ — and
since the paper's sagging criterion *is* the peak surface tension pressure `γκ`, feeding
it raw curvature manufactures precisely the signal the criterion is meant to detect.
"""
function curvature!(kappa::Array{T,3}, Fs::Array{T,3}, m::GridMetrics,
                    g::CartesianGrid) where {T<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
        gx, gy, gz = gradF(Fs, m, g, i, j, k)
        gm = sqrt(gx^2 + gy^2 + gz^2)
        if gm < 1e-10
            kappa[i, j, k] = zero(T)
            continue
        end
        dnx = dny = dnz = zero(T)
        if i > 1 && i < nx
            ap = gradF(Fs, m, g, i + 1, j, k); am = gradF(Fs, m, g, i - 1, j, k)
            npm = sqrt(ap[1]^2 + ap[2]^2 + ap[3]^2); nmm = sqrt(am[1]^2 + am[2]^2 + am[3]^2)
            npm < 1e-10 || (dnx = (ap[1] / npm - am[1] / nmm) / (m.dxf[i] + m.dxf[i + 1]))
        end
        if j > 1 && j < ny
            ap = gradF(Fs, m, g, i, j + 1, k); am = gradF(Fs, m, g, i, j - 1, k)
            npm = sqrt(ap[1]^2 + ap[2]^2 + ap[3]^2); nmm = sqrt(am[1]^2 + am[2]^2 + am[3]^2)
            npm < 1e-10 || (dny = (ap[2] / npm - am[2] / nmm) / (m.dyf[j] + m.dyf[j + 1]))
        end
        if k > 1 && k < nz
            ap = gradF(Fs, m, g, i, j, k + 1); am = gradF(Fs, m, g, i, j, k - 1)
            npm = sqrt(ap[1]^2 + ap[2]^2 + ap[3]^2); nmm = sqrt(am[1]^2 + am[2]^2 + am[3]^2)
            npm < 1e-10 || (dnz = (ap[3] / npm - am[3] / nmm) / (m.dzf[k] + m.dzf[k + 1]))
        end
        kk = -(dnx + dny + dnz)
        # Guard: a non-finite value can only arise where a neighbour's normal is
        # degenerate and the division is skipped, leaving an inconsistent stencil at a
        # domain boundary. Dropping it is correct (the curvature there is not
        # meaningful) and prevents one NaN from poisoning every downstream surface force
        # and the whole momentum solve.
        kappa[i, j, k] = isfinite(kk) ? kk : zero(T)
    end
    kappa
end

"""
    smooth_fraction!(Fs, F, passes)

Six-neighbour smoothing of the volume fraction, in place into `Fs`. Used before curvature.
"""
function smooth_fraction!(Fs::Array{T,3}, F::Array{T,3}, passes::Int = 2) where {T<:AbstractFloat}
    nx, ny, nz = size(F)
    copyto!(Fs, F)
    buf = similar(F)
    for _ in 1:passes
        @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
            s = Fs[i, j, k]; n = 1.0
            i > 1  && (s += Fs[i - 1, j, k]; n += 1)
            i < nx && (s += Fs[i + 1, j, k]; n += 1)
            j > 1  && (s += Fs[i, j - 1, k]; n += 1)
            j < ny && (s += Fs[i, j + 1, k]; n += 1)
            k > 1  && (s += Fs[i, j, k - 1]; n += 1)
            k < nz && (s += Fs[i, j, k + 1]; n += 1)
            buf[i, j, k] = s / n
        end
        copyto!(Fs, buf)
    end
    Fs
end

"""
    surface_tension_pressure!(Pst, kappa, T, mat, m, g)

`P_st = γ(T)·κ` at every cell — the paper's proposed wall-stability criterion. Sign is
kept (a positive `P_st` means a convex, high-pressure surface); the magnitude is what the
criterion thresholds on.
"""
function surface_tension_pressure!(Pst::Array{T,3}, kappa::Array{T,3},
                                   Tfld::Array{T,3}, mat::Material) where {T<:AbstractFloat}
    @inbounds for idx in eachindex(kappa)
        Pst[idx] = mat.gamma(Tfld[idx]) * kappa[idx]
    end
    Pst
end

"""
    csf_force!(fx, fy, fz, Pst, Fs, coeff, m, g) -> (fx, fy, fz)

Cell-centred CSF body force `f = coeff · P_st · ∇α` [Pa/m]. Uses the smoothed volume
fraction so the force is spread over the same band the curvature was measured on. The
force enters the velocity predictor (`viscous_candidate!`), which is what makes the
projection turn it into the Laplace pressure jump; adding it to the pressure RHS instead
is not equivalent.
"""
function csf_force!(fx::Array{T,3}, fy::Array{T,3}, fz::Array{T,3},
                    Pst::Array{T,3}, Fs::Array{T,3}, coeff::Real,
                    m::GridMetrics, g::CartesianGrid) where {T<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
        gx, gy, gz = gradF(Fs, m, g, i, j, k)
        f = coeff * Pst[i, j, k]
        fx[i, j, k] = f * gx
        fy[i, j, k] = f * gy
        fz[i, j, k] = f * gz
    end
    (fx, fy, fz)
end

"""
    csf_force_faces!(fxf, fyf, fzf, Pst, Fs, coeff, m, g) -> (fxf, fyf, fzf)

Face-centred CSF body force — the balanced-force form. On a face the force is
`coeff·⟨P_st⟩_f (α_R − α_L)/d_f`: the **same** face gradient of α and the same face
spacing the pressure projection uses, so the projection can cancel it. The cell-centred
`csf_force!` instead averages each cell's `P_st·∇α` onto the face, which is not a
discrete gradient; the residual accelerates the interface band and drives parasitic
currents that grow without bound in a static droplet (V12).

Boundary faces carry no force (the wall is not an interface).
"""
function csf_force_faces!(fxf::Array{T,3}, fyf::Array{T,3}, fzf::Array{T,3},
                          Pst::Array{T,3}, Fs::Array{T,3}, coeff::Real,
                          m::GridMetrics, g::CartesianGrid) where {T<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    fxf .= 0; fyf .= 0; fzf .= 0
    @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
        pf = 0.5 * (Pst[i - 1, j, k] + Pst[i, j, k])
        fxf[i, j, k] = coeff * pf * (Fs[i, j, k] - Fs[i - 1, j, k]) / m.dxf[i]
    end
    @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
        pf = 0.5 * (Pst[i, j - 1, k] + Pst[i, j, k])
        fyf[i, j, k] = coeff * pf * (Fs[i, j, k] - Fs[i, j - 1, k]) / m.dyf[j]
    end
    @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
        pf = 0.5 * (Pst[i, j, k - 1] + Pst[i, j, k])
        fzf[i, j, k] = coeff * pf * (Fs[i, j, k] - Fs[i, j, k - 1]) / m.dzf[k]
    end
    (fxf, fyf, fzf)
end

# ---------------------------------------------------------------------------
# Marangoni surface stress
# ---------------------------------------------------------------------------

"""
    marangoni_faces!(fx, fy, fz, F, T, mat, m, g, mu, alpha)

Tangential surface traction from `μ ∂u_t/∂n = −(∂γ/∂T)∇_s T` (paper Eq. 14).

Applied as a body force on the **interface cells**, computed face by face. The gradient
is taken along the surface (tangential to `∇F`), which is what makes the traction purely
tangential — a full `∇T` would inject a spurious normal component.

The sign of `∂γ/∂T` is the whole story: positive (ER70S6 with its 0.018 wt.% S) drives
flow *inward*, giving a deep narrow pool; negative (ER316L) drives flow *outward*, giving a
wide shallow pool that sags sooner.
"""
function marangoni_faces!(fx::Array{T,3}, fy::Array{T,3}, fz::Array{T,3},
                          F::Array{T,3}, Tfld::Array{T,3}, mat::Material,
                          m::GridMetrics, g::CartesianGrid) where {T<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    fx .= 0; fy .= 0; fz .= 0
    @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
        # only interface cells carry a surface
        (F[i, j, k] > 1e-6 && F[i, j, k] < 1 - 1e-6) || continue
        Tk = Tfld[i, j, k]
        dgamma = dgamma_dT(mat.gamma, Tk)
        dgamma == 0 && continue
        # surface normal from the volume fraction gradient
        gx, gy, gz = gradF(F, m, g, i, j, k)
        gm = sqrt(gx^2 + gy^2 + gz^2)
        gm < 1e-10 && continue
        nxv, nyv, nzv = gx / gm, gy / gm, gz / gm
        # tangential temperature gradient
        Tx = i < nx ? (Tfld[i + 1, j, k] - Tfld[i, j, k]) / m.dxf[i + 1] : 0.0
        Ty = j < ny ? (Tfld[i, j + 1, k] - Tfld[i, j, k]) / m.dyf[j + 1] : 0.0
        Tz = k < nz ? (Tfld[i, j, k + 1] - Tfld[i, j, k]) / m.dzf[k + 1] : 0.0
        # project out the normal component
        dotn = Tx * nxv + Ty * nyv + Tz * nzv
        Ttx, Tty, Ttz = Tx - dotn * nxv, Ty - dotn * nyv, Tz - dotn * nzv
        # traction = -(dgamma/dT) * grad_s T, applied as a force density
        fx[i, j, k] = -dgamma * Ttx
        fy[i, j, k] = -dgamma * Tty
        fz[i, j, k] = -dgamma * Ttz
    end
    (fx, fy, fz)
end

# ---------------------------------------------------------------------------
# Pressure–velocity coupling
# ---------------------------------------------------------------------------

# The no-slip tangential condition lives on the *interior* face layer adjacent to a
# wall (the staggered layout has no tangential velocity on the wall plane itself).
# Those faces are therefore also interior faces of wall-adjacent cells and appear in
# the divergence stencil. Holding them at the wall value is the no-slip condition, so
# the viscous predictor and the pressure projection must both leave them alone, and
# the Poisson operator must not route pressure through them (their flux is prescribed,
# not pressure-driven). Skipping them in all three places is what keeps the projection
# exactly divergence-free; re-applying the BC afterwards then becomes a no-op.
#
# These predicates must mirror `apply_velocity_bc!`'s guards exactly.
@inline is_u_wall(j, k, ny::Int, nz::Int) =
    (ny > 1 && (j == 1 || j == ny)) || (nz > 1 && (k == 1 || k == nz))
@inline is_v_wall(i, k, nx::Int, nz::Int) =
    (nx > 1 && (i == 1 || i == nx)) || (nz > 1 && (k == 1 || k == nz))
@inline is_w_wall(i, j, nx::Int, ny::Int) =
    (nx > 1 && (i == 1 || i == nx)) || (ny > 1 && (j == 1 || j == ny))

"""
    solve_pressure!(ws, U, F, T, mat, m, g, rho_amb, mode, dt) -> (residual, iters, ok)

Free-surface pressure solve.

`PartialVoid`: cells with `F < F_void` are Dirichlet at `rho_amb`; the liquid cells form
the Poisson system. The `∂F/∂t` source (the volume the interface gained) enters the
right-hand side, which is what makes the solve enforce the volume constraint on the liquid.

`CSF`: one global solve with the surface tension `γκ` included as a body force, so no
cell is pinned and the interface condition is emergent.

Returns `(residual, iterations, converged)`; the residual is in pressure units.
"""
function solve_pressure!(ws::MomentumWorkspace{Tf}, U::VectorField{Tf},
                         F::Array{Tf,3}, Tfld::Array{Tf,3}, mat::Material,
                         m::GridMetrics, g::CartesianGrid, dt::Real;
                         rho_amb::Real = 1000.0, mode::PressureMode = PartialVoid(),
                         p_amb::Real = 0.0, f_void::Real = 1e-3,
                         surf_tension_coeff::Real = 1.0,
                         tangential::Symbol = :layer,
                         tol::Real = 1e-9, maxiter::Integer = 3000) where {Tf<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    N = nx * ny * nz
    alpha = ws.alpha
    @inbounds for idx in eachindex(F)
        alpha[idx] = F[idx] >= 1 - f_void ? 1.0 : (F[idx] <= f_void ? 0.0 : F[idx])
    end

    # --- divergence of the face velocity ---
    divergence!(ws.divU, U.u, U.v, U.w, m, g)

    # --- face density from the local state: liquid above the melt range is rho_l ---
    @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
        ws.rhofx[i, j, k] = Tfld[i - 1, j, k] > mat.Tsol || Tfld[i, j, k] > mat.Tsol ?
                           mat.rho_l : mat.rho_s
    end
    @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
        ws.rhofy[i, j, k] = Tfld[i, j - 1, k] > mat.Tsol || Tfld[i, j, k] > mat.Tsol ?
                           mat.rho_l : mat.rho_s
    end
    @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
        ws.rhofz[i, j, k] = Tfld[i, j, k - 1] > mat.Tsol || Tfld[i, j, k] > mat.Tsol ?
                           mat.rho_l : mat.rho_s
    end

    # --- pressure conductances on faces: the face AREA ---
    # poisson7! assembles (1/V) Σ (a_f/d_f)(p_c − p_n), which is −∇²p when a_f = A_f.
    # The 1/ρ factor is folded into the RHS (constant-ρ form) and into the velocity
    # correction in project_velocity!. In the :layer wall convention the frozen wall-layer
    # faces keep a_f = 0 so the operator matches the projection exactly (those faces are
    # never corrected); in :wall (MAC) mode every interior face is a live dof.
    ax = ws.px; ay = ws.py; az = ws.pz
    ax .= 0; ay .= 0; az .= 0
    @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
        tangential === :layer && is_u_wall(j, k, ny, nz) && continue
        ax[i, j, k] = m.ax[i, j, k]
    end
    @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
        tangential === :layer && is_v_wall(i, k, nx, nz) && continue
        ay[i, j, k] = m.ay[i, j, k]
    end
    @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
        tangential === :layer && is_w_wall(i, j, nx, ny) && continue
        az[i, j, k] = m.az[i, j, k]
    end

    # --- right-hand side: −(ρ_c/dt) ∇·u* ---
    rhs = ws.rhs
    dtt = Tf(dt)
    @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
        rho_c = mat.rho_s > 0 ? (Tfld[i, j, k] > mat.Tsol ? mat.rho_l : mat.rho_s) :
                               mat.rho_l
        rhs[i, j, k] = -(rho_c / dtt) * ws.divU[i, j, k]
    end


    # --- Dirichlet mask ---
    fixed = ws.fixed
    fill!(fixed, false)
    @inbounds for idx in eachindex(F)
        if mode isa PartialVoid
            fixed[idx] = alpha[idx] < 1.0
        else
            # CSF: pin the far field only, so the system is not singular
            fixed[idx] = F[idx] <= f_void
        end
    end
    if mode isa PartialVoid && !all(fixed) && !any(fixed)
        fixed[1] = true      # keep the system non-singular
    end
    # A cell whose six faces all have zero conductance (a corner wedged between wall
    # layers) carries no pressure information: every one of its faces is held, so its
    # divergence is identically zero whatever p is. Its row would be all zeros —
    # pin it to ambient so the system stays non-singular. Poisson7! overwrites the RHS
    # on pinned rows, so no divergence information is lost.
    @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
        (ax[i, j, k] == 0 && ax[i + 1, j, k] == 0 &&
         ay[i, j, k] == 0 && ay[i, j + 1, k] == 0 &&
         az[i, j, k] == 0 && az[i, j, k + 1] == 0) || continue
        fixed[i, j, k] = true
    end
    fv = ws.fixedvals
    fill!(fv, Tf(p_amb))
    # Partial-void free-surface BC form: for the diffuse interface the pressure obeys
    # ∇p = σκ∇α, i.e. p = p_amb + σ⟨κ⟩·α across the band, so each fractional (0 < α < 1)
    # cell carries that Dirichlet value. Pure void (α = 0) stays at p_amb; the liquid
    # interior then recovers the full Laplace jump. ⟨κ⟩ is the interface-area-weighted
    # mean (|∇α|-weighted) — for a sphere it is the exact surface curvature; for a
    # deforming surface it is the ray-mean of κ across the band, which is what the
    # pressure integral of σκ∇α depends on. This is the boundary-condition counterpart
    # of the CSF body force used by the CSF mode.
    if mode isa PartialVoid && surf_tension_coeff != 0
        ksum = zero(Tf); wsum = zero(Tf)
        @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
            a = alpha[i, j, k]
            (a > 0 && a < 1) || continue
            gx, gy, gz = gradF(ws.Fs, m, g, i, j, k)
            gmag = sqrt(gx^2 + gy^2 + gz^2)
            ksum += ws.Pst[i, j, k] * gmag
            wsum += gmag
        end
        kbar = wsum > 0 ? ksum / wsum : zero(Tf)
        # The liquid side of the band (α ≥ ½) sits at the full jump; the void side
        # stays at p_amb. Pinning only the liquid side keeps the interior from losing
        # the part of the jump that the innermost fractional ring would otherwise
        # shave off.
        @inbounds for k in 1:nz, j in 1:ny, i in 1:nx
            a = alpha[i, j, k]
            (a >= 0.5 && a < 1) || continue
            fv[i, j, k] = Tf(p_amb) + Tf(surf_tension_coeff) * kbar
        end
    end
    fill!(ws.p, Tf(p_amb))

    res, iters, ok = poisson7!(vec(ws.p), vec(rhs), ax, ay, az, m.vol,
                              m.dx, m.dy, m.dz, vec(fixed), vec(fv);
                              tol = tol, maxiter = maxiter)
    (res, iters, ok)
end

"""
    project_velocity!(U, ws, p, F, m, g; mode)

Apply the pressure gradient to the face velocities:

```
u_f ← u_f − dt · (p_R − p_L) / (ρ_f · d_f)
```

and damp the velocity inside the mush by the Darcy drag. Face pressures are averaged from
the two cell centres, which is why a staggered layout needs no interpolator.
"""
function project_velocity!(U::VectorField{Tf}, ws::MomentumWorkspace{Tf},
                           dt::Real, drag::Array{Tf,3}, F::Array{Tf,3},
                           m::GridMetrics, g::CartesianGrid;
                           tangential::Symbol = :layer) where {Tf<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    dtt = Tf(dt)
    p = ws.p
    @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
        # :layer mode — wall-layer faces keep their prescribed (no-slip / lid) value
        tangential === :layer && is_u_wall(j, k, ny, nz) && continue
        a = F[i - 1, j, k]; b = F[i, j, k]
        aa = a >= 1 - 1e-3 ? 1.0 : (a <= 1e-3 ? 0.0 : a)
        bb = b >= 1 - 1e-3 ? 1.0 : (b <= 1e-3 ? 0.0 : b)
        # skip faces between two void cells: no fluid, nothing to project
        (aa <= 0 && bb <= 0) && continue
        pf = (aa * p[i - 1, j, k] + bb * p[i, j, k]) / (aa + bb)
        rho_f = ws.rhofx[i, j, k]
        kd = 0.5 * (drag[i - 1, j, k] + drag[i, j, k])
        U.u[i, j, k] -= dtt * (p[i, j, k] - p[i - 1, j, k]) / (rho_f * m.dxf[i])
        # implicit Darcy damping (unconditionally stable for any k_d)
        U.u[i, j, k] /= (1 + dtt * kd)
    end
    @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
        tangential === :layer && is_v_wall(i, k, nx, nz) && continue
        aa = F[i, j - 1, k] >= 1 - 1e-3 ? 1.0 : (F[i, j - 1, k] <= 1e-3 ? 0.0 : F[i, j - 1, k])
        bb = F[i, j, k] >= 1 - 1e-3 ? 1.0 : (F[i, j, k] <= 1e-3 ? 0.0 : F[i, j, k])
        (aa <= 0 && bb <= 0) && continue
        pf = (aa * p[i, j - 1, k] + bb * p[i, j, k]) / (aa + bb)
        rho_f = ws.rhofy[i, j, k]
        kd = 0.5 * (drag[i, j - 1, k] + drag[i, j, k])
        U.v[i, j, k] -= dtt * (p[i, j, k] - p[i, j - 1, k]) / (rho_f * m.dyf[j])
        U.v[i, j, k] /= (1 + dtt * kd)
    end
    @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
        tangential === :layer && is_w_wall(i, j, nx, ny) && continue
        aa = F[i, j, k - 1] >= 1 - 1e-3 ? 1.0 : (F[i, j, k - 1] <= 1e-3 ? 0.0 : F[i, j, k - 1])
        bb = F[i, j, k] >= 1 - 1e-3 ? 1.0 : (F[i, j, k] <= 1e-3 ? 0.0 : F[i, j, k])
        (aa <= 0 && bb <= 0) && continue
        pf = (aa * p[i, j, k - 1] + bb * p[i, j, k]) / (aa + bb)
        rho_f = ws.rhofz[i, j, k]
        kd = 0.5 * (drag[i, j, k - 1] + drag[i, j, k])
        U.w[i, j, k] -= dtt * (p[i, j, k] - p[i, j, k - 1]) / (rho_f * m.dzf[k])
        U.w[i, j, k] /= (1 + dtt * kd)
    end
    U
end

"""
    darcy_and_buoyancy!(drag, buoy, T, mat, m, g; sd, exponent, eps0, rho_amb)

Darcy mushy drag `k_d` (paper Eq. 5) and Boussinesq buoyancy (Eq. 15).

Buoyancy is referenced to the liquidus so that a fully liquid pool is neutrally
buoyant and only the *hotter* part of a partly solid pool rises — the paper's reference
point, and the physically right one.
"""
function darcy_and_buoyancy!(drag::Array{Tf,3}, buoy::Array{Tf,3},
                             Tfld::Array{Tf,3}, mat::Material;
                             sd::Real = 1e6, exponent::Int = 2,
                             eps0::Real = 1e-4, rho_amb::Real = 1000.0,
                             gmag::Real = 9.80665) where {Tf<:AbstractFloat}
    @inbounds for idx in eachindex(drag)
        T = Tfld[idx]
        fs = solid_fraction(mat, T)
        drag[idx] = Tf(darcy_drag(mat, fs, sd; exponent = exponent, eps0 = eps0))
        # g_b = -g * beta_T * (T - T_liq): upward is -z is down, so +z is up
        buoy[idx] = Tf(gmag * mat.beta_T * (T - mat.Tliq))
    end
    (drag, buoy)
end

"""
    viscous_candidate!(uu, vv, ww, U, muf, drag, buoy, mat, Tfld, m, g, dt, fx, fy, fz)

Explicit predictor for the face velocities: viscous diffusion, buoyancy, Marangoni and
surface tension, and the drag damping. Pressure projection follows.

Explicit diffusion is fine here because the timestep is CFL-limited by the flow anyway, so
the viscous number never becomes the restriction.
"""
function viscous_candidate!(U::VectorField{Tf}, ws::MomentumWorkspace{Tf},
                            dt::Real, drag, buoy, mat, Tfld,
                            m::GridMetrics, g::CartesianGrid,
                            fx = nothing, fy = nothing, fz = nothing;
                            face_force = nothing,
                            tangential::Symbol = :layer,
                            convection::Symbol = :central) where {Tf<:AbstractFloat}
    nx, ny, nz = g.nx, g.ny, g.nz
    dtt = Tf(dt)
    wm = tangential === :wall
    convection in (:central, :upwind) ||
        throw(ArgumentError("convection must be :central or :upwind"))
    @inbounds for idx in eachindex(drag)
        ws.visc[idx] = mat.rho_s > 0 ? viscous_rho(Tfld[idx], mat) : 0.0
    end
    copyto!(ws.u0, U.u); copyto!(ws.v0, U.v); copyto!(ws.w0, U.w)
    copyto!(ws.uu, U.u); copyto!(ws.vv, U.v); copyto!(ws.ww, U.w)

    # ---- u-faces (i in 2:nx): 3-D diffusion + convection, no buoyancy ----
    @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
        tangential === :layer && is_u_wall(j, k, ny, nz) && continue
        nu = 0.5 * (ws.visc[i - 1, j, k] + ws.visc[i, j, k])
        hL = m.dxf[i]; hR = m.dxf[i + 1]
        dif = 2 / (hL + hR) * ((U.u[i + 1, j, k] - U.u[i, j, k]) / hR -
                               (U.u[i, j, k] - U.u[i - 1, j, k]) / hL)
        if j > 1 && j < ny
            hD = m.dyc[j]; hU = m.dyc[j + 1]
            dif += 2 / (hD + hU) * ((U.u[i, j + 1, k] - U.u[i, j, k]) / hU -
                                    (U.u[i, j, k] - U.u[i, j - 1, k]) / hD)
        elseif j == 1 && wm && ny > 1
            hD = m.dyf[1]; hU = m.dyc[2]
            dif += 2 / (hD + hU) * ((U.u[i, 2, k] - U.u[i, 1, k]) / hU -
                                    2 * U.u[i, 1, k] / hD)
        elseif j == ny && wm && ny > 1
            hD = m.dyc[ny]; hU = m.dyf[ny]
            dif += 2 / (hD + hU) * (-2 * U.u[i, ny, k] / hU -
                                    (U.u[i, ny, k] - U.u[i, ny - 1, k]) / hD)
        end
        if k > 1 && k < nz
            hB = m.dzc[k]; hA = m.dzc[k + 1]
            dif += 2 / (hB + hA) * ((U.u[i, j, k + 1] - U.u[i, j, k]) / hA -
                                    (U.u[i, j, k] - U.u[i, j, k - 1]) / hB)
        elseif k == 1 && wm && nz > 1
            hB = m.dzf[1]; hA = m.dzc[2]
            dif += 2 / (hB + hA) * ((U.u[i, j, 2] - U.u[i, j, 1]) / hA -
                                    2 * U.u[i, j, 1] / hB)
        elseif k == nz && wm && nz > 1
            hB = m.dzc[nz]; hA = m.dzf[nz]
            dif += 2 / (hB + hA) * (-2 * U.u[i, j, nz] / hA -
                                    (U.u[i, j, nz] - U.u[i, j, nz - 1]) / hB)
        end
        vf = 0.25 * (U.v[i - 1, j, k] + U.v[i, j, k] +
                     U.v[i - 1, min(j + 1, ny + 1), k] + U.v[i, min(j + 1, ny + 1), k])
        wf = 0.25 * (U.w[i - 1, j, k] + U.w[i, j, k] +
                     U.w[i - 1, j, min(k + 1, nz + 1)] + U.w[i, j, min(k + 1, nz + 1)])
        if convection === :upwind
            conv = U.u[i, j, k] > 0 ?
                   U.u[i, j, k] * (U.u[i, j, k] - U.u[i - 1, j, k]) / hL :
                   U.u[i, j, k] * (U.u[i + 1, j, k] - U.u[i, j, k]) / hR
        else
            conv = U.u[i, j, k] * (U.u[i + 1, j, k] - U.u[i - 1, j, k]) / (hL + hR)
        end
        if j > 1 && j < ny
            if convection === :upwind
                if vf > 0
                    hh = m.dyc[j]
                    conv += vf * (U.u[i, j, k] - U.u[i, j - 1, k]) / hh
                else
                    hh = m.dyc[j + 1]
                    conv += vf * (U.u[i, j + 1, k] - U.u[i, j, k]) / hh
                end
            else
                conv += vf * (U.u[i, j + 1, k] - U.u[i, j - 1, k]) / (m.dyc[j] + m.dyc[j + 1])
            end
        elseif j == 1 && wm && ny > 1
            conv += vf * (U.u[i, 2, k] + U.u[i, 1, k]) / (m.dyf[1] + m.dyc[2])
        elseif j == ny && wm && ny > 1
            conv += vf * (-U.u[i, ny, k] - U.u[i, ny - 1, k]) / (m.dyc[ny] + m.dyf[ny])
        end
        if k > 1 && k < nz
            if convection === :upwind
                if wf > 0
                    hh = m.dzc[k]
                    conv += wf * (U.u[i, j, k] - U.u[i, j, k - 1]) / hh
                else
                    hh = m.dzc[k + 1]
                    conv += wf * (U.u[i, j, k + 1] - U.u[i, j, k]) / hh
                end
            else
                conv += wf * (U.u[i, j, k + 1] - U.u[i, j, k - 1]) / (m.dzc[k] + m.dzc[k + 1])
            end
        elseif k == 1 && wm && nz > 1
            conv += wf * (U.u[i, j, 2] + U.u[i, j, 1]) / (m.dzf[1] + m.dzc[2])
        elseif k == nz && wm && nz > 1
            conv += wf * (-U.u[i, j, nz] - U.u[i, j, nz - 1]) / (m.dzc[nz] + m.dzf[nz])
        end
        ws.uu[i, j, k] += dtt * (-conv + nu * dif)
        ws.uu[i, j, k] /= (1 + dtt * 0.5 * (drag[i - 1, j, k] + drag[i, j, k]))
    end

    # ---- v-faces (j in 2:ny): 3-D diffusion + convection, no buoyancy ----
    @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
        tangential === :layer && is_v_wall(i, k, nx, nz) && continue
        nv = 0.5 * (ws.visc[i, j - 1, k] + ws.visc[i, j, k])
        hD = m.dyf[j]; hU = m.dyf[j + 1]
        dif = 2 / (hD + hU) * ((U.v[i, j + 1, k] - U.v[i, j, k]) / hU -
                               (U.v[i, j, k] - U.v[i, j - 1, k]) / hD)
        if i > 1 && i < nx
            hL = m.dxc[i]; hR = m.dxc[i + 1]
            dif += 2 / (hL + hR) * ((U.v[i + 1, j, k] - U.v[i, j, k]) / hR -
                                    (U.v[i, j, k] - U.v[i - 1, j, k]) / hL)
        elseif i == 1 && wm && nx > 1
            hL = m.dxf[1]; hR = m.dxc[2]
            dif += 2 / (hL + hR) * ((U.v[2, j, k] - U.v[1, j, k]) / hR -
                                    2 * U.v[1, j, k] / hL)
        elseif i == nx && wm && nx > 1
            hL = m.dxc[nx]; hR = m.dxf[nx]
            dif += 2 / (hL + hR) * (-2 * U.v[nx, j, k] / hR -
                                    (U.v[nx, j, k] - U.v[nx - 1, j, k]) / hL)
        end
        if k > 1 && k < nz
            hB = m.dzc[k]; hA = m.dzc[k + 1]
            dif += 2 / (hB + hA) * ((U.v[i, j, k + 1] - U.v[i, j, k]) / hA -
                                    (U.v[i, j, k] - U.v[i, j, k - 1]) / hB)
        elseif k == 1 && wm && nz > 1
            hB = m.dzf[1]; hA = m.dzc[2]
            dif += 2 / (hB + hA) * ((U.v[i, j, 2] - U.v[i, j, 1]) / hA -
                                    2 * U.v[i, j, 1] / hB)
        elseif k == nz && wm && nz > 1
            hB = m.dzc[nz]; hA = m.dzf[nz]
            dif += 2 / (hB + hA) * (-2 * U.v[i, j, nz] / hA -
                                    (U.v[i, j, nz] - U.v[i, j, nz - 1]) / hB)
        end
        uf = 0.25 * (U.u[i, j - 1, k] + U.u[min(i + 1, nx + 1), j - 1, k] +
                     U.u[i, j, k] + U.u[min(i + 1, nx + 1), j, k])
        wf = 0.25 * (U.w[i, j - 1, k] + U.w[i, j, k] +
                     U.w[i, j - 1, min(k + 1, nz + 1)] + U.w[i, j, min(k + 1, nz + 1)])
        if i > 1 && i < nx
            if convection === :upwind
                if uf > 0
                    hh = m.dxc[i]
                    conv = uf * (U.v[i, j, k] - U.v[i - 1, j, k]) / hh
                else
                    hh = m.dxc[i + 1]
                    conv = uf * (U.v[i + 1, j, k] - U.v[i, j, k]) / hh
                end
            else
                conv = uf * (U.v[i + 1, j, k] - U.v[i - 1, j, k]) / (m.dxc[i] + m.dxc[i + 1])
            end
        elseif i == 1 && wm && nx > 1
            conv = uf * (U.v[2, j, k] + U.v[1, j, k]) / (m.dxf[1] + m.dxc[2])
        elseif i == nx && wm && nx > 1
            conv = uf * (-U.v[nx, j, k] - U.v[nx - 1, j, k]) / (m.dxc[nx] + m.dxf[nx])
        else
            conv = zero(Tf)
        end
        if convection === :upwind
            if U.v[i, j, k] > 0
                conv += U.v[i, j, k] * (U.v[i, j, k] - U.v[i, j - 1, k]) / hD
            else
                conv += U.v[i, j, k] * (U.v[i, j + 1, k] - U.v[i, j, k]) / hU
            end
        else
            conv += U.v[i, j, k] * (U.v[i, j + 1, k] - U.v[i, j - 1, k]) / (hD + hU)
        end
        if k > 1 && k < nz
            if convection === :upwind
                if wf > 0
                    hh = m.dzc[k]
                    conv += wf * (U.v[i, j, k] - U.v[i, j, k - 1]) / hh
                else
                    hh = m.dzc[k + 1]
                    conv += wf * (U.v[i, j, k + 1] - U.v[i, j, k]) / hh
                end
            else
                conv += wf * (U.v[i, j, k + 1] - U.v[i, j, k - 1]) / (m.dzc[k] + m.dzc[k + 1])
            end
        elseif k == 1 && wm && nz > 1
            conv += wf * (U.v[i, j, 2] + U.v[i, j, 1]) / (m.dzf[1] + m.dzc[2])
        elseif k == nz && wm && nz > 1
            conv += wf * (-U.v[i, j, nz] - U.v[i, j, nz - 1]) / (m.dzc[nz] + m.dzf[nz])
        end
        ws.vv[i, j, k] += dtt * (-conv + nv * dif)
        ws.vv[i, j, k] /= (1 + dtt * 0.5 * (drag[i, j - 1, k] + drag[i, j, k]))
    end

    # ---- w-faces (k in 2:nz): 3-D diffusion + convection + buoyancy ----
    @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
        tangential === :layer && is_w_wall(i, j, nx, ny) && continue
        nw = 0.5 * (ws.visc[i, j, k - 1] + ws.visc[i, j, k])
        hB = m.dzf[k]; hA = m.dzf[k + 1]
        dif = 2 / (hB + hA) * ((U.w[i, j, k + 1] - U.w[i, j, k]) / hA -
                               (U.w[i, j, k] - U.w[i, j, k - 1]) / hB)
        if i > 1 && i < nx
            hL = m.dxc[i]; hR = m.dxc[i + 1]
            dif += 2 / (hL + hR) * ((U.w[i + 1, j, k] - U.w[i, j, k]) / hR -
                                    (U.w[i, j, k] - U.w[i - 1, j, k]) / hL)
        elseif i == 1 && wm && nx > 1
            hL = m.dxf[1]; hR = m.dxc[2]
            dif += 2 / (hL + hR) * ((U.w[2, j, k] - U.w[1, j, k]) / hR -
                                    2 * U.w[1, j, k] / hL)
        elseif i == nx && wm && nx > 1
            hL = m.dxc[nx]; hR = m.dxf[nx]
            dif += 2 / (hL + hR) * (-2 * U.w[nx, j, k] / hR -
                                    (U.w[nx, j, k] - U.w[nx - 1, j, k]) / hL)
        end
        if j > 1 && j < ny
            hD = m.dyc[j]; hU = m.dyc[j + 1]
            dif += 2 / (hD + hU) * ((U.w[i, j + 1, k] - U.w[i, j, k]) / hU -
                                    (U.w[i, j, k] - U.w[i, j - 1, k]) / hD)
        elseif j == 1 && wm && ny > 1
            hD = m.dyf[1]; hU = m.dyc[2]
            dif += 2 / (hD + hU) * ((U.w[i, 2, k] - U.w[i, 1, k]) / hU -
                                    2 * U.w[i, 1, k] / hD)
        elseif j == ny && wm && ny > 1
            hD = m.dyc[ny]; hU = m.dyf[ny]
            dif += 2 / (hD + hU) * (-2 * U.w[i, ny, k] / hU -
                                    (U.w[i, ny, k] - U.w[i, ny - 1, k]) / hD)
        end
        uf = 0.25 * (U.u[i, j, k - 1] + U.u[min(i + 1, nx + 1), j, k - 1] +
                     U.u[i, j, k] + U.u[min(i + 1, nx + 1), j, k])
        vf = 0.25 * (U.v[i, j, k - 1] + U.v[i, min(j + 1, ny + 1), k - 1] +
                     U.v[i, j, k] + U.v[i, min(j + 1, ny + 1), k])
        if i > 1 && i < nx
            if convection === :upwind
                if uf > 0
                    hh = m.dxc[i]
                    conv = uf * (U.w[i, j, k] - U.w[i - 1, j, k]) / hh
                else
                    hh = m.dxc[i + 1]
                    conv = uf * (U.w[i + 1, j, k] - U.w[i, j, k]) / hh
                end
            else
                conv = uf * (U.w[i + 1, j, k] - U.w[i - 1, j, k]) / (m.dxc[i] + m.dxc[i + 1])
            end
        elseif i == 1 && wm && nx > 1
            conv = uf * (U.w[2, j, k] + U.w[1, j, k]) / (m.dxf[1] + m.dxc[2])
        elseif i == nx && wm && nx > 1
            conv = uf * (-U.w[nx, j, k] - U.w[nx - 1, j, k]) / (m.dxc[nx] + m.dxf[nx])
        else
            conv = zero(Tf)
        end
        if j > 1 && j < ny
            if convection === :upwind
                if vf > 0
                    hh = m.dyc[j]
                    conv += vf * (U.w[i, j, k] - U.w[i, j - 1, k]) / hh
                else
                    hh = m.dyc[j + 1]
                    conv += vf * (U.w[i, j + 1, k] - U.w[i, j, k]) / hh
                end
            else
                conv += vf * (U.w[i, j + 1, k] - U.w[i, j - 1, k]) / (m.dyc[j] + m.dyc[j + 1])
            end
        elseif j == 1 && wm && ny > 1
            conv += vf * (U.w[i, 2, k] + U.w[i, 1, k]) / (m.dyf[1] + m.dyc[2])
        elseif j == ny && wm && ny > 1
            conv += vf * (-U.w[i, ny, k] - U.w[i, ny - 1, k]) / (m.dyc[ny] + m.dyf[ny])
        end
        if convection === :upwind
            if U.w[i, j, k] > 0
                conv += U.w[i, j, k] * (U.w[i, j, k] - U.w[i, j, k - 1]) / hB
            else
                conv += U.w[i, j, k] * (U.w[i, j, k + 1] - U.w[i, j, k]) / hA
            end
        else
            conv += U.w[i, j, k] * (U.w[i, j, k + 1] - U.w[i, j, k - 1]) / (hB + hA)
        end
        ws.ww[i, j, k] += dtt * (-conv + nw * dif +
                                 0.5 * (buoy[i, j, k - 1] + buoy[i, j, k]))
        ws.ww[i, j, k] /= (1 + dtt * 0.5 * (drag[i, j, k - 1] + drag[i, j, k]))
    end

    # Surface-tension body force. `face_force` is the balanced-force form: the force is
    # already on the faces with the same gradient stencil as the pressure projection, so
    # it is added directly. The cell-centred `fx/fy/fz` (Marangoni, legacy CSF) is
    # averaged onto the faces instead.
    if face_force !== nothing
        fxf, fyf, fzf = face_force
        @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
            ws.uu[i, j, k] += dtt * fxf[i, j, k] / mat.rho_l
        end
        @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
            ws.vv[i, j, k] += dtt * fyf[i, j, k] / mat.rho_l
        end
        @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
            ws.ww[i, j, k] += dtt * fzf[i, j, k] / mat.rho_l
        end
    elseif fx !== nothing
        @inbounds for k in 1:nz, j in 1:ny, i in 2:nx
            ws.uu[i, j, k] += dtt * 0.5 * (fx[i - 1, j, k] + fx[i, j, k]) / mat.rho_l
        end
        @inbounds for k in 1:nz, j in 2:ny, i in 1:nx
            ws.vv[i, j, k] += dtt * 0.5 * (fy[i, j - 1, k] + fy[i, j, k]) / mat.rho_l
        end
        @inbounds for k in 2:nz, j in 1:ny, i in 1:nx
            ws.ww[i, j, k] += dtt * 0.5 * (fz[i, j, k - 1] + fz[i, j, k]) / mat.rho_l
        end
    end
    copyto!(U.u, ws.uu); copyto!(U.v, ws.vv); copyto!(U.w, ws.ww)
    U
end

"""
    viscous_rho(T, mat) -> Float64

Kinematic viscosity `μ/ρ` of the metal at temperature `T`, zero outside the liquid range
(solid metal does not creep in this model).
"""
@inline function viscous_rho(T::Real, mat::Material)
    T > mat.Tliq ? visc(mat, T) / mat.rho_l :
    T > mat.Tsol ? visc(mat, mat.Tliq) / mat.rho_l * 1e-2 : 0.0
end

"""
    max_speed(U) -> Float64

Largest face speed, used by the timestep controller for the Courant limit.
"""
function max_speed(U::VectorField)
    m = 0.0
    @inbounds for x in U.u; abs(x) > m && (m = abs(x)); end
    @inbounds for x in U.v; abs(x) > m && (m = abs(x)); end
    @inbounds for x in U.w; abs(x) > m && (m = abs(x)); end
    m
end

# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

"""
    apply_velocity_bc!(U, m, g; lid)

Impose the domain-boundary velocity conditions.

Every domain boundary face is a wall (no penetration), so its normal component is zero.
Because this staggered layout stores the *tangential* components of a wall on the adjacent
interior face layer rather than on the boundary itself, a moving lid is represented by
setting that adjacent layer: `lid = (wall = :z, side = :hi, comp = :x, value = 1.0)` puts
`value` on the topmost interior `u`-layer. That places the lid half a cell inside the
domain; the error is O(Δx) and vanishes as the mesh is refined.

The tangential zeroing respects the 2-D guard: an axis with a single cell is the
out-of-plane direction and its face layers must not be touched (they are interior faces
of the one and only cell in that direction).

`tangential` selects the wall model. `:layer` (default) is the convention described
above: walls act on the adjacent interior face layer, whose faces are frozen at their
prescribed value. `:wall` is the classical staggered-grid (MAC) treatment: the wall acts
on the domain boundary itself, the adjacent face layers evolve freely, and no-slip is
enforced by the mirror ghosts inside `viscous_candidate!`. `:wall` keeps the discrete
divergence exactly zero across the projection, which threshold-accurate buoyancy
problems need (the layer convention moves the no-slip plane Δ/2 inside and biases the
Rayleigh–Bénard onset by O(Δ⁴) in Ra); it does not support a moving lid.
"""
function apply_velocity_bc!(U::VectorField{Tf}, m::GridMetrics, g::CartesianGrid;
                            lid = nothing, tangential::Symbol = :layer) where {Tf<:AbstractFloat}
    (tangential === :layer || tangential === :wall) ||
        throw(ArgumentError("tangential must be :layer or :wall, got $tangential"))
    nx, ny, nz = g.nx, g.ny, g.nz
    # Normal components on their own boundary faces: exact no-penetration.
    fill!(view(U.u, 1, :, :), zero(Tf)); fill!(view(U.u, nx + 1, :, :), zero(Tf))
    fill!(view(U.v, :, 1, :), zero(Tf)); fill!(view(U.v, :, ny + 1, :), zero(Tf))
    fill!(view(U.w, :, :, 1), zero(Tf)); fill!(view(U.w, :, :, nz + 1), zero(Tf))
    tangential === :wall && lid !== nothing &&
        throw(ArgumentError("lid requires tangential = :layer (the wall-layer convention)"))
    tangential === :wall && return U
    # Tangential components live on the adjacent interior face layer.
    # An axis with ny == 1 (or nx == 1, nz == 1) is the 2-D out-of-plane direction:
    # its face layers are interior faces, not wall layers, and must not be zeroed.
    if ny > 1
        fill!(view(U.u, :, 1, :), zero(Tf)); fill!(view(U.u, :, ny, :), zero(Tf))
        fill!(view(U.w, :, 1, :), zero(Tf)); fill!(view(U.w, :, ny, :), zero(Tf))
    end
    if nz > 1
        fill!(view(U.u, :, :, 1), zero(Tf)); fill!(view(U.u, :, :, nz), zero(Tf))
        fill!(view(U.v, :, :, 1), zero(Tf)); fill!(view(U.v, :, :, nz), zero(Tf))
    end
    if nx > 1
        fill!(view(U.v, 1, :, :), zero(Tf)); fill!(view(U.v, nx, :, :), zero(Tf))
        fill!(view(U.w, 1, :, :), zero(Tf)); fill!(view(U.w, nx, :, :), zero(Tf))
    end
    lid === nothing && return U
    wall = get(lid, :wall, nothing); comp = get(lid, :comp, nothing)
    side = get(lid, :side, :hi); value = Tf(get(lid, :value, 0.0))
    if wall === :z && comp === :x
        side === :hi ? (U.u[:, :, nz] .= value) : (U.u[:, :, 1] .= value)
    elseif wall === :z && comp === :y
        side === :hi ? (U.v[:, :, nz] .= value) : (U.v[:, :, 1] .= value)
    elseif wall === :y && comp === :x
        side === :hi ? (U.u[:, ny, :] .= value) : (U.u[:, 1, :] .= value)
    elseif wall === :y && comp === :z
        side === :hi ? (U.w[:, ny, :] .= value) : (U.w[:, 1, :] .= value)
    elseif wall === :x && comp === :y
        side === :hi ? (U.v[nx, :, :] .= value) : (U.v[1, :, :] .= value)
    elseif wall === :x && comp === :z
        side === :hi ? (U.w[nx, :, :] .= value) : (U.w[1, :, :] .= value)
    else
        throw(ArgumentError("unsupported lid wall=$wall comp=$comp; tangential only"))
    end
    U
end

"""
    step_momentum!(U, ws, F, T, mat, m, g, dt; ...) -> U

One explicit momentum step: boundary conditions, buoyancy/Darcy, the explicit
convection-diffusion predictor, a pressure projection, and the boundary conditions again.

This is the momentum half of `step_fluid!`; it is exposed separately so the fluid stack
can be verified on its own (V13, V14) before the thermal coupling is layered on.
"""
function step_momentum!(U::VectorField{Tf}, ws::MomentumWorkspace{Tf},
                        F::Array{Tf,3}, T::Array{Tf,3}, mat::Material,
                        m::GridMetrics, g::CartesianGrid, dt::Real;
                        mode::PressureMode = PartialVoid(),
                        p_amb::Real = 0.0, f_void::Real = 1e-3,
                        rho_amb::Real = 1000.0, sd::Real = 1e6,
                        lid = nothing, tangential::Symbol = :layer,
                        surf_tension_coeff::Real = 0.0,
                        gmag::Real = 9.80665,
                        convection::Symbol = :central,
                        tol::Real = 1e-9, maxiter::Integer = 3000) where {Tf<:AbstractFloat}
    apply_velocity_bc!(U, m, g; lid = lid, tangential = tangential)
    darcy_and_buoyancy!(ws.drag, ws.buoy, T, mat; sd = sd, rho_amb = rho_amb, gmag = gmag)
    # Surface tension: refresh the interface geometry first, then hand the CSF force to
    # the velocity predictor. In PartialVoid mode the same P_st enters as the interface
    # Dirichlet value instead (see solve_pressure!), so the force must not be applied
    # twice.
    if surf_tension_coeff != 0
        smooth_fraction!(ws.Fs, F, 2)
        curvature!(ws.kappa, ws.Fs, m, g)
        surface_tension_pressure!(ws.Pst, ws.kappa, T, mat)
        mode isa CSF && csf_force_faces!(ws.fxf, ws.fyf, ws.fzf, ws.Pst, ws.Fs,
                                         surf_tension_coeff, m, g)
    end
    use_csf = mode isa CSF && surf_tension_coeff != 0
    viscous_candidate!(U, ws, dt, ws.drag, ws.buoy, mat, T, m, g;
                       face_force = use_csf ? (ws.fxf, ws.fyf, ws.fzf) : nothing,
                       tangential = tangential, convection = convection)
    solve_pressure!(ws, U, F, T, mat, m, g, dt; mode = mode, p_amb = p_amb,
                    f_void = f_void, rho_amb = rho_amb,
                    surf_tension_coeff = surf_tension_coeff, tangential = tangential,
                    tol = tol, maxiter = maxiter)
    project_velocity!(U, ws, dt, ws.drag, F, m, g; tangential = tangential)
    apply_velocity_bc!(U, m, g; lid = lid, tangential = tangential)
    U
end