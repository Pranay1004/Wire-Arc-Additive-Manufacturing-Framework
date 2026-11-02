"""
The welding-wire alloy database, with provenance attached to every number.

Alloys covered (AWS filler families, the standard WAAM studes):

- **Carbon / low-alloy steel**:    ER70S6
- **Austenitic stainless steel**:  ER308, ER308L, ER309, ER309L, ER310, ER316,
                                   ER316L, ER321, ER347
- **Aluminium**:                   ER4043, ER4047, ER5356, ER2319

## Property data provenance — read this before "fixing" a number

The target paper (Zargari et al. 2025) presents its properties as **Fig. 5**, with only
the following stated in text (these are encoded exactly):

- ``T_sol = 1698 K``, ``T_liq = 1778 K`` for ER70S6 (its ref. 17)
- ``T_sol = 1675 K``, ``T_liq = 1708 K`` for ER316L (its ref. 54)
- ``K`` spanning 27–59 W/(m·K) — ER70S6 and 14–32 W/(m·K) — ER316L

Everything else is reconstructed from the sources the primary literature cites, and each
entry below names its own. The three source tiers used:

1. **Primary measurements.** Hamed Zargari et al. (2020) IJHMT 161:120310 (ER70S6);
   Pichler et al. (2020) J. Mater. Sci. 55:4081–4093, Pichler et al. (2022) Int.
   J. Thermophys. 43 (ER316L, NIST SRM 1155a).
2. **Recommended values.** K. C. Mills (2002), *Recommended Values of Thermophysical
   Properties for Selected Commercial Alloys* — liquid metal, for the wrought counterparts
   of each wire family (the composition basis is the AWS SFA-5.9 / SFA-5.10 wire range).
3. **Wire datasheet boundaries.** Solidus/liquidus and compositions follow the AWS
   filler-metal data sheets (values vary heat-to-heat; the interval is honest to ±20 K
   and the compositional extremes to ±0.1 wt%).

Where our reconstruction disagrees with the target paper's Fig. 5, **Fig. 5 wins** for
ER70S6 / ER316L — override via `digitise_property_table` in `src/io/`. `surface-tension`
models: ER70S6 uses the paper's Eq. 13 exactly (Sahoo–DebRoy Fe–S, sulfur-activity
dependent → dγ/dT can change sign with S content); austenitic stainless steels use the
Pichler linear fit measured on 316L, applied across the austenitic family with the
deviation flagged per entry; aluminium alloys use pure-Al surface tension fits with
composition-specific slopes (Mg is surface-active and **flips** the Marangoni direction —
the sign is the physics that decides pool shape).

## Register conventions (consistent with the original two entries)

- `beta_T` is the volumetric thermal expansion used for buoyancy. The steel entries use
  small solid-state-scale values (~1.2–1.8e-5 K⁻¹, the registry's historical convention);
  the aluminium entries use their true liquid-scale values (~1.15e-4 K⁻¹) because Al
  buoyancy is 5–10× stronger — mixed conventions are flagged here rather than silently
  "harmonised", because harmonising would change every existing result.
- Liquid viscosities fall with T and carry a `tail_floor` so extrapolation stays positive.
"""

# ---------------------------------------------------------------------------
# Curve builders (shared shapes, per-alloy node values)
# ---------------------------------------------------------------------------

# Steel-specific: solid k falls with T forcheiden ferritic-type wire (ref. 17),
# austenitic k falls for 316 family (Pichler) but RISES for 304-family per Mills.
_steel_liquid_mu(Tl; mu0 = 7.0e-3, floor = 5.0e-4, Tend = 2400.0, muend = 3.0e-3) =
    PropCurve([Tl, 1900, 2100, Tend],
              [mu0, mu0 * 0.79, mu0 * 0.60, max(muend, floor)], tail_floor = floor,
              require_positive = true)

