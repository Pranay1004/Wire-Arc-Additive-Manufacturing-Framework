#include "WAAMGoldakKernel.h"
#include "WAAMToolpathUO.h"

registerMooseObject("WAAMApp", WAAMGoldakKernel);

InputParameters
WAAMGoldakKernel::validParams()
{
  InputParameters params = ADKernelValue::validParams();
  params.addClassDescription(
      "Goldak double-ellipsoid arc source q(x,t) * psi * srcMask (FreeFEM parity)");
  params.addRequiredParam<UserObjectName>("toolpath_uo", "The WAAMToolpathUO source of q");
  params.addRequiredCoupledVar("psi_var", "Nodal activation field (P1 aux)");
  params.addRequiredCoupledVar("fa_var", "Elemental birth mask (P0 aux, majority)");
  params.addParam<bool>("use_masks",
                        true,
                        "Multiply by psi and srcMask (off = raw Goldak, for source checks)");
  return params;
}

WAAMGoldakKernel::WAAMGoldakKernel(const InputParameters & parameters)
  : ADKernelValue(parameters),
    _uo(getUserObject<WAAMToolpathUO>("toolpath_uo")),
    _psi(coupledValue("psi_var")),
    _fa(coupledValue("fa_var")),
    _use_masks(getParam<bool>("use_masks"))
{
}

ADReal
WAAMGoldakKernel::precomputeQpResidual()
{
  Real q = _uo.goldakQ(_q_point[_qp], _t);
  if (_use_masks)
    q *= _psi[_qp] * _fa[_qp];
  return -q;
}
