#pragma once

#include "ElementIntegralPostprocessor.h"

/// Instantaneous removed power of the evaporation cap [W].
///
/// Counterpart of WAAMBoilingCapKernel for the energy ledger: integrates
///     Q_removed(W/m^3) = rho * cp * rate * r(T) * max(T - Tboil, 0)
/// over the domain each step so the P4 audit module can fold
/// 'boiling_cap_removed' into solver_results.json with the same semantics as
/// FreeFEM's EcapJ (energy DELETED by the Tboil clip, never re-injected).
/// The kernel residual itself also relaxes from the Tboil - width shoulder
/// (the smoothstep gate is two-sided there); for the audit only the
/// above-cap part is counted, matching FreeFEM's one-sided clip.
class WAAMCapPower : public ElementIntegralPostprocessor
{
public:
  static InputParameters validParams();

  WAAMCapPower(const InputParameters & parameters);

protected:
  virtual Real computeQpIntegral() override;

  const VariableValue & _temp;
  const MaterialProperty<Real> & _rho;
  const MaterialProperty<Real> & _cp;
  const Real _t_boil;
  const Real _rate;
  const Real _width;
};