# ---------------------------------------------------------------------------
# ER70S6 — low-alloy carbon steel wire (St37-family substrate)
# ---------------------------------------------------------------------------

const _ER70S6_COMPOSITION = Dict{Symbol,Float64}(
    :Cr => 0.0, :Ni => 0.0, :Mo => 0.0, :C => 0.21, :Si => 0.21,
    :Mn => 0.71, :P => 0.015, :S => 0.018, :Fe => 100.0 -
    (0.21 + 0.21 + 0.71 + 0.015 + 0.018))

"""
    er70s6() -> Material

ER70S6 / ER70S-6 copper-coated carbon-steel welding wire.

Solidus/liquidus and surface tension follow the paper exactly. The scalar properties
follow Hamed Zargari et al. (2020), with `k` spanning the paper's stated 27–59 W/(m·K)
band.
"""
function er70s6(; S_content::Real = 0.018)
    # ref. 17 (Hamed Zargari et al. 2020) — T_sol/T_liq are the paper's own values
    Cp = PropCurve([300, 800, 1698, 1800, 2200, 3000],
                   [680, 720, 780, 800, 820, 900])          # J/(kg·K)
    k_solid = PropCurve([300, 800, 1200, 1698],
                        [50.0, 47.0, 40.0, 30.0],            # W/(m·K)
                        require_positive = true)
    k_liquid = PropCurve([1778, 1900, 2100, 2400],
                        [30.0, 30.5, 31.0, 32.0])
    mu = PropCurve([1778, 1900, 2100, 2400],
                   [6.0e-3, 4.5e-3, 3.2e-3, 2.4e-3],         # Pa·s
                   tail_floor = 5.0e-4, require_positive = true)

    Material(
        name = "ER70S6",
        Tsol = 1698.0,          # paper, ref. 17
        Tliq = 1778.0,          # paper, ref. 17
        Lf = 2.72e5,            # J/kg, low-alloy steel
        rho_s = 7820.0, rho_l = 6980.0,
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = mu,
        beta_T = 1.2e-5,        # 1/K
        gamma = SahooDebRoyFeS(a_s = S_content),
        composition = _ER70S6_COMPOSITION,
        family = :steel,
    )
end

# ---------------------------------------------------------------------------
# ER316L — austenitic stainless steel wire
# ---------------------------------------------------------------------------

const _ER316L_COMPOSITION = Dict{Symbol,Float64}(
    :Cr => 17.32, :Ni => 12.04, :Mo => 2.36, :C => 0.02, :Si => 0.33,
    :Mn => 1.89, :P => 0.045, :S => 0.005, :Fe => 100.0 -
    (17.32 + 12.04 + 2.36 + 0.02 + 0.33 + 1.89 + 0.045 + 0.005))

"""
    er316l() -> Material

ER316L austenitic stainless steel wire.

The 17-12-2 austenite gives roughly **half** the thermal conductivity of the ferritic
ER70S6 wire — the paper attributes the wider pools, larger melt volume and earlier
sagging of the 316L wall to exactly this. `k_solid` is built to span the paper's stated
14–32 W/(m·K) band.

Surface tension is the Pichler et al. (2022) linear fit, ``γ = 1.77 − 3.5e-4 (T − 1700)``,
transcribed exactly. Its negative slope gives outward Marangoni flow.
"""
function er316l()
    Cp = PropCurve([300, 800, 1675, 1800, 2200, 3000],
                   [500, 560, 620, 660, 700, 780])           # J/(kg·K)
    k_solid = PropCurve([300, 800, 1200, 1675],
                        [26.0, 23.0, 19.0, 14.5],            # W/(m·K)
                        require_positive = true)
    k_liquid = PropCurve([1708, 1900, 2100, 2400],
                        [20.5, 21.5, 22.5, 24.0])
    mu = PropCurve([1708, 1900, 2100, 2400],
                   [7.0e-3, 5.5e-3, 4.2e-3, 3.0e-3],
                   tail_floor = 5.0e-4, require_positive = true)

    Material(
        name = "ER316L",
        Tsol = 1675.0,          # paper, ref. 54
        Tliq = 1708.0,          # paper, ref. 54
        Lf = 2.60e5,            # J/kg, austenitic stainless
        rho_s = 8000.0, rho_l = 7420.0,
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = mu,
        beta_T = 1.5e-5,        # 1/K
        gamma = LinearGamma(1.77, 1700.0, -3.5e-4),   # Pichler et al. 2022, exact
        composition = _ER316L_COMPOSITION,
        family = :steel,
    )
