#pragma once

#include "Material.h"

#include <map>
#include <string>
#include <vector>

class WAAMToolpathUO;

/// FreeFEM-parity thermophysical material for the activation ("born dead") model.
///
/// Two zones switch at ``hz_base`` (substrate below, deposit above):
///   zone = (z_qp <= hz_base + 1e-6) ? substrate : deposit
///
/// Each zone supplies piecewise-linear T-tables for k and cp (the cp table
/// carries the latent-heat spike exactly as emitted by the FreeFEM builder:
/// that is what the P2 moose_builder writes from material_database.json).
/// Density is constant per zone.
///
/// Masks (identities with the generated FreeFEM program):
///   k_eff   = k(T) * max(psi_qp, psi_floor) * (T > Tliq_zone ? k_liq_factor : 1)
///             * max(fa_e, born_floor)
///   cp_eff  = cp(T)            (never masked; apparent heat capacity, latent
///                               spike included -> identical to the enthalpy
///                               formulation of FreeFEM)
///   rho_eff = rho_zone         (never masked)
class WAAMActivationMaterial : public Material
{
public:
  static InputParameters validParams();

  WAAMActivationMaterial(const InputParameters & parameters);

protected:
  virtual void computeQpProperties() override;

  /// Piecewise-linear interpolation with clamping outside the knots.
  static Real interp(const std::vector<Real> & knots,
                     const std::vector<Real> & values,
                     Real t);

  const VariableValue & _temp;
  const VariableValue & _psi;
  const VariableValue & _fa;

  const Real _hz_base;
  const Real _psi_floor;
  const Real _born_floor;
  const Real _k_liq_factor;

  const std::vector<Real> & _t_k_base;
  const std::vector<Real> & _k_base;
  const std::vector<Real> & _t_cp_base;
  const std::vector<Real> & _cp_base;
  const Real _rho_base;
  const Real _tliq_base;

  const std::vector<Real> & _t_k_dep;
  const std::vector<Real> & _k_dep;
  const std::vector<Real> & _t_cp_dep;
  const std::vector<Real> & _cp_dep;
  const Real _rho_dep;
  const Real _tliq_dep;

  /// CALPHAD phase-fraction tables: one knot vector per zone, one value
  /// vector per phase ("liquid" plus the family's solid phases). Empty when
  /// no CALPHAD data is supplied (the phase-fraction properties are then
  /// simply not declared).
  std::vector<Real> _t_phase_base;
  std::vector<Real> _t_phase_dep;
  /// phase name -> per-zone value table
  std::map<std::string, std::vector<Real>> _f_phase_base;
  std::map<std::string, std::vector<Real>> _f_phase_dep;
  /// declared material properties, phase name -> property
  std::map<std::string, MaterialProperty<Real> *> _phase_props;

  MaterialProperty<Real> & _k;
  MaterialProperty<Real> & _cp;
  MaterialProperty<Real> & _rho;

  // Mechanical properties
  const Real _E_base;
  const Real _E_dep;
  const Real _nu_base;
  const Real _nu_dep;
  const Real _alpha_base;
  const Real _alpha_dep;
  const Real _yield_base;
  const Real _yield_dep;
  const Real _hardening_base;
  const Real _hardening_dep;

  MaterialProperty<Real> & _youngs_modulus;
  MaterialProperty<Real> & _poissons_ratio;
  MaterialProperty<Real> & _thermal_expansion;
  MaterialProperty<Real> & _yield_stress;
  MaterialProperty<Real> & _hardening_constant;
};
