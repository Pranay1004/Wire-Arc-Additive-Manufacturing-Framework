#include "WAAMActiveFraction.h"
#include "WAAMToolpathUO.h"

registerMooseObject("WAAMApp", WAAMActiveFraction);

InputParameters
WAAMActiveFraction::validParams()
{
  InputParameters params = GeneralPostprocessor::validParams();
  params.addClassDescription(
      "Cumulative active deposit fraction (or element count) from the toolpath ledger");
  params.addRequiredParam<UserObjectName>("toolpath_uo", "The WAAMToolpathUO to query");
  params.addParam<bool>("as_count", false, "Report the raw active element count instead of the fraction");
  params.addParam<bool>("use_time_query",
                        false,
                        "Evaluate the pure time-query (faAt at the current time) instead of "
                        "the persisted ledger");
  return params;
}

WAAMActiveFraction::WAAMActiveFraction(const InputParameters & parameters)
  : GeneralPostprocessor(parameters),
    _uo(getUserObject<UserObject>("toolpath_uo")),
    _as_count(getParam<bool>("as_count")),
    _use_time_query(getParam<bool>("use_time_query"))
{
  if (!dynamic_cast<const WAAMToolpathUO *>(&_uo))
    paramError("toolpath_uo", "Object is not a WAAMToolpathUO");
}

void
WAAMActiveFraction::initialize()
{
}

void
WAAMActiveFraction::execute()
{
  const auto & uo = dynamic_cast<const WAAMToolpathUO &>(_uo);
  const unsigned int n_active =
      _use_time_query ? uo.numActiveAt(_t) : uo.numActiveCumulative();
  const unsigned int n_deposit = uo.numDepositElems();

  _value = _as_count ? static_cast<Real>(n_active)
                     : (n_deposit > 0 ? static_cast<Real>(n_active) / n_deposit : 0.0);
}