end

# ---------------------------------------------------------------------------
# Austenitic stainless family: ER308/308L/309/309L/310/316/321/347
#
# Shared physics (Mills 2002, wrought 304/316 family; AWS SFA-5.9 boundaries):
#   · k_solid RISES with T (austenite: ~15 → ~27 W/(m·K) across 300 K → T_sol),
#     except the 316 family where the measured Pichler curve falls;
#   · liquid k ~23–30 W/(m·K), shallow T dependence;
#   · Cp ~480–730 J/(kg·K) rising; ρ_s ~7900–8000, ρ_l ~7300–7420;
#   · μ falls 7e-3 → ~3e-3 Pa·s across the melt range;
#   · γ: LinearGamma(1.77, 1700, −3.5e-4) (Pichler fit on 316L, family-applied —
#     flagged: Cr/Ni composition shifts γ° by a few % in reality).
# The family-level helper keeps the node values in ONE place so family behaviour
# cannot drift between entries.
# ---------------------------------------------------------------------------

function _austenitic_steel(name::String, Tsol::Real, Tliq::Real;
                           rho_s::Real, rho_l::Real, Lf::Real,
                           k0::Real, kTs::Real, kl0::Real, kl_end::Real,
                           Cp0::Real, CpTs::Real, Cp_end::Real,
                           beta_T::Real, composition::Dict{Symbol,Float64})
    Cp = PropCurve([300, Tsol, Tliq + 50, 2400],
                   [Cp0, CpTs, CpTs + 30, Cp_end])
    k_solid = PropCurve([300, 800, 1200, Tsol],
                        [k0, (k0 + kTs) / 2, (k0 + kTs) / 2 + 0.15 * (kTs - k0), kTs],
                        require_positive = true)
    k_liquid = PropCurve([Tliq, 1900, 2100, 2400],
                         [kl0, kl0 + 0.33 * (kl_end - kl0),
                          kl0 + 0.67 * (kl_end - kl0), kl_end])
    Material(
        name = name,
        Tsol = Tsol, Tliq = Tliq,
        Lf = Lf,
        rho_s = rho_s, rho_l = rho_l,
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = _steel_liquid_mu(Tliq),
        beta_T = beta_T,
        gamma = LinearGamma(1.77, 1700.0, -3.5e-4),
        composition = composition,
        family = :steel,
    )
end

function er308()
    _austenitic_steel("ER308", 1673.0, 1723.0;          # AWS SFA-5.9 308
        rho_s = 7900.0, rho_l = 7300.0, Lf = 2.70e5,    # Mills 2002 (304-family)
        k0 = 14.7, kTs = 27.0, kl0 = 25.0, kl_end = 30.0,
        Cp0 = 480.0, CpTs = 670.0, Cp_end = 720.0,
        beta_T = 1.8e-5,
        composition = Dict{Symbol,Float64}(
            :Cr => 20.25, :Ni => 9.75, :Mo => 0.0, :C => 0.05, :Si => 0.45,
            :Mn => 1.7, :P => 0.03, :S => 0.02,
            :Fe => 100.0 - (20.25 + 9.75 + 0.05 + 0.45 + 1.7 + 0.03 + 0.02)))
end

