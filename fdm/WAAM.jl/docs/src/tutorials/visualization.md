# Tutorial 3: Visualization & Interactive Cockpit

This tutorial details two visualization modes available in `WAAMFlow`:
1. Exporting 3D rectilinear mesh fields (`.vtr`) for ParaView.
2. Launching the real-time browser cockpit.

## 1. Exporting to ParaView (`WriteVTK.jl`)

To export simulation state snapshots to ParaView `.vtr` files:

```julia
using WAAMFlow
using WriteVTK

# Generate grid and fields
g = uniform_grid(32, 32, 32, 0.01, 0.01, 0.01)
U = VectorField(g)
F = fill(1.0, 32, 32, 32)
T = fill(1800.0, 32, 32, 32)

# Write to ParaView file (creates "waam_step_100.vtr")
write_vtk("waam_step_100", g, U, F, T; t = 0.05, step = 100)
```

In ParaView:
1. Open `waam_step_100.vtr`.
2. Apply the **Clip** or **Slice** filter to inspect internal temperature contours.
3. Apply the **Contour** filter on `PhaseFraction = 0.5` to visualize the 3D weld bead surface.
4. Apply the **Glyph** filter to visualize flow recirculation velocity vectors ($\mathbf{u}$).

---

## 2. Real-Time Interactive Browser Cockpit

`WAAMFlow` includes a zero-dependency WebSocket streaming server that visualizes simulations live in your browser:

### Launch Instructions

Start Julia with at least 2 threads:

```bash
cd fdm/WAAM.jl
julia -t 2 --project=gui -e 'using GLMakie, WAAMFlow; WAAMFlow.gui()'
```

Alternatively, launch the lightweight web dashboard:

```bash
julia -t 2 --project=. -e '
    using WAAMFlow
    # Start live single track with streaming callback
    run_track(RunConfig(); on_snapshot = snap -> println("Time: ", snap.t, " s, Peak: ", snap.peak, " K"))
'
```
