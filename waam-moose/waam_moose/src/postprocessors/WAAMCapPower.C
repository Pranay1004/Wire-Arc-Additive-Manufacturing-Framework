#include "WAAMCapPower.h"
#include "WAAMBoilingCapKernel.h"

#include "MaterialProperty.h"

#include <algorithm> // std::max

registerMooseObject("WAAMApp", WAAMCapPower);

InputParameters
WAAMCapPower::validParams()
{
  InputParameters params = ElementIntegralPostprocessor::validParams();
  params.addClassDescription("Removed power of the evaporation cap [W] "
                             "(FreeFEM EcapJ ledger counterpart)");
  params.addRequiredCoupledVar("temperature", "Temperature variable [C]");
  params.addParam<MaterialPropertyName>("density_name", "density", "rho [kg/m^3] property");
  params.addParam<MaterialPropertyName>(
      "specific_heat_name", "specific_heat", "cp [J/kg/K] property");
  params.addRequiredParam<Real>("t_boil", "Boiling / vaporization cap [C]");
  params.addParam<Real>("rate", 3.0e5, "Relaxation gain [1/s] (must match WAAMBoilingCapKernel)");
  params.addParam<Real>("width", 25.0, "Smoothstep width [C] (must match WAAMBoilingCapKernel)");
  return params;
}

WAAMCapPower::WAAMCapPower(const InputParameters & parameters)
  : ElementIntegralPostprocessor(parameters),
    _temp(coupledValue("temperature")),
    _rho(getMaterialPropertyByName<Real>(getParam<MaterialPropertyName>("density_name"))),
    _cp(getMaterialPropertyByName<Real>(getParam<MaterialPropertyName>("specific_heat_name"))),
    _t_boil(getParam<Real>("t_boil")),
    _rate(getParam<Real>("rate")),
    _width(getParam<Real>("width"))
{
}

Real
WAAMCapPower::computeQpIntegral()
{
  const Real T = _temp[_qp];
  const auto [r, dr] = WAAMBoilingCapKernel::smoothGate(T, _t_boil, _width);
  return _rho[_qp] * _cp[_qp] * _rate * r * std::max(T - _t_boil, 0.0);
}
