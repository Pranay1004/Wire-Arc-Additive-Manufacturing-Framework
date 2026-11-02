#pragma once

#include "IsotropicPlasticityStressUpdate.h"

/**
 * WAAMPlasticityStressUpdate: J2 radial-return plasticity with high-temperature
 * thermal annealing (plastic memory loss upon melting), temperature-dependent
 * flow softening, ultrasonic acoustic softening coupling, and element birth
 * regularization.
 */
class WAAMPlasticityStressUpdate : public IsotropicPlasticityStressUpdate
{
public:
  static InputParameters validParams();

  WAAMPlasticityStressUpdate(const InputParameters & parameters);

  virtual void computeYieldStress(const GenericRankFourTensor<false> & elasticity_tensor) override;
  virtual void computeStressInitialize(const Real & effective_trial_stress,
                                       const RankFourTensor & elasticity_tensor) override;
  virtual void computeStressFinalize(const RankTwoTensor & plastic_strain_increment) override;

protected:
  virtual void propagateQpStatefulProperties() override;

  const Real _yield_stress_base;
  const Real _T_solidus;
  const VariableValue & _fa;
  const VariableValue * const _softening;
  const bool _has_softening;
};
