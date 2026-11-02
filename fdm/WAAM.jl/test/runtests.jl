using Test, WAAMFlow

@testset "WAAMFlow" begin
    include("verify_core.jl")
    include("verify_energy.jl")
    include("verify_momentum.jl")
    include("verify_coupled.jl")
    include("verify_io.jl")
    include("verify_poisson.jl")
    include("verify_vof.jl")
    include("verify_rb.jl")
    include("verify_convergence.jl")
end
