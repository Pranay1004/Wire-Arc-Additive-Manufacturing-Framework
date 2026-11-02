module WAAMFlow

"""
    WAAMFlow

A free-surface, multiphase finite-volume solver for long-term Wire Arc Additive
Manufacturing thin-wall deposition.

Reproduces and extends Zargari, Khajeh Mohammadilar & Zaleh (2025), *A long-term and
pragmatic numerical simulation of wire arc additively manufactured ER70S6 and ER316L
thin-wall via finite difference method*, Progress in Additive Manufacturing
10:11647–11663, [doi:10.1007/s40964-025-01307-x](https://doi.org/10.1007/s40964-025-01307-x).

See `docs/MASTER_PLAN.md` for the full engineering plan and
`docs/src/limitations.md` for what this model deliberately does **not** do.
"""

using LinearAlgebra
using SparseArrays
using Printf
using Statistics
using StaticArrays

export CartesianGrid, GridMetrics, uniform_grid, graded_axis, metrics
export face_closure_error, volume_identity_error, uniform_step_error, grid_summary
export divergence!
export slope_limiter, face_gradient, grad_axis!
export minmod, superbee, vanleer
export cell_to_face_distance
export VolumeField, SurfaceField, VectorField, cell_volume_sum, cell_mean, field_range
export PropCurve, Material, get_material, material_report, darcy_drag
export MATERIAL_FAMILIES, material_names
export ConstantGamma, LinearGamma, SahooDebRoyFeS, marangoni_source, dgamma_dT
export enthalpy, temperature, cp_effective, liquid_fraction, solid_fraction
export Cp_s_ref, Cp_l_ref, dgamma_dT_range, sulfur_critical_content
export darcy_coefficient, porosity_scale, latent_heat_rate, er70s6, er316l
export face_interp2, harmonic_mean, harmonic_face_coeff, laplacian_cell
export face_fluxes, face_fluxes_stretched, update_from_flux!, muscl_slope
export rusanov, limited_slopes, MAX_STABLE_COURANT
export update_from_flux_stretched!, limited_slopes_stretched
export SparseCSR, apply7!, poisson7!, to_sparse, poisson_diagonal
export multigrid_poisson!
export advect_vof!, compress!, vof_divergence!, total_volume, liquid_volume
export interface_cells, alpha_phase
export ProcessParameters, sigma_q, wire_feed_mass_rate, arc_power, droplet_heat
export EnergySplit, energy_budget, arc_flux!, arc_source!, arc_power_delivered
export droplet_sources!, surface_loss!, surface_loss_coeff
export EnergyWorkspace, solve_energy!, energy_residual, global_energy_budget
export max_temperature, min_temperature
export latent_heat_fraction
export TimestepController, timestep, wall_clock_hint
export cross_section, bead_geometry, thermal_profile, cooling_rate
export interpass_temperature, wall_height, effective_thickness, pool_volume
export RunConfig, SingleTrackResult, run_track
export FluidWorkspace, step_fluid!, simulate_track
export write_restart, read_restart, write_vtk
export MomentumWorkspace, PressureMode, PartialVoid, CSF, gradF, curvature!, smooth_fraction!
export surface_tension_pressure!, csf_force!, marangoni_faces!, solve_pressure!
export project_velocity!, darcy_and_buoyancy!, viscous_candidate!, max_speed
export apply_velocity_bc!, step_momentum!
export DepositionSchedule, DepositionState, begin_pass!, step_schedule!
export pass_length, total_time, arc_position, paper_cases, sagging_prediction
export rho, Cp, kcond, visc
export gui

include("mesh/grid.jl")
include("fields/fields.jl")
include("fields/interpolation.jl")
include("materials/properties.jl")
include("materials/alloys.jl")
include("physics/enthalpy.jl")
include("physics/advection.jl")
include("solvers/sparse.jl")
include("physics/vof.jl")
include("physics/sources.jl")
include("solvers/energy.jl")
include("solvers/timestep.jl")
include("diagnostics/bead.jl")
include("solvers/momentum.jl")
include("process/schedule.jl")
include("process/single_track.jl")
include("process/simulate.jl")
include("io/restart.jl")

"""
    gui() -> Makie.Figure

Interactive process cockpit: alloy, arc power, travel speed and track length
drive a live thermal single-track run with top-view and torch-plane section
rendering plus bead/thermal metrics. Provided by the `WAAMFlowGUIExt`
extension (loaded when `GLMakie` is available in the environment); without
GLMakie this is a bare function and calling it gives a MethodError. Launch with

    julia --project=gui -e 'using GLMakie, WAAMFlow; WAAMFlow.gui()'
"""
function gui end

"""
    write_vtk(path, g, U, F, T; t = 0.0, step = 0, p = nothing, extra_fields = Dict())

Export simulation fields to a VTK RectilinearGrid (.vtr) file for 3D inspection in ParaView.
Requires `WriteVTK` to be imported (`using WriteVTK`).
"""
function write_vtk end

end # module