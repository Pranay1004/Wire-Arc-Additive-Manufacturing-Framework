# V23 helper — runs one fixed coupled configuration in a fresh process and prints a
# fingerprint of the final state. Invoked by test/verify_coupled.jl with different
# `-t` values; the output must be identical for every thread count.
using WAAMFlow, Printf

Tv = [200.0, 3000.0]
c = PropCurve(Tv, fill(1000.0, 2))
k = PropCurve(Tv, fill(30.0, 2))
μ = PropCurve(Tv, fill(0.01, 2))
mat = Material(name = "ReproRef", Tsol = 1700.0, Tliq = 1701.0, Lf = 272000.0,
               rho_s = 7850.0, rho_l = 6980.0, Cp_s = c, Cp_l = c,
               k_s = k, k_l = k, mu_l = μ, beta_T = 1.0e-5,
               gamma = ConstantGamma(1.2))
n = 10
L = 0.01
g = CartesianGrid(collect(range(0.0, L; length = n + 1)),
                  collect(range(0.0, L; length = n + 1)),
                  collect(range(0.0, L; length = n + 1)))
m = metrics(g)
F = fill(0.0, n, n, n)
R = 0.002
cx = cy = cz = L / 2
for k in 1:n, j in 1:n, i in 1:n
    d = sqrt((m.xc[i] - cx)^2 + (m.yc[j] - cy)^2 + (m.zc[k] - cz)^2)
    F[i, j, k] = clamp((R + 2 * L / n - d) / (4 * L / n), 0.0, 1.0)
end
T = fill(1800.0, n, n, n)
Told = copy(T)
U = VectorField(g)
fw = FluidWorkspace(g)
p = ProcessParameters()
dt = 1.0e-4
for _ in 1:60
    copyto!(Told, T)
    step_fluid!(fw, U, F, T, Told, mat, m, g, dt; p = p, torch = (L / 2, L / 2),
                do_compress = false)
end
@printf("fingerprint %.17e %.17e %.17e %.17e %.17e\n",
        sum(F), sum(abs, F), sum(T), sum(abs, U.w), sum(abs2, U.w))
