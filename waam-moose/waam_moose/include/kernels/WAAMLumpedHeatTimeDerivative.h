#pragma once

#include "TimeKernel.h"

/// Lump-mass heat-capacity time derivative: rho * cp * dT/dt with a DIAGONAL
/// (lumped) mass matrix.
///
/// Root-cause fix for the P1 moving-source under/overshoot. The consistent
/// Galerkin mass matrix couples neighbouring nodal time derivatives, so a
/// ~4e10 W/m^3 Goldak source interpolated onto ~9.5 mm tets at dt = 0.33 s
/// rings: cold neighbours undershoot far below ambient (measured -87 C on
/// step 1, -826 C by t ~ 8 s) and the hot node overshoots. MOOSE's own docs on
/// MassLumpedTimeDerivative call this out ("spurious oscillations with
/// unphysical under- and over-shoot phenomena") and recommend lumping, which
/// isolates each nodal equation term to its own node.
///
/// FreeFEM never sees the ringing because it (a) does a per-step linear solve
/// and (b) CLIPS the nodal field at [Tamb, Tboil] after every solve. With a
/// lumped mass matrix MOOSE's implicit solve no longer produces the ringing in
/// the first place, and the WAAMFreeFEMClip corrector removes any residual
/// excursion so the ledger matches the FreeFEM baseline bit-for-bit.
///
/// The coefficient is the WAAMActivationMaterial rho * cp (same property names
/// as HeatConductionTimeDerivative). Following MassLumpedTimeDerivative, the
/// Jacobian is diagonal (only the _i,i entry is filled) and the residual uses
/// the nodal dofValuesDot() so each node's equation is independent.
class WAAMLumpedHeatTimeDerivative : public TimeKernel
{
public:
  static InputParameters validParams();

  WAAMLumpedHeatTimeDerivative(const InputParameters & parameters);

  virtual void computeJacobian() override;

protected:
  virtual Real computeQpResidual() override;
  virtual Real computeQpJacobian() override;

  const MaterialPropertyName _density_name;
  const MaterialPropertyName _specific_heat_name;
  const MaterialProperty<Real> & _rho;
  const MaterialProperty<Real> & _cp;
  const VariableValue & _u_dot_nodal;};
