#pragma once

#include "ADKernelValue.h"

class WAAMToolpathUO;

/// Volumetric arc heat source: q(x, t) * psi(x, t) * srcMask(e, t).
///
/// q is the FreeFEM-parity Goldak double-ellipsoid power density from
/// WAAMToolpathUO (W/m^3, arc-state gated, tanh front/rear split along +/-x by
/// layer parity).  psi / srcMask come from the activation aux fields
/// (WAAMActivationAux at 'initial timestep_begin', so the gate of step n is
/// visible to step n's own assembly, exactly like the FreeFEM loop).
class WAAMGoldakKernel : public ADKernelValue
{
public:
  static InputParameters validParams();

  WAAMGoldakKernel(const InputParameters & parameters);

protected:
  virtual ADReal precomputeQpResidual() override;

  const WAAMToolpathUO & _uo;
  const VariableValue & _psi;
  const VariableValue & _fa;
  const bool _use_masks;
};