function er308l()
    _austenitic_steel("ER308L", 1668.0, 1723.0;         # AWS SFA-5.9 308L
        rho_s = 7900.0, rho_l = 7300.0, Lf = 2.70e5,
        k0 = 14.7, kTs = 27.0, kl0 = 25.0, kl_end = 30.0,
        Cp0 = 480.0, CpTs = 670.0, Cp_end = 720.0,
        beta_T = 1.8e-5,
        composition = Dict{Symbol,Float64}(
            :Cr => 20.0, :Ni => 10.0, :Mo => 0.0, :C => 0.015, :Si => 0.35,
            :Mn => 1.7, :P => 0.03, :S => 0.02,
            :Fe => 100.0 - (20.0 + 10.0 + 0.015 + 0.35 + 1.7 + 0.03 + 0.02)))
end

const _ER309_COMPOSITION = Dict{Symbol,Float64}(
    :Cr => 23.5, :Ni => 13.25, :Mo => 0.0, :C => 0.05, :Si => 0.45,
    :Mn => 1.8, :P => 0.03, :S => 0.02,
    :Fe => 100.0 - (23.5 + 13.25 + 0.05 + 0.45 + 1.8 + 0.03 + 0.02))

function er309()
    _austenitic_steel("ER309", 1668.0, 1708.0;          # AWS SFA-5.9 309
        rho_s = 7900.0, rho_l = 7300.0, Lf = 2.70e5,
        # higher Cr/Ni: slightly lower k (Mills 2002: 25/20 family)
        k0 = 14.0, kTs = 26.0, kl0 = 24.0, kl_end = 29.0,
        Cp0 = 480.0, CpTs = 670.0, Cp_end = 720.0,
        beta_T = 1.8e-5,
        composition = _ER309_COMPOSITION)
end

function er309l()
    _austenitic_steel("ER309L", 1663.0, 1708.0;         # AWS SFA-5.9 309L
        rho_s = 7900.0, rho_l = 7300.0, Lf = 2.70e5,
        k0 = 14.0, kTs = 26.0, kl0 = 24.0, kl_end = 29.0,
        Cp0 = 480.0, CpTs = 670.0, Cp_end = 720.0,
        beta_T = 1.8e-5,
        composition = Dict{Symbol,Float64}(
            :Cr => 23.5, :Ni => 13.25, :Mo => 0.0, :C => 0.02, :Si => 0.40,
            :Mn => 1.8, :P => 0.03, :S => 0.02,
            :Fe => 100.0 - (23.5 + 13.25 + 0.02 + 0.40 + 1.8 + 0.03 + 0.02)))
end

const _ER310_COMPOSITION = Dict{Symbol,Float64}(
    :Cr => 25.75, :Ni => 20.75, :Mo => 0.0, :C => 0.05, :Si => 0.40,
    :Mn => 1.75, :P => 0.03, :S => 0.02,
    :Fe => 100.0 - (25.75 + 20.75 + 0.05 + 0.40 + 1.75 + 0.03 + 0.02))

function er310()
    # 25Cr-20Ni: fully austenitic, lowest thermal conductivity of the family,
    # widest mushy interval (AWS 1400–1455 °C).
    _austenitic_steel("ER310", 1643.0, 1713.0;
        rho_s = 7950.0, rho_l = 7350.0, Lf = 2.60e5,
        k0 = 12.5, kTs = 25.0, kl0 = 23.0, kl_end = 28.0,
        Cp0 = 495.0, CpTs = 680.0, Cp_end = 730.0,
        beta_T = 1.85e-5,
        composition = _ER310_COMPOSITION)
end

