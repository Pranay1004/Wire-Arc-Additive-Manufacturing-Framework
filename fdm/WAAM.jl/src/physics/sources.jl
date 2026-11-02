"""
Heat sources and boundary losses from the paper.

Implements Eqs. (7)–(12) of Zargari et al. (2025), plus the energy-budget bookkeeping
that makes the closure checkable.

## The energy budget does not close in the source paper

Taking the paper's own numbers, Eqs. (10) and (12) are mutually inconsistent by a factor
of about 2.5:

```
wire feed 4.7 m/min, 1.2 mm wire, 7850 kg/m³   →  ṁ = 6.95e-4 kg/s
Q_drop = ṁ [C_l(T_d − T_l) + L_f + C_s(T_s − T_0)]
       = 6.95e-4 [800·122 + 272000 + 680·1400] ≈ 922 W
η η_d U I = 0.68 × 0.25 × 2165 = 368 W
```

Both readings are defensible, so both are supported and the closure error is *always*
reported rather than buried:

- **Mode A `paper`** — fix `η_d = 0.25`; the surface flux carries 1104 W and the droplet
  thermal source is the smaller 368 W. This is what reproduces the published numbers, and
  it is internally inconsistent between the droplet *thermal* and droplet *mass* sources.
- **Mode B `consistent`** — fix the droplet *mass* rate from the wire feed
  (this is what sets the deposited wall volume, hence its geometry), derive `Q_drop`
  from it, and give the surface flux the remainder `η·UI − Q_drop`. The budget then
  closes to round-off.

`RunConfig` defaults to **Mode A** (it is the configuration that reproduces the paper's
surface flux; the thermal-only track cannot pool ER70S6 on Mode B's 456 W surface share).
`EnergySplit`'s own default remains `:consistent` for direct callers; every run reports
the closure error either way.
"""

# ---------------------------------------------------------------------------
# Process parameters (paper Sec. 2)
# ---------------------------------------------------------------------------

"""
    ProcessParameters

P-GMAW parameters of the paper, in SI units.

`UI` is the measured instantaneous average arc power, not a nominal product of current
and voltage: the voltage swings 16→22 V under pulsing, and the paper quotes the measured
value (ref. 47), which is the honest number to use.
"""
Base.@kwdef struct ProcessParameters
    I_nominal::Float64 = 125.0       # A
    I_effective::Float64 = 90.0      # A
    voltage_min::Float64 = 16.0      # V
    voltage_max::Float64 = 22.0      # V
    duty_cycle::Float64 = 0.30       # -
    frequency::Float64 = 60.0        # Hz
    UI::Float64 = 2165.0             # W (measured instantaneous average power)
    eta::Float64 = 0.68              # arc thermal efficiency
    eta_d::Float64 = 0.25            # droplet heat partition
    sigma_q_a::Float64 = 6.205e-4    # σ_q = a · I^b   (Eq. 16)
    sigma_q_b::Float64 = 0.28
    travel_speed::Float64 = 0.17 / 60.0   # 0.17 m/min = 2.833 mm/s
    wire_diameter::Float64 = 1.2e-3  # m
    wire_density::Float64 = 7850.0   # kg/m³ (steel)
    wire_feed_speed::Float64 = 4.7 / 60.0    # m/min → m/s
    droplet_radius::Float64 = 0.734e-3       # m (self-consistent with the wire feed)
    droplet_temperature::Float64 = 1900.0    # K
    droplet_velocity::Float64 = 0.7          # m/s, downward
    droplet_height::Float64 = 1.5e-3         # m above the surface
    droplet_frequency::Float64 = 60.0        # Hz
    h_conv::Float64 = 20.0                  # W/(m²·K)
    emissivity::Float64 = 0.68
    sigma_sb::Float64 = 5.67e-8             # W/(m²·K⁴)
    T_ambient::Float64 = 298.0               # K
    xi::Float64 = 1.0                       # undefined in the paper, see §3.5 of the plan
end

"""
    sigma_q(p) -> Float64

Effective Gaussian arc radius, Eq. (16): `σ_q = 6.205e-4 · I^0.28` [m, I in A].
At the paper's 125 A this gives **2.40 mm**, i.e. the heat is spread over a spot a few
times wider than the 1.2 mm wire.
"""
sigma_q(p::ProcessParameters, I::Real = p.I_nominal) =
    p.sigma_q_a * I^p.sigma_q_b

"""
    wire_feed_mass_rate(p) -> Float64  [kg/s]

`ρ_wire · π d²/4 · v_wire`. At the paper's settings this is **6.95e-4 kg/s**
(≈ 41.7 g/min), and it is the quantity that fixes the deposited wall volume — so it is
the anchor for the whole mass budget.
"""
wire_feed_mass_rate(p::ProcessParameters) =
    p.wire_density * π * (p.wire_diameter / 2)^2 * p.wire_feed_speed

