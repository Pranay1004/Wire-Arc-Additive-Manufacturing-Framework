module WAAMFlowVTKExt

using WAAMFlow
using WriteVTK

"""
    write_vtk(path, g, U, F, T; t = 0.0, step = 0, p = nothing, extra_fields = Dict()) -> String

Write simulation fields to a VTK RectilinearGrid (.vtr) file readable by ParaView.
`path` should be provided without file extension (WriteVTK appends `.vtr`).
"""
function WAAMFlow.write_vtk(path::AbstractString, g::CartesianGrid,
                            U::Union{VectorField, Nothing},
                            F::AbstractArray{<:Real,3},
                            T::AbstractArray{<:Real,3};
                            t::Real = 0.0, step::Integer = 0,
                            p::Union{AbstractArray{<:Real,3}, Nothing} = nothing,
                            extra_fields::Dict{String, <:AbstractArray{<:Real,3}} = Dict{String, Array{Float64,3}}())
    # CartesianGrid coordinates define cell vertices along each axis:
    # g.x: (nx + 1), g.y: (ny + 1), g.z: (nz + 1)
    vtk = vtk_grid(path, g.x, g.y, g.z)
    try
        vtk["PhaseFraction", VTKCellData()] = Float64.(F)
        vtk["Temperature", VTKCellData()] = Float64.(T)
        if U !== nothing
            # Staggered face velocities interpolated to cell-centres
            u_c = 0.5 .* (U.u[1:end-1, :, :] .+ U.u[2:end, :, :])
            v_c = 0.5 .* (U.v[:, 1:end-1, :] .+ U.v[:, 2:end, :])
            w_c = 0.5 .* (U.w[:, :, 1:end-1] .+ U.w[:, :, 2:end])
            vtk["Velocity", VTKCellData()] = (Float64.(u_c), Float64.(v_c), Float64.(w_c))
            vtk["Speed", VTKCellData()] = sqrt.(u_c.^2 .+ v_c.^2 .+ w_c.^2)
        end
        if p !== nothing
            vtk["Pressure", VTKCellData()] = Float64.(p)
        end
        for (name, arr) in extra_fields
            vtk[string(name), VTKCellData()] = Float64.(arr)
        end
        vtk["Time"] = Float64(t)
        vtk["Step"] = Int64(step)
    finally
        vtk_save(vtk)
    end
    return path * ".vtr"
end

end # module