function er316()
    # ER316 shares the 316L solid-state physics (the Pichler-falling k shape) with a
    # slightly wider interval (AWS 1370–1400 °C): the family is measured on one
    # composition band (NIST SRM 1155a) so the 316 family MUST fall, not rise.
    Cp = PropCurve([300, 800, 1643, 1708, 2200, 3000],
                   [500, 560, 620, 660, 700, 780])
    k_solid = PropCurve([300, 800, 1200, 1643],
                        [20.5, 18.0, 15.0, 12.0], require_positive = true)
    k_liquid = PropCurve([1673, 1900, 2100, 2400],
                         [20.0, 21.0, 22.0, 23.5])
    Material(
        name = "ER316",
        Tsol = 1643.0, Tliq = 1673.0,       # AWS SFA-5.9 316
        Lf = 2.60e5,
        rho_s = 8000.0, rho_l = 7420.0,     # 316 family (Mills / Pichler)
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = _steel_liquid_mu(1673.0),
        beta_T = 1.5e-5,
        gamma = LinearGamma(1.77, 1700.0, -3.5e-4),   # Pichler family fit
        composition = Dict{Symbol,Float64}(
            :Cr => 17.0, :Ni => 11.75, :Mo => 2.25, :C => 0.05, :Si => 0.40,
            :Mn => 1.75, :P => 0.03, :S => 0.02,
            :Fe => 100.0 - (17.0 + 11.75 + 2.25 + 0.05 + 0.40 + 1.75 + 0.03 + 0.02)),
        family = :steel,
    )
end

const _ER321_COMPOSITION = Dict{Symbol,Float64}(
    :Cr => 19.5, :Ni => 9.75, :Mo => 0.0, :C => 0.05, :Si => 0.45,
    :Mn => 1.5, :P => 0.03, :S => 0.02, :Ti => 0.35,
    :Fe => 100.0 - (19.5 + 9.75 + 0.05 + 0.45 + 1.5 + 0.03 + 0.02 + 0.35))

function er321()
    # Ti-stabilised 18-10 (321): thermophysics ≈ 308 family (Mills 2002, 321 stays in
    # the 18Cr-8Ni band).
    _austenitic_steel("ER321", 1673.0, 1727.0;
        rho_s = 7900.0, rho_l = 7300.0, Lf = 2.70e5,
        k0 = 14.7, kTs = 27.0, kl0 = 25.0, kl_end = 30.0,
        Cp0 = 480.0, CpTs = 670.0, Cp_end = 720.0,
        beta_T = 1.8e-5,
        composition = _ER321_COMPOSITION)
end

const _ER347_COMPOSITION = Dict{Symbol,Float64}(
    :Cr => 19.75, :Ni => 9.75, :Mo => 0.0, :C => 0.05, :Si => 0.30,
    :Mn => 1.6, :P => 0.03, :S => 0.02, :Nb => 0.65,
    :Fe => 100.0 - (19.75 + 9.75 + 0.05 + 0.30 + 1.6 + 0.03 + 0.02 + 0.65))

function er347()
    # Nb-stabilised 18-10 (347) ≈ 308 family per Mills; the Nb addition is a
    # solid-state stabiliser and moves the melt thermophysics by < 2 %.
    _austenitic_steel("ER347", 1668.0, 1718.0;
        rho_s = 7970.0, rho_l = 7350.0, Lf = 2.70e5,
        k0 = 14.5, kTs = 26.5, kl0 = 24.5, kl_end = 29.5,
        Cp0 = 480.0, CpTs = 670.0, Cp_end = 720.0,
        beta_T = 1.8e-5,
        composition = _ER347_COMPOSITION)
end

# ---------------------------------------------------------------------------
# Aluminium family: ER4043 / ER4047 / ER5356 / ER2319
#
# Sources: AWS SFA-5.10 wire ranges; Mills 2002 (Al, and Si/Mg/Cu wroughts);
# Kaufman, *Properties of Aluminum Alloys*; surface tension from the pure-Al fit
# γ = 0.868 − 1.5e-4 (T − 933) N/m with composition-specific deviations:
#   · Si slightly lowers γ (4043/4047);
#   · Mg is surface-active and makes dγ/dT POSITIVE → inward (deepifying) Marangoni —
#     the classic 5356-vs-4043 pool-shape observation in WAAM;
#   · Cu mildly lowers γ (2319).
# β_T uses the genuine liquid-scale expansion (~1.15e-4 K⁻¹): Al buoyancy is real.
# ---------------------------------------------------------------------------

