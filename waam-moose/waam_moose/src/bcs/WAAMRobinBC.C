#include "WAAMRobinBC.h"

registerMooseObject("WAAMApp", WAAMRobinBC);

InputParameters
WAAMRobinBC::validParams()
{
  InputParameters params = IntegratedBC::validParams();
  params.addClassDescription(
      "Activation-weighted convection + linearized radiation Robin BC (FreeFEM parity)");
  params.addRequiredCoupledVar("psi_var", "Nodal activation field (P1 aux)");
  params.addRequiredParam<Real>("h", "Convection coefficient [W/m^2/K]");
  params.addRequiredParam<Real>("T_ambient", "Ambient temperature [K or C, same numeric frame]");
  params.addParam<Real>("radiation",
                        0.,
                        "Emissivity * sigma [W/m^2/K^4]; 0 disables radiation (bottom face)");
  return params;
}

WAAMRobinBC::WAAMRobinBC(const InputParameters & parameters)
  : IntegratedBC(parameters),
    _psi(coupledValue("psi_var")),
    _h(getParam<Real>("h")),
    _t_ambient(getParam<Real>("T_ambient")),
    _radiation(getParam<Real>("radiation"))
{
}

Real
WAAMRobinBC::computeQpResidual()
{
  const Real T = _u[_qp];
  const Real Ta = _t_ambient;
  // (T^4 - Ta^4) written in the frozen-coefficient factored form.
  const Real rad_flux = _radiation * (T + Ta) * (T * T + Ta * Ta) * (T - Ta);
  return _test[_i][_qp] * _psi[_qp] * (_h * (T - Ta) + rad_flux);
}

Real
WAAMRobinBC::computeQpJacobian()
{
  const Real T = _u[_qp];
  const Real Ta = _t_ambient;
  const Real frozen_coef = _h + _radiation * (T + Ta) * (T * T + Ta * Ta);
  return _test[_i][_qp] * _phi[_j][_qp] * _psi[_qp] * frozen_coef;
}
