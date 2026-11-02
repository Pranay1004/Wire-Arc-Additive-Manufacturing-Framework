#include "WAAMEnergyAuditUO.h"
#include "WAAMToolpathUO.h"

registerMooseObject("WAAMApp", WAAMEnergyAuditUO);

InputParameters
WAAMEnergyAuditUO::validParams()
{
  InputParameters params = GeneralUserObject::validParams();
  params.addClassDescription(
      "Intended-vs-injected arc energy audit (FreeFEM EintJ parity schedule)");
  params.addRequiredParam<UserObjectName>("toolpath_uo", "The WAAMToolpathUO instance");
  params.addRequiredParam<Real>("pweld", "Weld power constant Pweld [W] (3840 baseline)");
  params.addRequiredParam<PostprocessorName>(
      "power_pp", "WAAMSourcePower integral [W], masked (src_power)");
  params.addRequiredParam<PostprocessorName>(
      "power_raw_pp", "WAAMSourcePower integral [W], raw (src_power_raw)");
  return params;
}

WAAMEnergyAuditUO::WAAMEnergyAuditUO(const InputParameters & parameters)
  : GeneralUserObject(parameters),
    _uo(getUserObject<WAAMToolpathUO>("toolpath_uo")),
    _pweld(getParam<Real>("pweld")),
    _p_masked(getPostprocessorValueByName(getParam<PostprocessorName>("power_pp"))),
    _p_raw(getPostprocessorValueByName(getParam<PostprocessorName>("power_raw_pp"))),
    _e_intended(declareRestartableData<Real>("e_intended", 0.)),
    _e_injected(declareRestartableData<Real>("e_injected", 0.)),
    _e_injected_raw(declareRestartableData<Real>("e_injected_raw", 0.))
{
  if (_pweld <= 0)
    paramError("pweld", "must be positive");
}

void
WAAMEnergyAuditUO::initialize()
{
  // No-op on purpose: GeneralUserObjects get initialize() called before every
  // execute() (FEProblemBase::computeUserObjects), so zeroing here would reset
  // the counters each step. Cumulative state lives in restartable data whose
  // initial value is 0 and which is restored verbatim on --recover.
}

Real
WAAMEnergyAuditUO::intendedPowerAt(Real t) const
{
  const WAAMTorchState st = _uo.torchStateAt(t);
  return (st.in_pass && st.p_state > 0.5) ? _pweld : 0.;
}

void
WAAMEnergyAuditUO::execute()
{
  if (_t <= 0.)
    return;

  const Real dt = _dt;
  _e_intended += intendedPowerAt(_t) * dt;
  _e_injected += _p_masked * dt;
  _e_injected_raw += _p_raw * dt;
}
