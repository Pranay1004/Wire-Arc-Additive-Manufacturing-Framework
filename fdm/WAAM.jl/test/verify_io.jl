using Test, WAAMFlow

# ===========================================================================
# Restart I/O — binary round-trip
#
#     A restart file exists so a long run can be stopped and resumed without
#     losing anything. The only way to trust that is to write a known state,
#     read it back, and require bit-equality — plus require that a corrupt or
#     wrong-size file is rejected loudly rather than read as garbage.
# ===========================================================================

@testset "Restart I/O roundtrip" begin
    g = uniform_grid(6, 5, 4, 1.0, 2.0, 3.0)
    U = VectorField(g)
    U.u .= 0.5; U.v .= -0.25; U.w .= 0.125
    F = [i / 10 + j / 100 + k / 1000 for i in 1:6, j in 1:5, k in 1:4]
    T = [300.0 + 10i + 100j for i in 1:6, j in 1:5, k in 1:4]

    path = joinpath(mktempdir(), "state.rt")
    write_restart(path, U, F, T, 1.5, 42)

    U2, F2, T2, t, step = read_restart(path, g)
    @test t == 1.5
    @test step == 42
    @test F2 === F || F2 == F
    @test T2 == T
    @test U2.u == U.u && U2.v == U.v && U2.w == U.w
end

@testset "Restart I/O rejects bad input" begin
    g = uniform_grid(4, 4, 4, 1.0, 1.0, 1.0)
    @test_throws ArgumentError read_restart(joinpath(mktempdir(), "nope.rt"), g)

    bad = joinpath(mktempdir(), "bad.rt")
    write(bad, b"NOPE\x00\x00")   # wrong magic
    @test_throws ArgumentError read_restart(bad, g)

    # valid magic, wrong dimensions for the supplied grid
    U = VectorField(uniform_grid(8, 8, 8, 1.0, 1.0, 1.0))
    small = joinpath(mktempdir(), "small.rt")
    write_restart(small, U, fill(0.0, 8, 8, 8), fill(0.0, 8, 8, 8), 0.0, 0)
    @test_throws ArgumentError read_restart(small, g)
end

@testset "VTK Extension interface" begin
    g = uniform_grid(4, 4, 4, 1.0, 1.0, 1.0)
    U = VectorField(g)
    F = fill(0.5, 4, 4, 4)
    T = fill(300.0, 4, 4, 4)
    # Without WriteVTK loaded in the standard test depot, write_vtk has no matching method
    @test_throws MethodError write_vtk("dummy", g, U, F, T)
end
