#pragma once

#include "IntegratedBC.h"

/// FreeFEM-parity convection + linearized-radiation Robin boundary,
/// weighted by the nodal activation field:
///
///   residual = test * psi * [ h*(T - Tamb) + er*(T^2+Ta^2)*(T+Ta)*(T - Tamb) ]
///
/// The radiation part is exactly FreeFEM's `hSurf = hConv + 0.7*sigma*(TvK^2 +
/// TaK^2)*(TvK + TaK)` with Ta = 25 C: (T^2+Ta^2)(T+Ta)*(T-Tamb) == T^4 - Ta^4,
/// frozen at the current iterate inside the coefficient (Picard linearization,
/// matching the generated program's linear assembly). The Jacobian uses the
/// same frozen coefficient, so PJFNK reproduces the FreeFEM linear solve.
///
/// Boundary mapping (medit refs -> exodus labels): lbl_1 = bottom -> hBot
/// (50 W/m^2K, no radiation); lbl_2 + lbl_5 (flanks/top) -> hConv = 15 plus
/// radiation (0.7 * 5.67e-8).
class WAAMRobinBC : public IntegratedBC
{
public:
  static InputParameters validParams();

  WAAMRobinBC(const InputParameters & parameters);

protected:
  virtual Real computeQpResidual() override;
  virtual Real computeQpJacobian() override;

  const VariableValue & _psi;
  const Real _h;
  const Real _t_ambient;
  const Real _radiation;
};
