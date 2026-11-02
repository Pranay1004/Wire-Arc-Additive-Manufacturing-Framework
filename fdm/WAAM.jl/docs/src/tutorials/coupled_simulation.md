# Tutorial 2: Coupled Multiphysics Simulation

This tutorial covers the operator-split multiphysics workflow in `WAAMFlow`: advancing Navier-Stokes fluid momentum, free-surface Volume-of-Fluid (VOF) advection, Marangoni thermocapillary stresses, and latent-heat enthalpy energy conservation in unified time steps.

## 1. Mathematical Architecture

At each time step $\Delta t$, the solver executes four sequential operations:

1. **Momentum Predictor & Poisson Projection**:
   $$\mathbf{u}^* = \mathbf{u}^n + \Delta t \left[ -\nabla \cdot (\mathbf{u} \otimes \mathbf{u}) + \nu \nabla^2 \mathbf{u} + \mathbf{g} + \mathbf{f}_{Darcy} + \mathbf{f}_{st} \right]$$
   $$\nabla \cdot \left( \frac{1}{\rho} \nabla p \right) = \frac{\nabla \cdot \mathbf{u}^*}{\Delta t}$$
   $$\mathbf{u}^{n+1} = \mathbf{u}^* - \frac{\Delta t}{\rho} \nabla p$$

2. **VOF Interface Advection & Geometric Compression**:
   $$\frac{\partial F}{\partial t} + \nabla \cdot (F \mathbf{u}) + \nabla \cdot \left[ \mathbf{u}_r F (1 - F) \right] = 0$$

3. **Volumetric & Surface Source Deposition**:
   * Moving surface arc flux: $q_{arc}(x, y)$
   * Droplet mass and enthalpy injection: $S_{mass}, S_{momentum}, S_{enthalpy}$
   * Radiation and convective heat loss: $q_{loss} = h_c (T - T_\infty) + \epsilon \sigma_{SB} (T^4 - T_\infty^4)$

4. **Implicit Enthalpy Energy Equation**:
   $$\rho \frac{\partial h}{\partial t} + \nabla \cdot (\rho \mathbf{u} h) = \nabla \cdot (k \nabla T) + S_{energy}$$

## 2. Julia Execution Example

```julia
using WAAMFlow

# 1. Allocate computational domain
n = 32
L = 0.015  # 15 mm cube
g = uniform_grid(n, n, n, L, L, L)
m = metrics(g)

# 2. Initialize fields
U = VectorField(g)
F = zeros(n, n, n)
F[:, :, 1:n÷2] .= 1.0  # Solid substrate in bottom half
T = fill(300.0, n, n, n)
Told = copy(T)

# 3. Setup workspace and material
fw = FluidWorkspace(g)
mat = get_material("ER316L")
p = ProcessParameters()
dt = 1.0e-4  # 0.1 ms time step

# 4. Integrate 100 coupled steps
torch_pos = (L / 2, L / 2)
for step in 1:100
    copyto!(Told, T)
    step_fluid!(
        fw, U, F, T, Told, mat, m, g, dt;
        p = p,
        torch = torch_pos,
        surface_tension = true,
        do_compress = true
    )
end

println("Coupled simulation completed successfully!")
```
