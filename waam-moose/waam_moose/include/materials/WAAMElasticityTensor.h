#pragma once

#include "ComputeElasticityTensorBase.h"

/**
 * WAAMElasticityTensor: Temperature-dependent, multi-zone isotropic elasticity
 * tensor with element birth activation masking and liquid slurry cutoff.
 *
 * Implements:
 * - Substrate & Deposit specific Young's moduli and Poisson ratios
 * - Metallurgical high-temperature thermal softening E(T)
 * - Liquid slurry modulus cutoff above solidus temperature T_solidus
 * - Quiet element birth stiffness masking (born_floor) for inactive void elements
 */
class WAAMElasticityTensor : public ComputeElasticityTensorBase
{
public:
  static InputParameters validParams();

  WAAMElasticityTensor(const InputParameters & parameters);

protected:
  virtual void computeQpElasticityTensor() override;

  const VariableValue & _temp;
  const VariableValue & _psi;
  const VariableValue & _fa;

  const Real _hz_base;
  const Real _E_base;
  const Real _E_dep;
  const Real _nu_base;
  const Real _nu_dep;
  const Real _tsol_base;
  const Real _tsol_dep;
  const Real _born_floor;
  const Real _slurry_factor;
};