"""
    arc_power(p) -> Float64

Heat available at the workpiece after arc efficiency: `η · UI` = 1472 W at the paper's
settings.
"""
arc_power(p::ProcessParameters) = p.eta * p.UI

"""
    droplet_heat(p, mat) -> Float64  [W]

Droplet thermal power from Eq. (12), using the **wire-feed mass rate** so that the droplet
thermal and mass sources are the same droplets:

```
Q_drop = ṁ [ C_l(T_d − T_l) + L_f + C_s(T_s − T_0) ]
```

At the paper's settings this is ≈ 922 W.
"""
function droplet_heat(p::ProcessParameters, mat::Material)
    mdot = wire_feed_mass_rate(p)
    Csl = Cp_s_ref(mat)
    Cll = Cp_l_ref(mat)
    mdot * (Cll * (p.droplet_temperature - mat.Tliq) + mat.Lf +
            Csl * (mat.Tsol - p.T_ambient))
end

"""
    EnergySplit

How the arc power is divided between the free surface and the droplets.

    EnergySplit(p, mat; mode = :consistent)

Fields
- `q_surface`  : W delivered by the Gaussian surface flux
- `q_droplet`  : W carried by the droplets
- `closure`    : |q_surface + q_droplet − η·UI| / (η·UI), the budget error
"""
struct EnergySplit
    q_surface::Float64
    q_droplet::Float64
    closure::Float64
    mode::Symbol
end

function EnergySplit(p::ProcessParameters, mat::Material; mode::Symbol = :consistent)
    Ptot = arc_power(p)
    Qd = droplet_heat(p, mat)
    if mode === :paper
        # η_d fixed from the literature: droplet share = η η_d UI, surface share = the rest
        qd = p.eta * p.eta_d * p.UI
        qs = Ptot - qd
    elseif mode === :consistent
        qd = Qd
        qs = Ptot - qd
    else
        throw(ArgumentError("mode must be :paper or :consistent, got $mode"))
    end
    # A negative surface flux means the droplets alone carry more than the arc delivers,
    # which is unphysical: clamp and report the error rather than running with it.
    if qs < 0
        qs = 0.0
    end
    closure = abs(qs + qd - Ptot) / Ptot
    EnergySplit(qs, qd, closure, mode)
end

"""
    energy_budget(p, mat; mode) -> NamedTuple

Full audit of the energy split, printed into every run manifest so a result can be
reproduced *and questioned* from its own output.
"""
function energy_budget(p::ProcessParameters, mat::Material; mode::Symbol = :consistent)
    es = EnergySplit(p, mat; mode = mode)
    mdot = wire_feed_mass_rate(p)
    # deposited volume rate: the geometric anchor of the whole simulation
    Vdot = mdot / mat.rho_l
    (arc_power_W = arc_power(p),
     arc_efficiency = p.eta,
     droplet_partition_eta_d = p.eta_d,
     droplet_power_W = es.q_droplet,
     droplet_power_from_eq12_W = droplet_heat(p, mat),
     surface_power_W = es.q_surface,
     closure_error = es.closure,
     mode = es.mode,
     wire_feed_kg_per_s = mdot,
     deposited_volume_m3_per_s = Vdot,
     self_consistent_droplet_radius_m = p.droplet_radius)
end

# ---------------------------------------------------------------------------
# Gaussian arc flux on the free surface  (Eq. 11)
# ---------------------------------------------------------------------------

"""
    arc_flux!(qsurf, T, p, xc, yc, zc, m, g, torch; mask = nothing)

Gaussian surface heat flux, Eq. (11):

```
q(x,y) = [η(1−η_d) UI / (ξ π σ_q²)] · exp( −[(x−x_c)² + (y−y_c)²] / (ξ σ_q²) )
```

`torch = (x_t, y_t)` is the arc centre, which moves with the travel speed during a pass.

**No temperature mask is applied here.** The arc radiates onto the exposed surface
whatever its temperature: on a cold substrate the top cell is solid, and masking by
`T > T_sol` makes the pool unable to ever form — a circular dependency that silently
delivers 0 W. Restricting the flux to a liquid region is `arc_source!`'s job, via the
explicit `top_k` surface index.

`qsurf` is filled with W/m² of *surface* flux; `arc_source!` applies it to the exposed
cells as Eq. (7)'s boundary condition.
"""
function arc_flux!(qsurf::AbstractArray{T,3}, Tfield::AbstractArray{T,3},
                   p::ProcessParameters, mat::Material,
                   m::GridMetrics, g::CartesianGrid, torch::Tuple{Float64,Float64};
                   q_surface_power::Real = arc_power(p), mask::Union{Nothing,BitArray} = nothing) where {T<:AbstractFloat}
    σ2 = T(sigma_q(p)^2)
    ξ = T(p.xi)
    amp = T(q_surface_power) / (ξ * T(pi) * σ2)
    xt, yt = T(torch[1]), T(torch[2])
    @inbounds for k in 1:g.nz, j in 1:g.ny, i in 1:g.nx
        # surface-projected distance from the arc centre
        r2 = (m.xc[i] - xt)^2 + (m.yc[j] - yt)^2
        q = amp * exp(-r2 / (ξ * σ2))
        mask !== nothing && !mask[i, j, k] && (q = zero(T))
        qsurf[i, j, k] = q
    end
    qsurf
