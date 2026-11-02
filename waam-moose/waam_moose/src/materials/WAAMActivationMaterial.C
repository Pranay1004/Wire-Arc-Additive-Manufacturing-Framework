#include "WAAMActivationMaterial.h"

registerMooseObject("WAAMApp", WAAMActivationMaterial);

InputParameters
WAAMActivationMaterial::validParams()
{
  InputParameters params = Material::validParams();
  params.addClassDescription(
      "FreeFEM-parity two-zone thermophysical material with activation masks");
  params.addRequiredCoupledVar("temperature", "Temperature variable [K]");
  params.addRequiredCoupledVar("psi_var", "Nodal activation field (P1 aux)");
  params.addRequiredCoupledVar("fa_var", "Elemental birth mask (P0 aux, majority)");
  params.addRequiredParam<Real>("hz_base", "Substrate/deposit zone split z [m]");
  params.addParam<Real>("psi_floor", 1e-4, "Conductivity floor on the nodal psi");
  params.addParam<Real>("born_floor", 1e-5, "Conductivity floor on the element birth mask");
  params.addParam<Real>("k_liq_factor",
                        1.0,
                        "Liquid-state conductivity enhancement when T > Tliq_zone "
                        "(FreeFEM kLiqF; 1.0 = off)");
  params.addRequiredParam<std::vector<Real>>("T_k_substrate", "Substrate k table knots [K]");
  params.addRequiredParam<std::vector<Real>>("k_substrate", "Substrate k values [W/m/K]");
  params.addRequiredParam<std::vector<Real>>("T_cp_substrate",
                                             "Substrate cp table knots [K] (includes latent spike)");
  params.addRequiredParam<std::vector<Real>>("cp_substrate",
                                             "Substrate cp values [J/kg/K]");
  params.addRequiredParam<Real>("rho_substrate", "Substrate density [kg/m^3]");
  params.addRequiredParam<Real>("Tliq_substrate", "Substrate liquidus [K] (k switch)");
  params.addRequiredParam<std::vector<Real>>("T_k_deposit", "Deposit k table knots [K]");
  params.addRequiredParam<std::vector<Real>>("k_deposit", "Deposit k values [W/m/K]");
  params.addRequiredParam<std::vector<Real>>("T_cp_deposit",
                                             "Deposit cp table knots [K] (includes latent spike)");
  params.addRequiredParam<std::vector<Real>>("cp_deposit", "Deposit cp values [J/kg/K]");
  params.addRequiredParam<Real>("rho_deposit", "Deposit density [kg/m^3]");
  params.addRequiredParam<Real>("Tliq_deposit", "Deposit liquidus [K] (k switch)");
  params.addParam<std::vector<Real>>(
      "T_phase_substrate",
      std::vector<Real>(),
      "CALPHAD phase-fraction knot temperatures for the substrate zone [C]. Empty "
      "disables the phase-fraction properties.");
  params.addParam<std::vector<Real>>(
      "T_phase_deposit",
      std::vector<Real>(),
      "CALPHAD phase-fraction knot temperatures for the deposit zone [C]");
  // The CALPHAD phase set is exposed as three fixed thermal slots: the
  // molten fraction (the one the enthalpy formulation and the melt-pool audit
  // need), the first solid phase to form (delta-ferrite in FA mode) and the
  // remaining solid phases. MOOSE parameters are static, so the real phase
  // names cannot be parameter names; they travel in the calphad.json
  // artifact instead.
  params.addParam<std::vector<Real>>(
      "f_liquid_substrate", std::vector<Real>(), "Substrate molten fraction table");
  params.addParam<std::vector<Real>>(
      "f_primary_substrate", std::vector<Real>(), "Substrate primary solid fraction table");
  params.addParam<std::vector<Real>>(
      "f_secondary_substrate", std::vector<Real>(), "Substrate secondary solid fraction table");
  params.addParam<std::vector<Real>>(
      "f_liquid_deposit", std::vector<Real>(), "Deposit molten fraction table");
  params.addParam<std::vector<Real>>(
      "f_primary_deposit", std::vector<Real>(), "Deposit primary solid fraction table");
  params.addParam<std::vector<Real>>(
      "f_secondary_deposit", std::vector<Real>(), "Deposit secondary solid fraction table");

  // Mechanical parameters
  params.addParam<Real>("E_substrate", 2.0e11, "Substrate Young's modulus [Pa]");
  params.addParam<Real>("E_deposit", 2.0e11, "Deposit Young's modulus [Pa]");
  params.addParam<Real>("poissons_ratio_substrate", 0.3, "Substrate Poisson ratio");
  params.addParam<Real>("poissons_ratio_deposit", 0.3, "Deposit Poisson ratio");
  params.addParam<Real>("thermal_expansion_substrate", 1.6e-5, "Substrate thermal expansion coeff [1/K]");
  params.addParam<Real>("thermal_expansion_deposit", 1.6e-5, "Deposit thermal expansion coeff [1/K]");
  params.addParam<Real>("yield_substrate", 3.5e8, "Substrate yield stress [Pa]");
  params.addParam<Real>("yield_deposit", 3.5e8, "Deposit yield stress [Pa]");
  params.addParam<Real>("hardening_substrate", 1.0e9, "Substrate isotropic hardening constant [Pa]");
  params.addParam<Real>("hardening_deposit", 1.0e9, "Deposit isotropic hardening constant [Pa]");

  return params;
}