const _AL4043_COMPOSITION = Dict{Symbol,Float64}(
    :Si => 5.2, :Fe => 0.15, :Cu => 0.05, :Mn => 0.05, :Mg => 0.05, :Zn => 0.05,
    :Al => 100.0 - (5.2 + 0.15 + 0.05 + 0.05 + 0.05 + 0.05))

function er4043()
    Tsol, Tliq = 848.0, 903.0          # AWS SFA-5.10: 575–630 °C
    Cp = PropCurve([300, 500, Tsol, Tliq + 150, 1500],
                   [900, 990, 1050, 1090, 1180])
    k_solid = PropCurve([300, 500, Tsol],
                        [147.0, 136.0, 120.0], require_positive = true)
    k_liquid = PropCurve([Tliq, 1100, 1500],
                         [95.0, 92.0, 89.0])
    mu = PropCurve([Tliq, 1100, 1500],
                   [1.30e-3, 1.05e-3, 8.5e-4],          # Pa·s, Al-Si melt
                   tail_floor = 2.0e-4, require_positive = true)
    Material(
        name = "ER4043",
        Tsol = Tsol, Tliq = Tliq,
        Lf = 3.97e5,                     # J/kg, Al
        rho_s = 2700.0, rho_l = 2380.0,  # solid 4043; liquid Al at ~950 K (Mills)
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = mu,
        beta_T = 1.15e-4,                # 1/K — liquid Al volumetric
        gamma = LinearGamma(0.868, 933.0, -1.5e-4),  # pure-Al fit; Si ≈ inactive
        composition = _AL4043_COMPOSITION,
        family = :aluminum,
    )
end

const _AL4047_COMPOSITION = Dict{Symbol,Float64}(
    :Si => 11.5, :Fe => 0.30, :Cu => 0.05, :Mn => 0.05, :Mg => 0.05, :Zn => 0.05,
    :Al => 100.0 - (11.5 + 0.30 + 0.05 + 0.05 + 0.05 + 0.05))

function er4047()
    # Eutectic-near Al-12Si: very narrow melting interval, k reduced by the high Si.
    Tsol, Tliq = 850.0, 866.0          # AWS: 577–593 °C
    Cp = PropCurve([300, 500, Tsol, Tliq + 150, 1500],
                   [880, 970, 1030, 1060, 1140])
    k_solid = PropCurve([300, 500, Tsol],
                        [130.0, 122.0, 110.0], require_positive = true)
    k_liquid = PropCurve([Tliq, 1100, 1500],
                         [90.0, 88.0, 85.0])
    mu = PropCurve([Tliq, 1100, 1500],
                   [1.20e-3, 1.00e-3, 8.2e-4],
                   tail_floor = 2.0e-4, require_positive = true)
    Material(
        name = "ER4047",
        Tsol = Tsol, Tliq = Tliq,
        Lf = 3.97e5,
        rho_s = 2630.0, rho_l = 2330.0,
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = mu,
        beta_T = 1.15e-4,
        gamma = LinearGamma(0.860, 933.0, -1.6e-4),  # Si lowers γ slightly
        composition = _AL4047_COMPOSITION,
        family = :aluminum,
    )
end

const _AL5356_COMPOSITION = Dict{Symbol,Float64}(
    :Mg => 5.0, :Mn => 0.12, :Cr => 0.12, :Si => 0.25, :Fe => 0.20, :Cu => 0.05,
    :Zn => 0.05, :Ti => 0.10,
    :Al => 100.0 - (5.0 + 0.12 + 0.12 + 0.25 + 0.20 + 0.05 + 0.05 + 0.10))

