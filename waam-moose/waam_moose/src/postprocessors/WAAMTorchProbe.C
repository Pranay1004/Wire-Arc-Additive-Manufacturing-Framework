#include "WAAMTorchProbe.h"
#include "WAAMToolpathUO.h"

registerMooseObject("WAAMApp", WAAMTorchProbe);

InputParameters
WAAMTorchProbe::validParams()
{
  InputParameters params = GeneralPostprocessor::validParams();
  params.addClassDescription("Reports a component of the WAAM torch state at the current time");
  params.addRequiredParam<UserObjectName>("toolpath_uo", "The WAAMToolpathUO to query");
  MooseEnum component("x y z pstate tlocal layer seg_frac", "x");
  params.addParam<MooseEnum>("component", component, "Torch state component to report");
  return params;
}

WAAMTorchProbe::WAAMTorchProbe(const InputParameters & parameters)
  : GeneralPostprocessor(parameters),
    _uo(getUserObject<UserObject>("toolpath_uo")),
    _component(getParam<MooseEnum>("component"))
{
  if (!dynamic_cast<const WAAMToolpathUO *>(&_uo))
    paramError("toolpath_uo", "Object is not a WAAMToolpathUO");
}

void
WAAMTorchProbe::initialize()
{
}

void
WAAMTorchProbe::execute()
{
  const auto & uo = dynamic_cast<const WAAMToolpathUO &>(_uo);
  const WAAMTorchState st = uo.torchStateAt(_t);

  switch (_component)
  {
    case 0:
      _value = st.position(0);
      break;
    case 1:
      _value = st.position(1);
      break;
    case 2:
      _value = st.position(2);
      break;
    case 3:
      _value = st.p_state;
      break;
    case 4:
      _value = st.t_local;
      break;
    case 5:
      _value = st.layer;
      break;
    default:
      _value = st.seg_frac;
      break;
  }
}
