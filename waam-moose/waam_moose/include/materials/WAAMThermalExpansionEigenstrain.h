#pragma once

#include "ComputeThermalExpansionEigenstrainBase.h"

/**
 * WAAMThermalExpansionEigenstrain: Thermal expansion eigenstrain with
 * element birth masking and solidus temperature strain cutoff.
 *
 * Physically, thermal contraction strains only accumulate below the solidus
 * (or coherency) temperature T_solidus. Above T_solidus, the alloy is liquid
 * or mushy slurry, so fluid back-feeding accommodates volume changes without
 * generating macroscopic elastic-plastic thermal stress.
 */
class WAAMThermalExpansionEigenstrain : public ComputeThermalExpansionEigenstrainBase
{
public:
  static InputParameters validParams();

  WAAMThermalExpansionEigenstrain(const InputParameters & parameters);

protected:
  virtual ValueAndDerivative<false> computeThermalStrain() override;

  const Real _alpha;
  const Real _T_solidus;
  const VariableValue & _fa;
};
