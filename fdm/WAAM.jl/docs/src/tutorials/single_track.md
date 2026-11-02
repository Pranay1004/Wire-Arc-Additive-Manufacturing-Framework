# Tutorial 1: Single-Track WAAM Deposition

This tutorial guides you through setting up, running, and analyzing a single-track Wire Arc Additive Manufacturing (WAAM) pass using `WAAMFlow`.

## 1. Physical Configuration

We model a moving gas metal arc welding (GMAW) torch depositing an 8 mm bead along the x-axis on an initial substrate at 298 K:

* **Material**: `ER70S6` (mild steel) or `ER316L` (austenitic stainless steel)
* **Arc Current**: 125 A
* **Arc Voltage**: 19.6 V
* **Travel Speed**: 2.833 mm/s (0.17 m/min)
* **Net Arc Power**: 1472 W ($\eta = 0.60$)
* **Mesh Resolution**: Graded Cartesian grid with $\Delta x_{fine} = 0.4\text{ mm}$ along the melt path and $\Delta x_{coarse} = 1.6\text{ mm}$ in the far field.

## 2. Julia Script Execution

```julia
using WAAMFlow
using Printf

# Configure single track process
cfg = RunConfig(
    material = "ER70S6",          # Alloy selection: "ER70S6" or "ER316L"
    Lx = 0.020,                   # Substrate length: 20 mm
    Ly = 0.004,                   # Half-symmetry width: 4 mm
    Lz = 0.008,                   # Height: 8 mm
    h_fine = 0.4e-3,              # Melt-pool zone cell width: 0.4 mm
    h_coarse = 1.6e-3,            # Far-field cell width: 1.6 mm
    ny = 10,                      # Half-width cells
    travel_speed = 0.0028333,     # 2.833 mm/s
    track_length = 0.008,         # 8 mm pass
    energy_mode = :paper,         # Mode A: 1104 W surface + 368 W droplets
    verbose = true
)

# Run the thermal and phase-change solve
result = run_track(cfg)

# Print summary diagnostics
@printf("Simulation Summary:\n")
@printf("  • Peak Temperature : %.1f K\n", result.peak_T)
@printf("  • Bead Width       : %.2f mm\n", result.width * 1e3)
@printf("  • Penetration Depth: %.2f mm\n", result.penetration * 1e3)
@printf("  • Energy Injected  : %.1f J\n", result.energy_in)
@printf("  • Energy Residual  : %.3e J (Relative: %.2e)\n", 
        result.energy_residual, result.energy_residual / result.energy_in)
```

## 3. Interpreting the Energy Audit

Every `run_track` step continuously tracks the global energy ledger:
$$\Delta E_{stored} = E_{in} - E_{loss} - \text{Residual}$$

The energy conservation residual is strictly verified to be $< 10^{-8}\text{ J}$ (relative error $< 10^{-11}$), guaranteeing zero unphysical heat loss or artificial latent-heat creation during solid-liquid phase transitions.
