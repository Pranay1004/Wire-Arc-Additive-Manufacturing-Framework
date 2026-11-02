#pragma once

#include "ElementIntegralPostprocessor.h"

class WAAMToolpathUO;

/// Instantaneous masked arc power ∫ q(x,t) * psi(x,t) * srcMask(e,t) dV [W].
///
/// This is the unmasked-quadrature measure of the injected power; the 1D
/// coupling to the per-layer arc schedule (NweldSteps dt) lives in
/// WAAMEnergyAuditUO.  Use `use_masks = false` for the raw Goldak power.
class WAAMSourcePower : public ElementIntegralPostprocessor
{
public:
  static InputParameters validParams();

  WAAMSourcePower(const InputParameters & parameters);

protected:
  virtual Real computeQpIntegral() override;

  const WAAMToolpathUO & _uo;
  const VariableValue & _psi;
  const VariableValue & _fa;
  const bool _use_masks;
};
