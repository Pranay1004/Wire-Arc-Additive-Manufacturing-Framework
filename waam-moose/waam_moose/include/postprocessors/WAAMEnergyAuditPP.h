#pragma once

#include "GeneralPostprocessor.h"

class WAAMEnergyAuditUO;

/// Exposes one quantity of a `WAAMEnergyAuditUO` as a postprocessor
/// (CSV/console evidence for the energy drill).
class WAAMEnergyAuditPP : public GeneralPostprocessor
{
public:
  static InputParameters validParams();

  WAAMEnergyAuditPP(const InputParameters & parameters);

  virtual void initialize() override {}
  virtual void execute() override {}
  virtual Real getValue() const override;

protected:
  enum class Quantity
  {
    INTENDED_ENERGY,
    INJECTED_ENERGY,
    INJECTED_ENERGY_RAW,
    INTENDED_POWER,
    FIDELITY
  };

  const WAAMEnergyAuditUO & _audit;
  const Quantity _quantity;
};
