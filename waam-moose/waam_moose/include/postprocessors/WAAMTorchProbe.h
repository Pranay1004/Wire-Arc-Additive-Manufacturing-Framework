#pragma once

#include "GeneralPostprocessor.h"

/// Exposes WAAMToolpathUO torch state (clock mapping / arc gating) as a
/// postprocessor for parity tests and run logs.
class WAAMTorchProbe : public GeneralPostprocessor
{
public:
  static InputParameters validParams();

  WAAMTorchProbe(const InputParameters & parameters);

  virtual void initialize() override;
  virtual void execute() override;
  virtual Real getValue() const override { return _value; }

protected:
  const UserObject & _uo;
  const unsigned int _component;
  Real _value = 0.0;
};
