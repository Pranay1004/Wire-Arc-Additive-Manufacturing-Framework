#include "WAAMElasticityTensor.h"
#include <cmath>
#include <algorithm>

registerMooseObject("WAAMApp", WAAMElasticityTensor);

InputParameters
WAAMElasticityTensor::validParams()
{
  InputParameters params = ComputeElasticityTensorBase::validParams();
  params.addClassDescription(
      "Temperature-dependent isotropic elasticity tensor with activation masks "
      "and molten slurry cutoff.");

  params.addRequiredCoupledVar("temperature", "Temperature variable [K]");
  params.addRequiredCoupledVar("psi_var", "Nodal activation field (P1 aux)");
  params.addRequiredCoupledVar("fa_var", "Elemental birth mask (P0 aux, majority)");

  params.addRequiredParam<Real>("hz_base", "Substrate/deposit zone split z [m]");
  params.addParam<Real>("E_substrate", 2.0e11, "Substrate Young's modulus [Pa]");
  params.addParam<Real>("E_deposit", 2.0e11, "Deposit Young's modulus [Pa]");
  params.addParam<Real>("poissons_ratio_substrate", 0.3, "Substrate Poisson ratio");
  params.addParam<Real>("poissons_ratio_deposit", 0.3, "Deposit Poisson ratio");
  params.addParam<Real>("T_solidus_substrate", 1723.0, "Substrate solidus temperature [K]");
  params.addParam<Real>("T_solidus_deposit", 1723.0, "Deposit solidus temperature [K]");
  params.addParam<Real>("born_floor", 1.0e-5, "Modulus floor on unactivated elements");
  params.addParam<Real>("slurry_factor", 0.02, "Molten slurry modulus factor above solidus");

  return params;
}

WAAMElasticityTensor::WAAMElasticityTensor(const InputParameters & parameters)
  : ComputeElasticityTensorBase(parameters),
    _temp(coupledValue("temperature")),
    _psi(coupledValue("psi_var")),
    _fa(coupledValue("fa_var")),
    _hz_base(getParam<Real>("hz_base")),
    _E_base(getParam<Real>("E_substrate")),
    _E_dep(getParam<Real>("E_deposit")),
    _nu_base(getParam<Real>("poissons_ratio_substrate")),
    _nu_dep(getParam<Real>("poissons_ratio_deposit")),
    _tsol_base(getParam<Real>("T_solidus_substrate")),
    _tsol_dep(getParam<Real>("T_solidus_deposit")),
    _born_floor(getParam<Real>("born_floor")),
    _slurry_factor(getParam<Real>("slurry_factor"))
{
  issueGuarantee(_elasticity_tensor_name, Guarantee::ISOTROPIC);
  issueGuarantee("effective_stiffness", Guarantee::ISOTROPIC);
}

void
WAAMElasticityTensor::computeQpElasticityTensor()
{
  const bool substrate = (_q_point[_qp](2) <= _hz_base + 1.0e-6);
  const Real T = _temp[_qp];
  const Real T_ref = 25.0; // In Celsius matching simulation temperature field
  const Real T_sol = substrate ? _tsol_base : _tsol_dep;
  const Real E_0 = substrate ? _E_base : _E_dep;
  const Real nu = substrate ? _nu_base : _nu_dep;

  // Thermal softening ratio
  const Real theta = std::max(0.0, std::min(1.0, (T - T_ref) / std::max(100.0, T_sol - T_ref)));
  Real E_T = E_0 * std::max(_slurry_factor, 1.0 - (1.0 - _slurry_factor) * theta);

  // Slurry cutoff above solidus (liquid pool cannot carry elastic shear stress)
  if (T >= T_sol)
    E_T = std::max(1.0e6, _slurry_factor * E_0);

  // Element birth activation scaling: unactivated void elements are quieted
  if (!substrate)
  {
    const bool is_active = (_fa[_qp] >= 0.5);
    const Real act_scale = is_active ? std::max(_fa[_qp], _born_floor) : _born_floor;
    E_T *= act_scale;
  }

  _elasticity_tensor[_qp].fillSymmetricIsotropicEandNu(E_T, nu);
  _effective_stiffness[_qp] = std::sqrt(E_T / (2.0 * (1.0 + nu)));
}
