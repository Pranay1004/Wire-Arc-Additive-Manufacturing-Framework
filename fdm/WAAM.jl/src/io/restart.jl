"""
Restart I/O: a dependency-free binary writer/reader for the full simulation state.

The point of a restart file is to be able to stop a 3400 s run and resume it later
without losing anything, so the format stores the three fields, the time and the step
number, and nothing else — no mesh, no material, all of which are reconstructed from the
`RunConfig` on load. A magic number and a version are written first so a corrupt or
mismatched file is rejected loudly rather than read as garbage.

The VTK writer lives in its own extension (`src/io/vtk.jl`, loaded only when the user
adds `WriteVTK`) so a headless install stays small; this file has no dependencies beyond
the standard library.
"""

"""
    write_restart(path, U, F, T, t, step) -> String

Write the full state to `path` and return the path. `U` is a `VectorField`, `F` the
volume fraction and `T` the temperature.
"""
function write_restart(path::AbstractString, U::VectorField, F::AbstractArray{<:Real,3},
                       T::AbstractArray{<:Real,3}, t::Real, step::Integer)
    open(path, "w") do io
        write(io, "WAAMRT")                 # magic
        write(io, Int32(1))                 # format version
        write(io, Float64(t))
        write(io, Int64(step))
        nx, ny, nz = size(F)
        write(io, Int32(nx), Int32(ny), Int32(nz))
        write(io, Float64.(F))
        write(io, Float64.(T))
        write(io, Float64.(U.u))
        write(io, Float64.(U.v))
        write(io, Float64.(U.w))
    end
    path
end

"""
    read_restart(path, g) -> (U, F, T, t, step)

Read a restart file written by `write_restart`, rebuilding the `VectorField` on the
supplied `g::CartesianGrid` (the mesh itself is not stored — it comes from the
`RunConfig` used to restart). Throws `ArgumentError` if the magic, the version, or the
stored dimensions do not match `g`, so a mismatched file is rejected loudly rather than
silently producing a nonsense field.
"""
function read_restart(path::AbstractString, g::CartesianGrid)
    isfile(path) || throw(ArgumentError("no restart file at $path"))
    open(path, "r") do io
        magic = read(io, 6)
        m = String(magic)
        m == "WAAMRT" || throw(ArgumentError(
            "not a WAAM restart file at $path (magic = $(repr(m))"))
        ver = read(io, Int32)
        ver == 1 || throw(ArgumentError(
            "unsupported restart version $ver at $path"))
        t = read(io, Float64)
        step = read(io, Int64)
        nx = Int(read(io, Int32)); ny = Int(read(io, Int32)); nz = Int(read(io, Int32))
        (nx, ny, nz) == (g.nx, g.ny, g.nz) || throw(ArgumentError(
            "restart file at $path has $(nx)x$(ny)x$(nz) cells but grid has $(g.nx)x$(g.ny)x$(g.nz)"))
        F = Array{Float64,3}(undef, nx, ny, nz)
        T = Array{Float64,3}(undef, nx, ny, nz)
        read!(io, F); read!(io, T)
        u = Array{Float64,3}(undef, nx + 1, ny, nz)
        v = Array{Float64,3}(undef, nx, ny + 1, nz)
        w = Array{Float64,3}(undef, nx, ny, nz + 1)
        read!(io, u); read!(io, v); read!(io, w)
        (VectorField(u, v, w, g), F, T, t, step)
    end
end
