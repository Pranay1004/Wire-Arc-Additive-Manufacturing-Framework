#include "WAAMLumpedHeatTimeDerivative.h"

#include "Assembly.h"
#include "MooseVariableFE.h"

#include "libmesh/quadrature.h"

registerMooseObject("WAAMApp", WAAMLumpedHeatTimeDerivative);

InputParameters
WAAMLumpedHeatTimeDerivative::validParams()
{
  InputParameters params = TimeKernel::validParams();
  params.addClassDescription(
      "Lump-mass heat capacity time derivative rho*cp*dT/dt (diagonal mass; "
      "eliminates the P1 moving-source under/overshoot of the consistent form)");
  params.addParam<MaterialPropertyName>("specific_heat",
                                        "specific_heat",
                                        "Property supplying cp [J/kg/K]");
  params.addParam<MaterialPropertyName>(
      "density_name", "density", "Property name of the density material property");
  return params;
}

WAAMLumpedHeatTimeDerivative::WAAMLumpedHeatTimeDerivative(const InputParameters & parameters)
  : TimeKernel(parameters),
    _density_name(getParam<MaterialPropertyName>("density_name")),
    _specific_heat_name(getParam<MaterialPropertyName>("specific_heat")),
    _rho(getMaterialPropertyByName<Real>(_density_name)),
    _cp(getMaterialPropertyByName<Real>(_specific_heat_name)),
    _u_dot_nodal(_var.dofValuesDot())
{
}

Real
WAAMLumpedHeatTimeDerivative::computeQpResidual()
{
  // Each node sees its own dT/dt (dofValuesDot at _i), i.e. the lumped
  // (row-summed) mass form: rho*cp*u_dot_i * test_i.
  return _test[_i][_qp] * _rho[_qp] * _cp[_qp] * _u_dot_nodal[_i];
}

Real
WAAMLumpedHeatTimeDerivative::computeQpJacobian()
{
  return _test[_i][_qp] * _rho[_qp] * _cp[_qp] * _du_dot_du[_qp];
}

void
WAAMLumpedHeatTimeDerivative::computeJacobian()
{
  // Diagonal-only assembly (matches MassLumpedTimeDerivative): fill _local_ke
  // (i,i) and discard the off-diagonal terms that the consistent form retains.
  prepareMatrixTag(_assembly, _var.number(), _var.number());
  for (_i = 0; _i < _test.size(); _i++)
    for (_qp = 0; _qp < _qrule->n_points(); _qp++)
      _local_ke(_i, _i) += _JxW[_qp] * _coord[_qp] * computeQpJacobian();
  accumulateTaggedLocalMatrix();
}
