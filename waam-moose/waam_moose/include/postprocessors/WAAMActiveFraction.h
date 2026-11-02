#pragma once

#include "GeneralPostprocessor.h"

/// Fraction (or count) of deposit elements that are cumulatively active
/// according to the WAAMToolpathUO activation ledger.
class WAAMActiveFraction : public GeneralPostprocessor
{
public:
  static InputParameters validParams();

  WAAMActiveFraction(const InputParameters & parameters);

  virtual void initialize() override;
  virtual void execute() override;
  virtual Real getValue() const override { return _value; }

protected:
  const UserObject & _uo;
  const bool _as_count;
  const bool _use_time_query;
  Real _value = 0.0;
};
