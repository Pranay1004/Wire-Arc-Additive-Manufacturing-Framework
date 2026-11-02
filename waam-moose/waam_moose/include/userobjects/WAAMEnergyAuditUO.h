#pragma once

#include "GeneralUserObject.h"

class WAAMToolpathUO;

/// Energy audit against the FreeFEM schedule.
///
/// Intended energy reproduces the generated program's `EintJ += Pweld * pState
/// * dt` line: at every step ending at t_n (executed at `timestep_end`, the
/// step's own gate time) a welding torch state adds `Pweld * dt`.
///
/// Injected energy integrates the instantaneous masked/raw source power
/// (`WAAMSourcePower` postprocessors) with the same right-endpoint rule the
/// per-step assembly uses: `E += P(t_n) * dt`.
///
/// With a `TimeSequenceStepper` carrying the FreeFEM step times (P4) the
/// intended counter reproduces the baseline `Earc = 714.514 kJ` exactly.
class WAAMEnergyAuditUO : public GeneralUserObject
{
public:
  static InputParameters validParams();

  WAAMEnergyAuditUO(const InputParameters & parameters);

  virtual void initialize() override;
  virtual void execute() override;
  virtual void finalize() override {}

  /// Intended arc energy delivered up to the current step [J].
  Real intendedEnergy() const { return _e_intended; }
  /// ∫ P_masked dt accumulated so far [J].
  Real injectedEnergy() const { return _e_injected; }
  /// ∫ P_raw dt accumulated so far [J].
  Real injectedEnergyRaw() const { return _e_injected_raw; }

  /// Instantaneous intended power at time t: Pweld while the torch is welding.
  Real intendedPowerAt(Real t) const;

  /// injected / intended (0 before any intended energy).
  Real fidelity() const { return _e_intended > 0. ? _e_injected / _e_intended : 0.; }

private:
  const WAAMToolpathUO & _uo;
  const Real & _pweld;
  const PostprocessorValue & _p_masked;
  const PostprocessorValue & _p_raw;

  Real & _e_intended;
  Real & _e_injected;
  Real & _e_injected_raw;
};