WAAMActivationMaterial::WAAMActivationMaterial(const InputParameters & parameters)
  : Material(parameters),
    _temp(coupledValue("temperature")),
    _psi(coupledValue("psi_var")),
    _fa(coupledValue("fa_var")),
    _hz_base(getParam<Real>("hz_base")),
    _psi_floor(getParam<Real>("psi_floor")),
    _born_floor(getParam<Real>("born_floor")),
    _k_liq_factor(getParam<Real>("k_liq_factor")),
    _t_k_base(getParam<std::vector<Real>>("T_k_substrate")),
    _k_base(getParam<std::vector<Real>>("k_substrate")),
    _t_cp_base(getParam<std::vector<Real>>("T_cp_substrate")),
    _cp_base(getParam<std::vector<Real>>("cp_substrate")),
    _rho_base(getParam<Real>("rho_substrate")),
    _tliq_base(getParam<Real>("Tliq_substrate")),
    _t_k_dep(getParam<std::vector<Real>>("T_k_deposit")),
    _k_dep(getParam<std::vector<Real>>("k_deposit")),
    _t_cp_dep(getParam<std::vector<Real>>("T_cp_deposit")),
    _cp_dep(getParam<std::vector<Real>>("cp_deposit")),
    _rho_dep(getParam<Real>("rho_deposit")),
    _tliq_dep(getParam<Real>("Tliq_deposit")),
    _k(declareProperty<Real>("thermal_conductivity")),
    _cp(declareProperty<Real>("specific_heat")),
    _rho(declareProperty<Real>("density")),
    _E_base(getParam<Real>("E_substrate")),
    _E_dep(getParam<Real>("E_deposit")),
    _nu_base(getParam<Real>("poissons_ratio_substrate")),
    _nu_dep(getParam<Real>("poissons_ratio_deposit")),
    _alpha_base(getParam<Real>("thermal_expansion_substrate")),
    _alpha_dep(getParam<Real>("thermal_expansion_deposit")),
    _yield_base(getParam<Real>("yield_substrate")),
    _yield_dep(getParam<Real>("yield_deposit")),
    _hardening_base(getParam<Real>("hardening_substrate")),
    _hardening_dep(getParam<Real>("hardening_deposit")),
    _youngs_modulus(declareProperty<Real>("youngs_modulus")),
    _poissons_ratio(declareProperty<Real>("poissons_ratio")),
    _thermal_expansion(declareProperty<Real>("thermal_expansion_coeff")),
    _yield_stress(declareProperty<Real>("yield_stress")),
    _hardening_constant(declareProperty<Real>("hardening_constant"))
{
  if (_t_k_base.size() != _k_base.size() || _t_cp_base.size() != _cp_base.size() ||
      _t_k_dep.size() != _k_dep.size() || _t_cp_dep.size() != _cp_dep.size())
    paramError("T_k_substrate", "table knots and values must have matching sizes");

  // ---- CALPHAD phase fractions (optional) --------------------------------
  _t_phase_base = getParam<std::vector<Real>>("T_phase_substrate");
  _t_phase_dep = getParam<std::vector<Real>>("T_phase_deposit");

  for (const auto & slot : {"liquid", "primary", "secondary"})
  {
    _f_phase_base[slot] = getParam<std::vector<Real>>("f_" + std::string(slot) + "_substrate");
    _f_phase_dep[slot] = getParam<std::vector<Real>>("f_" + std::string(slot) + "_deposit");
    // Declare one material property per slot: phase_fraction_<slot>.
    _phase_props[slot] = &declareProperty<Real>("phase_fraction_" + std::string(slot));
  }

  for (const auto & slot : {"liquid", "primary", "secondary"})
  {
    const auto & kb = _f_phase_base[slot];
    const auto & kd = _f_phase_dep[slot];
    if (!kb.empty() && kb.size() != _t_phase_base.size())
      paramError("f_" + std::string(slot) + "_substrate",
                 "phase-fraction table size does not match T_phase_substrate");
    if (!kd.empty() && kd.size() != _t_phase_dep.size())
      paramError("f_" + std::string(slot) + "_deposit",
                 "phase-fraction table size does not match T_phase_deposit");
  }
}

