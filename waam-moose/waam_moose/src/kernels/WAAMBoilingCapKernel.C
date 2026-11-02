#include "WAAMBoilingCapKernel.h"

#include "MaterialProperty.h" // MaterialProperty<Real> lookup (exact type match)

registerMooseObject("WAAMApp", WAAMBoilingCapKernel);

InputParameters
WAAMBoilingCapKernel::validParams()
{
  InputParameters params = Kernel::validParams();
  params.addClassDescription(
      "Smooth evaporation sink pinning the pool at Tboil (FreeFEM boiling-cap "
      "parity; removed energy is audited via WAAMCapPower)");
  params.addParam<MaterialPropertyName>("density_name",
                                        "density",
                                        "Property supplying rho [kg/m^3] "
                                        "(WAAMActivationMaterial emits this name)");
  params.addParam<MaterialPropertyName>("specific_heat_name",
                                        "specific_heat",
                                        "Property supplying cp [J/kg/K] (never masked; "
                                        "FreeFEM keeps mass unmasked, so does the cap)");
  params.addRequiredParam<Real>("t_boil", "Boiling / vaporization cap [C] (FreeFEM Tboil)");
  params.addParam<Real>(
      "rate",
      3.0e5,
      "Relaxation gain [1/s] of the sink: at the baseline arc regime the pinning "
      "offset T - Tboil ~ q_field / (rho * cp * rate) stays well below 1 K.");
  params.addParam<Real>(
      "width",
      25.0,
      "Smoothstep activation width [C] centred just below Tboil: r = 0 below "
      "Tboil - width, r = 1 at T >= Tboil. Keeps the residual C1 in T.");
  return params;
}

WAAMBoilingCapKernel::WAAMBoilingCapKernel(const InputParameters & parameters)
  : Kernel(parameters),
    _density_name(getParam<MaterialPropertyName>("density_name")),
    _specific_heat_name(getParam<MaterialPropertyName>("specific_heat_name")),
    _rho(getMaterialPropertyByName<Real>(_density_name)),
    _cp(getMaterialPropertyByName<Real>(_specific_heat_name)),
    _t_boil(getParam<Real>("t_boil")),
    _rate(getParam<Real>("rate")),
    _width(getParam<Real>("width"))
{
  if (_width <= 0.0)
    paramError("width", "must be positive (smoothstep width in C)");
}

std::pair<Real, Real>
WAAMBoilingCapKernel::smoothGate(Real T, Real edge, Real width)
{
  // s = normalised position inside the activation window [edge, edge + width];
  // smoothstep s^2*(3-2s) is C1 at both ends (zero slope), so dr/dT vanishes
  // at the joins with the r=0 / r=1 plateaus and no kink plane survives.
  const Real s = (T - edge) / width;
  if (s <= 0.0)
    return {0.0, 0.0};
  if (s >= 1.0)
    return {1.0, 0.0};
  return {s * s * (3.0 - 2.0 * s), 6.0 * s * (1.0 - s) / width};
}

Real
WAAMBoilingCapKernel::computeQpResidual()
{
  const Real T = _u[_qp];
  if (T <= _t_boil)
    return 0.0;
  const auto [r, dr] = smoothGate(T, _t_boil, _width);
  // Removal rate [W/m^3]; strictly positive above Tboil, zero below Tboil.
  // rho and cp follow the torch-region material but are NOT masked by psi/fa.
  return _test[_i][_qp] * _rho[_qp] * _cp[_qp] * _rate * r * (T - _t_boil);
}

Real
WAAMBoilingCapKernel::computeQpJacobian()
{
  const Real T = _u[_qp];
  if (T <= _t_boil)
    return 0.0;
  const auto [r, dr] = smoothGate(T, _t_boil, _width);
  // d/dT of rho*cp*rate*(T - Tboil)*r(T); rho/cp are frozen-coefficient
  // contributions (Picard parity with FreeFEM).
  return _test[_i][_qp] * _phi[_j][_qp] * _rho[_qp] * _cp[_qp] * _rate *
         (r + (T - _t_boil) * dr);
}
