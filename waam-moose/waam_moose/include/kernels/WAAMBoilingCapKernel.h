#pragma once

#include "Kernel.h"

#include <utility> // std::pair for smoothGate()

/// FreeFEM-parity evaporation (boiling) cap as a smooth volumetric sink.
///
/// FreeFEM's generated program clips the nodal field at Tboil (2862 C) AFTER
/// every solve, so T can never exceed Tboil and every joule the torch injects
/// above that cap is DELETED and audited as 'boiling_cap_removed' (EcapJ). A
/// naive MOOSE translation (zeroing the Goldak source inside the kernel where
/// T >= Tboil) is a T-discontinuous residual: when the melt pool rides the
/// 2862 C plane the residual flips between q and 0 across neighbouring Newton
/// iterations and SNES's line search diverges (measured DIVERGED_LINE_SEARCH
/// death spiral, dt bottoming at 1e-12). This kernel instead implements the
/// physics the FreeFEM clip realises as an infinite-gain relaxation sink that
/// pins the pool at ~Tboil and exports the removed power:
///
///     Q(x,t) = rho * cp * rate * r(T) * (T - Tboil)      [W/m^3]
///     r(T)   = smoothstep((T - (Tboil - width)) / width)  in (0, 1), C1 in T
///
/// so Newton / line search stay healthy (no kinks, no flip planes). The
/// companion WAAMFreeFEMClip corrector performs the exact post-solve nodal
/// [Tamb, Tboil] clip for bit-for-bit parity; this kernel just keeps the
/// in-solve residual sane so Newton converges on the hot front.
/// WAAMCapPower integrates the removed power for the P4 ledger term
/// boiling_cap_removed, matching FreeFEM's EcapJ.
class WAAMBoilingCapKernel : public Kernel
{
public:
  static InputParameters validParams();

  WAAMBoilingCapKernel(const InputParameters & parameters);

  /// Shared smoothstep gate: returns (r, dr/dT) for the given T/edge/width.
  /// Public+static so WAAMCapPower reproduces the kernel's gate exactly
  /// (single source of truth for the audit).
  static std::pair<Real, Real> smoothGate(Real T, Real edge, Real width);

protected:
  virtual Real computeQpResidual() override;
  virtual Real computeQpJacobian() override;
  virtual Real computeQpOffDiagJacobian(unsigned int /*jvar*/) override { return 0.0; }

  const MaterialPropertyName _density_name;
  const MaterialPropertyName _specific_heat_name;
  const MaterialProperty<Real> & _rho;
  const MaterialProperty<Real> & _cp;
  const Real _t_boil;
  const Real _rate;
  const Real _width;
};
