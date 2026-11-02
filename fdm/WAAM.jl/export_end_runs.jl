# Export ParaView .vtr results for ER70S6 and ER316L single-track WAAM runs
using WAAMFlow
using WriteVTK
using Printf

const OUTDIR = joinpath(@__DIR__, "validation_output")
mkpath(OUTDIR)

println("=" ^ 78)
println("Running WAAMFlow single-track end runs and exporting ParaView .vtr fields")
println("=" ^ 78)

for alloy in ["ER70S6", "ER316L"]
    cfg = RunConfig(material = alloy, verbose = false)
    println("\nStarting ", alloy, " simulation...")
    t0 = time()
    res = run_track(cfg)
    wall = time() - t0

    # Build CartesianGrid matching run_track
    xf = graded_axis(0.0, cfg.Lx, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
    zf = graded_axis(0.0, cfg.Lz, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
    yf = collect(range(0.0, cfg.Ly; length = cfg.ny))
    g = CartesianGrid(xf, yf, zf)
    m = metrics(g)
    mat = get_material(alloy)

    # Compute liquid fraction and solid fraction fields
    nx, ny, nz = g.nx, g.ny, g.nz
    F_liquid = zeros(nx, ny, nz)
    for k in 1:nz, j in 1:ny, i in 1:nx
        F_liquid[i, j, k] = liquid_fraction(mat, res.T[i, j, k])
    end
    U = VectorField(g)

    vtr_name = joinpath(OUTDIR, "waam_" * lowercase(alloy) * "_end_run")
    outpath = write_vtk(vtr_name, g, U, F_liquid, res.T;
                        t = res.sim_time, step = res.steps,
                        extra_fields = Dict("MoltenPhase" => F_liquid))

    @printf("  • Alloy           : %s\n", alloy)
    @printf("  • Wall Time       : %.2f s (%.1f min)\n", wall, wall / 60.0)
    @printf("  • Steps           : %d\n", res.steps)
    @printf("  • Peak Temperature: %.1f K\n", res.peak_T)
    @printf("  • Bead Width      : %.2f mm\n", res.width * 1e3)
    @printf("  • Penetration     : %.3f mm\n", res.penetration * 1e3)
    @printf("  • Energy Injected : %.1f J\n", res.energy_in)
    @printf("  • Energy Residual : %.3e J (rel: %.2e)\n", res.energy_residual, res.energy_residual / res.energy_in)
    @printf("  • ParaView Output : %s\n", outpath)
end

println("\nAll ParaView exports successfully generated.")
