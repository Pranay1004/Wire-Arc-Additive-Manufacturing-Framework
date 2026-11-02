#include "WAAMThermalExpansionEigenstrain.h"

registerMooseObject("WAAMApp", WAAMThermalExpansionEigenstrain);

InputParameters
WAAMThermalExpansionEigenstrain::validParams()
{
  InputParameters params = ComputeThermalExpansionEigenstrainBase::validParams();
  params.addClassDescription(
      "WAAM thermal expansion eigenstrain with element birth masking and "
      "molten pool solidus strain cutoff.");

  params.addRequiredParam<Real>("thermal_expansion_coeff", "Thermal expansion coefficient [1/K]");
  params.addRequiredParam<Real>("T_solidus", "Solidus temperature [K] above which thermal strain is capped");
  params.addRequiredCoupledVar("fa_var", "Elemental birth mask (P0 aux, majority)");
  params.declareControllable("thermal_expansion_coeff");

  return params;
}

WAAMThermalExpansionEigenstrain::WAAMThermalExpansionEigenstrain(
    const InputParameters & parameters)
  : ComputeThermalExpansionEigenstrainBase(parameters),
    _alpha(getParam<Real>("thermal_expansion_coeff")),
    _T_solidus(getParam<Real>("T_solidus")),
    _fa(coupledValue("fa_var"))
{
}

ValueAndDerivative<false>
WAAMThermalExpansionEigenstrain::computeThermalStrain()
{
  const Real fa = _fa[_qp];
  if (fa < 0.5)
  {
    // Unborn element: zero thermal eigenstrain prevents spurious air deformation
    return ValueAndDerivative<false>(0.0, 0.0);
  }

  const auto & T_chain = _temperature[_qp]; // ChainedReal
  const Real T_val = T_chain.value();
  const Real T_sf = _stress_free_temperature[_qp];

  // Smooth C1 transition over a 50 K transition zone below solidus
  // to avoid discontinuous Jacobian derivatives during Newton iterations.
  const Real T_band = 50.0;
  const Real T_low = _T_solidus - T_band;

  if (T_val >= _T_solidus)
  {
    // Molten pool: strain locked at solidus contraction level with zero temperature derivative
    const Real eps_solidus = _alpha * (_T_solidus - T_sf - 0.5 * T_band);
    return ValueAndDerivative<false>(eps_solidus, 0.0);
  }
  else if (T_val <= T_low)
  {
    // Below transition zone: standard linear thermoelastic eigenstrain
    const Real eps = _alpha * (T_val - T_sf);
    return ValueAndDerivative<false>(eps, _alpha);
  }
  else
  {
    // Quadratic C1 spline transition where d(eps)/dT smoothly decreases from alpha to 0
    const Real s = (T_val - T_low) / T_band;
    const Real eps = _alpha * (T_low - T_sf) + _alpha * T_band * (s - 0.5 * s * s);
    const Real d_eps_dT = _alpha * (1.0 - s);
    return ValueAndDerivative<false>(eps, d_eps_dT);
  }
}
