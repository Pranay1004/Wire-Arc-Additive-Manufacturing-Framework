#pragma once

#include "AuxKernel.h"

/// Writes the WAAMToolpathUO activation ledger into an auxiliary variable:
///  * nodal auxiliary variable (LAGRANGE)      -> per-node psi (FreeFEM psiActive)
///  * elemental auxiliary variable (CONSTANT)  -> per-element birth mask
///    (majority vote of the nodes / faCumulative)
class WAAMActivationAux : public AuxKernel
{
public:
  static InputParameters validParams();

  WAAMActivationAux(const InputParameters & parameters);

protected:
  virtual Real computeValue() override;

  const UserObject & _uo;
};