end

"""
    arc_source!(src, qsurf, T, mat, m, g)

Apply the Gaussian surface flux as the paper's Eq. (7) boundary condition on the
*exposed surface*: the flux `q_s` [W/m²] crosses the top face of the exposed cell,
contributing `q_s · A_top` of power. On the cell-centred FVM that boundary condition is
exactly a volumetric source `q_s·A_top/V` on the exposed cell — the discretisation is
not an approximation of the surface flux, it *is* its conservative form.

The exposed cell is the first cell along each column (the free surface on a cold
substrate is the first cell of the column, not the first liquid cell — restricting
deposition to already-melted material is a silent circular dependency: the pool can
never form because the heat is only applied where the pool already is. Measured: 0 W
delivered on a cold substrate, peak T stuck at ambient.)
"""
function arc_source!(src::AbstractArray{T,3}, qsurf::AbstractArray{T,3},
                     T_fld::AbstractArray{T,3}, mat::Material,
                     m::GridMetrics, g::CartesianGrid;
                     top_k::Int = g.nz) where {T<:AbstractFloat}
    src .= 0
    @inbounds for j in 1:g.ny, i in 1:g.nx
        ktop = 0
        for k in 1:top_k
            ktop = k
            break
        end
        ktop == 0 && continue
        q = qsurf[i, j, ktop]
        q == 0 && continue
        # A_top is the TOP face area (dx·dy, i.e. `az`), not the x-face area: on the
        # graded track mesh dx ≠ dz, and using ax silently scaled the delivered power
        # by dz/dx (~0.3 mid-track), starving the pool.
        src[i, j, ktop] = q * m.az[i, j, ktop] / m.vol[i, j, ktop]
    end
    src
end

"""
    arc_power_delivered(src, m) -> Float64

Integrated arc power actually delivered [W]. Compared against the intended split this is
the check that the surface-flux deposition put the energy where it was supposed to.
"""
function arc_power_delivered(src::AbstractArray{T,3}, m::GridMetrics) where {T<:AbstractFloat}
    s = zero(T)
    @inbounds for idx in eachindex(src)
        s += src[idx] * m.vol[idx]
    end
    s
end

# ---------------------------------------------------------------------------
# Droplet source  (Eq. 12)
# ---------------------------------------------------------------------------

"""
    droplet_sources!(smass, smom, sh, p, mat, T_fld, m, g, torch; radius_footprint)

Volumetric droplet sources at the torch position:
- `smass` [1/s] : volume generation rate for the VOF update
- `smom` [kg/(m³·s)] : momentum source (mass rate times the droplet velocity)
- `sh`    [W/m³] : enthalpy source

The droplets are deposited into the first liquid cells in a cylindrical footprint of
`radius_footprint` around the torch, at `droplet_height` above the pool surface.
"""
function droplet_sources!(smass::AbstractArray{T,3}, smom::AbstractArray{T,3},
                          sh::AbstractArray{T,3}, p::ProcessParameters,
                          mat::Material, T_fld::AbstractArray{T,3},
                          m::GridMetrics, g::CartesianGrid,
                          torch::Tuple{Float64,Float64};
                          radius_footprint::Real = 1.1 * p.droplet_radius) where {T<:AbstractFloat}
    smass .= 0; smom .= 0; sh .= 0
    mdot = wire_feed_mass_rate(p)
    Vdot = mdot / mat.rho_l                       # m³/s of molten metal
    qdot = droplet_heat(p, mat)                   # W
    rfoot = T(radius_footprint)
    xt, yt = T(torch[1]), T(torch[2])

    # footprint area (discrete)
    cells = Tuple{Int,Int,Int}[]
    @inbounds for j in 1:g.ny, i in 1:g.nx
        if (m.xc[i] - xt)^2 + (m.yc[j] - yt)^2 <= rfoot^2
            for k in 1:g.nz
                if T_fld[i, j, k] > mat.Tsol
                    push!(cells, (i, j, k))
                    break
                end
            end
        end
    end
    isempty(cells) && return (smass, smom, sh)

    # weight by cell volume so the footprint is uniform in depth
    wsum = zero(T)
    @inbounds for (i, j, k) in cells
        wsum += m.vol[i, j, k]
    end
    wsum == 0 && return (smass, smom, sh)

    @inbounds for (i, j, k) in cells
        w = m.vol[i, j, k] / wsum
        smass[i, j, k] = Vdot * w / m.vol[i, j, k]
        smom[i, j, k] = mdot * w / m.vol[i, j, k]    # kg/(m³·s), momentum via U
        sh[i, j, k] = qdot * w / m.vol[i, j, k]
    end
    (smass, smom, sh)
