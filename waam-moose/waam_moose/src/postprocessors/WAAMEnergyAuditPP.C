#include "WAAMEnergyAuditPP.h"
#include "WAAMEnergyAuditUO.h"

registerMooseObject("WAAMApp", WAAMEnergyAuditPP);

InputParameters
WAAMEnergyAuditPP::validParams()
{
  InputParameters params = GeneralPostprocessor::validParams();
  params.addClassDescription("Exposes a WAAMEnergyAuditUO quantity as a postprocessor");
  params.addRequiredParam<UserObjectName>("audit_uo", "The WAAMEnergyAuditUO instance");
  MooseEnum quantity("intended_energy injected_energy injected_energy_raw intended_power "
                     "fidelity",
                     "intended_energy");
  params.addParam<MooseEnum>("quantity", quantity, "Quantity to expose");
  return params;
}

WAAMEnergyAuditPP::WAAMEnergyAuditPP(const InputParameters & parameters)
  : GeneralPostprocessor(parameters),
    _audit(getUserObject<WAAMEnergyAuditUO>("audit_uo")),
    _quantity(getParam<MooseEnum>("quantity")
                  .getEnum<Quantity>())
{
}

Real
WAAMEnergyAuditPP::getValue() const
{
  switch (_quantity)
  {
    case Quantity::INTENDED_ENERGY:
      return _audit.intendedEnergy();
    case Quantity::INJECTED_ENERGY:
      return _audit.injectedEnergy();
    case Quantity::INJECTED_ENERGY_RAW:
      return _audit.injectedEnergyRaw();
    case Quantity::INTENDED_POWER:
      return _audit.intendedPowerAt(_t);
    case Quantity::FIDELITY:
      return _audit.fidelity();
  }
  return 0.;
}
