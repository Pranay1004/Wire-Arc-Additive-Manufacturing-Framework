#pragma once

#include "AuxKernel.h"

/**
 * WAAMUltrasonicAux: Evaluates Ultrasonic Vibration-Assisted (UVA) additive
 * manufacturing physics:
 *  - Acoustic pressure amplitude: P = rho * c_sound * omega * A * exp(-alpha * z / 2)
 *  - Acoustic intensity: I = 0.5 * rho * c_sound * (omega * A)^2 * exp(-alpha * z)
 *  - Acoustic streaming velocity: v_stream = 0.15 * sqrt(I / (rho * c_sound))
 *  - Acoustic volumetric thermal dissipation: Q_acou = 2 * alpha * I
 *  - Dynamic acoustic softening factor: S_acou = min(0.8, eta_soft * P / P_cav)
 *  - Cavitation index: C_cav = max(0, (P - P_cav) / P_cav)
 */
class WAAMUltrasonicAux : public AuxKernel
{
public:
  static InputParameters validParams();

  WAAMUltrasonicAux(const InputParameters & parameters);

protected:
  virtual Real computeValue() override;

  const Real _freq;
  const Real _amp;
  const Real _c_sound;
  const Real _rho;
  const Real _alpha;
  const Real _cav_threshold;
  const Real _soft_eff;
  const int _field_type;
};
