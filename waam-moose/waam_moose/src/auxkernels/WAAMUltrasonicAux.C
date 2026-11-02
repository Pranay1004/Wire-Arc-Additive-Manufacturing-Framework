#include "WAAMUltrasonicAux.h"
#include "libmesh/point.h"
#include <cmath>

registerMooseObject("WAAMApp", WAAMUltrasonicAux);

InputParameters
WAAMUltrasonicAux::validParams()
{
  InputParameters params = AuxKernel::validParams();
  params.addClassDescription(
      "Evaluates ultrasonic vibration-assisted (UVA) acoustic pressure, streaming, "
      "cavitation, and softening fields in WAAM.");

  params.addParam<Real>("frequency", 20000.0, "Ultrasonic frequency [Hz]");
  params.addParam<Real>("amplitude", 15.0e-6, "Horn vibration amplitude [m]");
  params.addParam<Real>("c_sound", 5790.0, "Speed of sound in alloy [m/s]");
  params.addParam<Real>("density", 7850.0, "Alloy density [kg/m^3]");
  params.addParam<Real>("attenuation", 0.12, "Acoustic attenuation coefficient [1/m]");
  params.addParam<Real>("cavitation_threshold", 1.0e6, "Cavitation pressure threshold [Pa]");
  params.addParam<Real>("softening_efficiency", 0.15, "Acoustic softening coupling efficiency");

  MooseEnum fieldEnum("pressure intensity streaming_velocity dissipation softening cavitation_index", "pressure");
  params.addParam<MooseEnum>("field_type", fieldEnum, "Type of acoustic field to evaluate");

  return params;
}

WAAMUltrasonicAux::WAAMUltrasonicAux(const InputParameters & parameters)
  : AuxKernel(parameters),
    _freq(getParam<Real>("frequency")),
    _amp(getParam<Real>("amplitude")),
    _c_sound(getParam<Real>("c_sound")),
    _rho(getParam<Real>("density")),
    _alpha(getParam<Real>("attenuation")),
    _cav_threshold(getParam<Real>("cavitation_threshold")),
    _soft_eff(getParam<Real>("softening_efficiency")),
    _field_type(getParam<MooseEnum>("field_type"))
{
}

Real
WAAMUltrasonicAux::computeValue()
{
  // Distance from bottom substrate boundary (z=0)
  const Real z = _nodal ? (*_current_node)(2) : _current_elem->vertex_average()(2);
  const Real z_eff = std::max(0.0, z);

  const Real pi = M_PI;
  const Real omega = 2.0 * pi * _freq;
  const Real v_us = _amp * omega;

  // Acoustic intensity [W/m^2]
  const Real I_0 = 0.5 * _rho * _c_sound * v_us * v_us;
  const Real I = I_0 * std::exp(-_alpha * z_eff);

  // Acoustic pressure amplitude [Pa]
  const Real P_0 = _rho * _c_sound * omega * _amp;
  const Real P = P_0 * std::exp(-0.5 * _alpha * z_eff);

  switch (_field_type)
  {
    case 0: // pressure
      return P;
    case 1: // intensity
      return I;
    case 2: // streaming_velocity [m/s]
      return 0.15 * std::sqrt(std::max(0.0, I / (_rho * _c_sound)));
    case 3: // dissipation [W/m^3]
      return 2.0 * _alpha * I;
    case 4: // softening factor (dimensionless fraction in [0, 0.8])
      return std::min(0.8, _soft_eff * (P / _cav_threshold));
    case 5: // cavitation index (>= 0 when P > P_cav)
      return std::max(0.0, (P - _cav_threshold) / _cav_threshold);
    default:
      return P;
  }
}
