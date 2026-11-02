#include "WAAMPlasticityStressUpdate.h"
#include <cmath>
#include <algorithm>

registerMooseObject("WAAMApp", WAAMPlasticityStressUpdate);

InputParameters
WAAMPlasticityStressUpdate::validParams()
{
  InputParameters params = IsotropicPlasticityStressUpdate::validParams();
  params.addClassDescription(
      "J2 radial-return plasticity with high-temperature thermal annealing, "
      "ultrasonic acoustic softening, and element birth regularization.");

  params.addRequiredCoupledVar("fa_var", "Elemental birth mask (P0 aux, majority)");
  params.addParam<Real>("T_solidus", 1450.0, "Solidus temperature [C] above which plastic strain is annealed");
  params.addCoupledVar("softening", "Coupled ultrasonic acoustic softening factor (optional)");

  return params;
}

WAAMPlasticityStressUpdate::WAAMPlasticityStressUpdate(const InputParameters & parameters)
  : IsotropicPlasticityStressUpdate(parameters),
    _yield_stress_base(getParam<Real>("yield_stress")),
    _T_solidus(getParam<Real>("T_solidus")),
    _fa(coupledValue("fa_var")),
    _softening(isCoupled("softening") ? &coupledValue("softening") : nullptr),
    _has_softening(isCoupled("softening"))
{
}

void
WAAMPlasticityStressUpdate::computeYieldStress(
    const GenericRankFourTensor<false> & /*elasticity_tensor*/)
{
  const Real T = _temperature[_qp];
  const Real fa = _fa[_qp];

  if (fa < 0.5)
  {
    _yield_stress = 1.0e10; // Unborn elements stay elastic with negligible stiffness
    return;
  }

  // Consistent ambient reference in Celsius
  const Real T_ref = 25.0;
  const Real delta_T = std::max(100.0, _T_solidus - T_ref);
  const Real theta = std::max(0.0, std::min(1.0, (T - T_ref) / delta_T));

  // Smooth C1 softening: (1-theta)^2 down to slurry floor factor of 0.005
  const Real floor_factor = 0.005;
  Real T_fact = floor_factor + (1.0 - floor_factor) * (1.0 - theta) * (1.0 - theta);
  if (T >= _T_solidus)
    T_fact = floor_factor;

  Real sy = _yield_stress_base * T_fact;

  // Ultrasonic acoustic softening coupling
  if (_has_softening && _softening)
  {
    const Real s_acou = std::max(0.0, std::min(0.8, (*_softening)[_qp]));
    sy *= (1.0 - s_acou);
  }

  _yield_stress = std::max(1.0e5, sy);
}

void
WAAMPlasticityStressUpdate::computeStressInitialize(
    const Real & effective_trial_stress, const RankFourTensor & elasticity_tensor)
{
  IsotropicPlasticityStressUpdate::computeStressInitialize(effective_trial_stress, elasticity_tensor);

  const Real fa = _fa[_qp];
  if (fa < 0.5)
  {
    _plastic_strain[_qp].zero();
    _hardening_variable[_qp] = 0.0;
  }
}

void
WAAMPlasticityStressUpdate::computeStressFinalize(
    const RankTwoTensor & plastic_strain_increment)
{
  const Real fa = _fa[_qp];
  const Real T = _temperature[_qp];

  if (fa < 0.5 || T >= _T_solidus)
  {
    _plastic_strain[_qp].zero();
    _hardening_variable[_qp] = 0.0;
  }
  else
  {
    IsotropicPlasticityStressUpdate::computeStressFinalize(plastic_strain_increment);
  }
}

void
WAAMPlasticityStressUpdate::propagateQpStatefulProperties()
{
  const Real fa = _fa[_qp];
  const Real T = _temperature[_qp];

  if (fa < 0.5 || T >= _T_solidus)
  {
    _plastic_strain[_qp].zero();
    _hardening_variable[_qp] = 0.0;
    RadialReturnStressUpdateTempl<false>::propagateQpStatefulPropertiesRadialReturn();
  }
  else
  {
    IsotropicPlasticityStressUpdate::propagateQpStatefulProperties();
  }
}