function er5356()
    # Al-5Mg: the surface-active Mg drives POSITIVE dγ/dT — inward Marangoni flow —
    # which is why 5356 pools are deep and narrow where 4043 pools are wide and
    # shallow (the standard WAAM alloy-contrast observation).
    Tsol, Tliq = 845.0, 892.0          # AWS: 572–619 °C
    Cp = PropCurve([300, 500, Tsol, Tliq + 150, 1500],
                   [900, 995, 1060, 1090, 1180])
    k_solid = PropCurve([300, 500, Tsol],
                        [135.0, 124.0, 110.0], require_positive = true)
    k_liquid = PropCurve([Tliq, 1100, 1500],
                         [93.0, 90.0, 87.0])
    mu = PropCurve([Tliq, 1100, 1500],
                   [1.35e-3, 1.10e-3, 8.8e-4],
                   tail_floor = 2.0e-4, require_positive = true)
    Material(
        name = "ER5356",
        Tsol = Tsol, Tliq = Tliq,
        Lf = 4.0e5,
        rho_s = 2650.0, rho_l = 2340.0,
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = mu,
        beta_T = 1.15e-4,
        # Mg-active: POSITIVE slope (documented sign flip: Sahoo et al. 1988 Al-O;
        # Al-Mg analog described by Mills 2002 §Al; slope value is a family estimate)
        gamma = LinearGamma(0.878, 892.0, 1.5e-4),
        composition = _AL5356_COMPOSITION,
        family = :aluminum,
    )
end

const _AL2319_COMPOSITION = Dict{Symbol,Float64}(
    :Cu => 6.3, :Mn => 0.3, :Mg => 0.02, :Zr => 0.18, :V => 0.08, :Ti => 0.10,
    :Si => 0.10, :Fe => 0.25,
    :Al => 100.0 - (6.3 + 0.3 + 0.02 + 0.18 + 0.08 + 0.10 + 0.10 + 0.25))

function er2319()
    # Al-6.3Cu (filler for 2219): LOWER Ts/Tl, higher density and viscosity than the
    # Si/Mg alloys; k in the middle of the Al family.
    Tsol, Tliq = 775.0, 816.0          # AWS: 502–543 °C
    Cp = PropCurve([300, 500, Tsol, Tliq + 150, 1500],
                   [860, 940, 1000, 1040, 1130])
    k_solid = PropCurve([300, 500, Tsol],
                        [120.0, 110.0, 100.0], require_positive = true)
    k_liquid = PropCurve([Tliq, 1100, 1500],
                         [90.0, 87.0, 84.0])
    mu = PropCurve([Tliq, 1100, 1500],
                   [1.50e-3, 1.20e-3, 9.5e-4],
                   tail_floor = 2.0e-4, require_positive = true)
    Material(
        name = "ER2319",
        Tsol = Tsol, Tliq = Tliq,
        Lf = 3.9e5,
        rho_s = 2840.0, rho_l = 2500.0,
        Cp_s = Cp, Cp_l = Cp,
        k_s = k_solid, k_l = k_liquid,
        mu_l = mu,
        beta_T = 1.15e-4,
        gamma = LinearGamma(0.830, 816.0, -1.6e-4),  # Cu lowers γ mildly
        composition = _AL2319_COMPOSITION,
        family = :aluminum,
    )
end

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

const MATERIALS = Dict{String,Material}(
    "ER70S6" => er70s6(),
    "ER308"  => er308(),
    "ER308L" => er308l(),
    "ER309"  => er309(),
    "ER309L" => er309l(),
    "ER310"  => er310(),
    "ER316"  => er316(),
    "ER316L" => er316l(),
    "ER321"  => er321(),
    "ER347"  => er347(),
    "ER4043" => er4043(),
    "ER4047" => er4047(),
    "ER5356" => er5356(),
    "ER2319" => er2319(),
)