Real
WAAMActivationMaterial::interp(const std::vector<Real> & knots,
                               const std::vector<Real> & values,
                               Real t)
{
  if (t <= knots.front())
    return values.front();
  if (t >= knots.back())
    return values.back();

  std::size_t i = 1;
  while (i < knots.size() && knots[i] < t)
    ++i;
  const Real x0 = knots[i - 1];
  const Real x1 = knots[i];
  const Real w = (x1 > x0) ? (t - x0) / (x1 - x0) : 0.0;
  return values[i - 1] * (1.0 - w) + values[i] * w;
}

void
WAAMActivationMaterial::computeQpProperties()
{
  const bool substrate = (_q_point[_qp](2) <= _hz_base + 1e-6);

  const Real T = _temp[_qp];

  if (substrate)
  {
    _k[_qp] = interp(_t_k_base, _k_base, T) * std::max(_psi[_qp], _psi_floor) *
              (T > _tliq_base ? _k_liq_factor : 1.0) * std::max(_fa[_qp], _born_floor);
    _cp[_qp] = interp(_t_cp_base, _cp_base, T);
    _rho[_qp] = _rho_base;
  }
  else
  {
    _k[_qp] = interp(_t_k_dep, _k_dep, T) * std::max(_psi[_qp], _psi_floor) *
              (T > _tliq_dep ? _k_liq_factor : 1.0) * std::max(_fa[_qp], _born_floor);
    _cp[_qp] = interp(_t_cp_dep, _cp_dep, T);
    _rho[_qp] = _rho_dep;
  }

  // CALPHAD phase fractions (zone dependent). An empty table means the phase
  // is absent in that zone -> fraction 0.
  if (!_phase_props.empty())
  {
    const auto & knots = substrate ? _t_phase_base : _t_phase_dep;
    for (const auto & [phase, prop] : _phase_props)
    {
      const auto & values = substrate ? _f_phase_base.at(phase) : _f_phase_dep.at(phase);
      (*prop)[_qp] = (knots.empty() || values.empty()) ? 0.0 : interp(knots, values, T);
    }
  }

  // ---- Mechanical properties (E, nu, alpha, yield stress, hardening) ----
  const Real T_ref = 298.15;
  const Real theta_sub = std::max(0.0, std::min(1.0, (T - T_ref) / std::max(100.0, _tliq_base - T_ref)));
  const Real theta_dep = std::max(0.0, std::min(1.0, (T - T_ref) / std::max(100.0, _tliq_dep - T_ref)));
  const Real E_T_sub = _E_base * std::max(0.01, 1.0 - 0.8 * theta_sub);
  const Real E_T_dep = _E_dep * std::max(0.01, 1.0 - 0.8 * theta_dep);
  const Real sy_T_sub = _yield_base * std::max(0.01, 1.0 - 0.9 * theta_sub);
  const Real sy_T_dep = _yield_dep * std::max(0.01, 1.0 - 0.9 * theta_dep);

  if (substrate)
  {
    _youngs_modulus[_qp] = E_T_sub;
    _poissons_ratio[_qp] = _nu_base;
    _thermal_expansion[_qp] = _alpha_base;
    _yield_stress[_qp] = sy_T_sub;
    _hardening_constant[_qp] = _hardening_base;
  }
  else
  {
    const bool is_active = (_fa[_qp] >= 0.5);
    const Real act_scale = is_active ? std::max(_fa[_qp], _born_floor) : _born_floor;
    _youngs_modulus[_qp] = E_T_dep * act_scale;
    _poissons_ratio[_qp] = _nu_dep;
    _thermal_expansion[_qp] = is_active ? _alpha_dep : 0.0;
    _yield_stress[_qp] = is_active ? sy_T_dep : 1.0e10;
    _hardening_constant[_qp] = _hardening_dep;
  }
}