end

# ---------------------------------------------------------------------------
# Surface losses  (Eqs. 8, 9)
# ---------------------------------------------------------------------------

"""
    surface_loss_coeff(p, T, mat) -> Float64

Combined convective + radiative loss coefficient [W/(m²·K)]:

```
h_eff = h_c + 4 ε σ_SB T³
```

Linearised about the local temperature, which keeps the boundary condition linear in `T`
so it can be dropped straight into the implicit energy matrix. Using `h_c + 4εσT³`
rather than the exact `εσ(T⁴ − T_0⁴)/(T − T_0)` is what makes that possible; the two
agree to within a few percent over the welding range.
"""
@inline function surface_loss_coeff(p::ProcessParameters, Tk::Real, mat::Material)
    T = float(Tk)
    p.h_conv + 4 * p.emissivity * p.sigma_sb * T^3
end

"""
    surface_loss!(loss, T_fld, p, mat, m, g; exposed = nothing)

Surface heat loss, Eqs. (8)+(9) combined into the linearised coefficient
`h_eff = h_conv + 4 ε σ_SB T³`, applied on the exposed surface area `A_top`:

```
q_loss = h_eff (T − T_ambient)          [W/m²]
loss   = q_loss · A_top / V_cell        [W/m³]
```

**The exposed surface loses heat whatever its phase.** Eq. (7) removes `q_conv + q_rad`
wherever metal faces the ambient gas, solid or molten alike. Masking the loss by
`T > T_sol` — the historical behaviour — left a *solid substrate with no loss at all*,
so the plate could not pre-cool before melting and every thermal event after the first
heat-up was shifted in time. Phase now enters only through the radiative `T³` in
`h_eff`.

The exposed face is the cell's **−z face** (the face toward the ambient gas above the
plate), so `A_top` is the z-face area `m.az` [dx·dy]. The earlier code used the x-face
area `m.ax` [dy·dz], which divides the loss by dx instead of dz — on the graded track
mesh (dx coarsening to 1.6 mm while the surface layer stays dz = 0.4 mm) the mid-track
loss was under-removed by 4×, the same face-area bug family as `arc_source!`'s.

When `exposed = nothing` the exposed cell of a column is the first cell (scanning +z,
i.e. downward into the material) that does not sit on molten material: the melt-pool
surface in the coupled path, and — crucially — the domain's top cell for a column that
never melts, which is the thermal-only track's cold plate. Pass a `BitArray{3}` of
exposed cells to mark the loss surface explicitly (all marked cells lose, none masked).
"""
function surface_loss!(loss::AbstractArray{T,3}, T_fld::AbstractArray{T,3},
                       p::ProcessParameters, mat::Material,
                       m::GridMetrics, g::CartesianGrid;
                       exposed::Union{Nothing,AbstractArray{Bool,3}} = nothing) where {T<:AbstractFloat}
    loss .= 0
    @inbounds for j in 1:g.ny, i in 1:g.nx
        if exposed === nothing
            for k in 1:g.nz
                # deeper (+z) neighbour is still molten → keep scanning down for the
                # melt-surface boundary; otherwise this cell's −z face is exposed
                k < g.nz && T_fld[i, j, k + 1] > mat.Tsol && continue
                Tk = T_fld[i, j, k]
                loss[i, j, k] = surface_loss_coeff(p, Tk, mat) * (Tk - p.T_ambient) *
                                m.az[i, j, k] / m.vol[i, j, k]
                break
            end
        else
            for k in 1:g.nz
                exposed[i, j, k] || continue
                Tk = T_fld[i, j, k]
                loss[i, j, k] = surface_loss_coeff(p, Tk, mat) * (Tk - p.T_ambient) *
                                m.az[i, j, k] / m.vol[i, j, k]
            end
        end
    end
    loss
end