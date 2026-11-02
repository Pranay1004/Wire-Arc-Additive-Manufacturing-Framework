#include "WAAMActivationAux.h"
#include "WAAMToolpathUO.h"

registerMooseObject("WAAMApp", WAAMActivationAux);

InputParameters
WAAMActivationAux::validParams()
{
  InputParameters params = AuxKernel::validParams();
  params.addClassDescription(
      "Copies the toolpath activation ledger (nodal psi or elemental birth mask) into an "
      "auxiliary variable");
  params.addRequiredParam<UserObjectName>("toolpath_uo", "The WAAMToolpathUO to query");
  return params;
}

WAAMActivationAux::WAAMActivationAux(const InputParameters & parameters)
  : AuxKernel(parameters), _uo(getUserObject<UserObject>("toolpath_uo"))
{
  if (!dynamic_cast<const WAAMToolpathUO *>(&_uo))
    paramError("toolpath_uo", "Object is not a WAAMToolpathUO");
}

Real
WAAMActivationAux::computeValue()
{
  const auto & uo = dynamic_cast<const WAAMToolpathUO &>(_uo);
  if (_nodal)
    return uo.psiAt(_current_node->id(), _t);
  return uo.faAt(_current_elem->id(), _t);
}
