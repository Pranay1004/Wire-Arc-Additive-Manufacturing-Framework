#include "WAAMSourcePower.h"
#include "WAAMToolpathUO.h"

registerMooseObject("WAAMApp", WAAMSourcePower);

InputParameters
WAAMSourcePower::validParams()
{
  InputParameters params = ElementIntegralPostprocessor::validParams();
  params.addClassDescription(
      "Instantaneous masked arc power integral [W] (q * psi * srcMask)");
  params.addRequiredParam<UserObjectName>("toolpath_uo", "The WAAMToolpathUO source of q");
  params.addRequiredCoupledVar("psi_var", "Nodal activation field (P1 aux)");
  params.addRequiredCoupledVar("fa_var", "Elemental birth mask (P0 aux, majority)");
  params.addParam<bool>("use_masks", true, "Multiply by psi and srcMask");
  return params;
}

WAAMSourcePower::WAAMSourcePower(const InputParameters & parameters)
  : ElementIntegralPostprocessor(parameters),
    _uo(getUserObject<WAAMToolpathUO>("toolpath_uo")),
    _psi(coupledValue("psi_var")),
    _fa(coupledValue("fa_var")),
    _use_masks(getParam<bool>("use_masks"))
{
}

Real
WAAMSourcePower::computeQpIntegral()
{
  Real q = _uo.goldakQ(_q_point[_qp], _t);
  if (_use_masks)
    q *= _psi[_qp] * _fa[_qp];
  return q;
}