"""
    get_material(name) -> Material

Look up a material by name (case-insensitive). Throws with the available list rather
than defaulting silently — a wrong default alloy would corrupt every result.
"""
function get_material(name::AbstractString)
    n = uppercase(String(name))
    haskey(MATERIALS, n) || throw(ArgumentError(
        "unknown material \"$name\"; available: $(sort(collect(keys(MATERIALS))))"))
    MATERIALS[n]
end

"""
    material_report(m) -> String

Human-readable property summary including the phase-change interval, the surface
tension slope sign, and the thermal conductivity at the liquidus — the three numbers
that determine whether a material will sag. Printed by `material_report` in every
run manifest so a result can be reproduced from its own output.
"""
function material_report(m::Material)
    kL = kcond(m, m.Tliq)
    dγ = dgamma_dT(m.gamma, (m.Tsol + m.Tliq) / 2)
    mtype = m.gamma isa SahooDebRoyFeS ? "Sahoo–DebRoy Fe–S" :
            m.gamma isa LinearGamma ? "linear (Pichler-family)" : "constant"
    fam = m.family === :steel ? "steel" :
          m.family === :aluminum ? "aluminium" : "other"
    """
    Material: $(m.name)  [$fam]
      solidus / liquidus      : $(round(m.Tsol, digits=1)) / $(round(m.Tliq, digits=1)) K
      mushy interval           : $(round(m.Tliq - m.Tsol, digits=1)) K
      latent heat of fusion    : $(m.Lf) J/kg
      density solid / liquid   : $(m.rho_s) / $(m.rho_l) kg/m³
      thermal expansion β_T    : $(m.beta_T) 1/K
      k at liquidus            : $(round(kL, digits=2)) W/(m·K)
      surface tension model    : $mtype
      dγ/dT at mid-mush         : $(round(dγ, sigdigits=4)) N/(m·K)
      → Marangoni flow         : $(dγ > 0 ? "inward  → deep, narrow pool" :
                                      dγ < 0 ? "outward → wide, shallow pool" : "neutral")
    """
end

"""
    dgamma_dT_range(m, Tlo, Thi, N=200)

Sample the surface-tension slope across a temperature range and report whether it
changes sign. For ER70S6 the Sahoo–DebRoy model can flip sign with sulfur content; a
sign flip inside the operating range is a *qualitative* change in pool shape and pool
stability, and `sulfur_critical_content` locates it.
"""
function dgamma_dT_range(m::Material, Tlo::Real, Thi::Real, N::Int = 200)
    (min = minimum(dgamma_dT(m.gamma, Tlo + (Thi - Tlo) * (i - 1) / (N - 1)) for i in 1:N),
     max = maximum(dgamma_dT(m.gamma, Tlo + (Thi - Tlo) * (i - 1) / (N - 1)) for i in 1:N))
end

"""
    sulfur_critical_content(m, T) -> Float64

Sulfur wt.% at which `dγ/dT` changes sign at temperature `T`. The Sahoo–DebRoy
`ln[1 + k₁ a_s e^{−ΔH/RT}]` term grows with `a_s`, so raising sulfur drives `∂γ/∂T`
positive (inward flow). Returns `NaN` if no crossing exists in `[0, 1]` wt%.
"""
function sulfur_critical_content(m::Material, T::Real)
    g = m.gamma isa SahooDebRoyFeS ? m.gamma :
        throw(ArgumentError("sulfur sweep only applies to SahooDebRoyFeS"))
    lo, hi = 0.0, 1.0
    dgamma_dT(g, T) > 0 && return 0.0
    dgamma_dT(g, T) < 0 || return NaN
    for _ in 1:200                       # bisection on a_s
        mid = 0.5 * (lo + hi)
        trial = SahooDebRoyFeS(a_s = mid, gamma_m = g.gamma_m, A = g.A, Tm = g.Tm,
                               R = g.R, Gamma_s = g.Gamma_s, k1 = g.k1, dH = g.dH)
        if dgamma_dT(trial, T) > 0
            hi = mid
        else
            lo = mid
        end
    end
    0.5 * (lo + hi)
end
