#pragma once

#include "NodalVariablePostprocessor.h"

#include <unordered_map>
#include <vector>

/// Melt-pool phase statistics from the CALPHAD phase-fraction tables.
///
/// Reports the numbers the P4 audit needs and that the raw temperature field
/// cannot give on its own:
///
///   * ``max_liquid``     -- the largest local liquid fraction, i.e. how close
///     the pool is to fully molten (the key melt-pool metric),
///   * ``molten_volume``  -- the volume-weighted molten fraction of the
///     domain, i.e. how much of the part is liquid,
///   * ``mean_liquid``    -- the volume-weighted mean liquid fraction.
///
/// The phase fractions come from the CALPHAD solidification path, supplied as
/// interpolation tables, and are evaluated against the local temperature.
///
/// This is a NODAL postprocessor on purpose. At ``EXEC_TIMESTEP_END`` the
/// element-level user objects see the pre-solve values of a nonlinear
/// variable (the variable cache is only refreshed by the output step, which
/// runs after the user-object batch), while the nodal batch recomputes the
/// nodal values from the live solution vector. A nodal postprocessor
/// therefore reports the solved state; an element postprocessor would report
/// the initial condition.
class WAAMMeltPoolPhase : public NodalVariablePostprocessor
{
public:
  static InputParameters validParams();

  WAAMMeltPoolPhase(const InputParameters & parameters);

  virtual void initialize() override;
  virtual void execute() override;
  virtual void finalize() override;
  virtual void threadJoin(const UserObject & y) override;
  virtual Real getValue() const override;

protected:
  /// piecewise-linear interpolation with clamping outside the knots
  static Real interp(const std::vector<Real> & knots,
                     const std::vector<Real> & values,
                     Real t);

  /// 'max_liquid', 'molten_volume' or 'mean_liquid'
  const std::string _mode;
  /// liquid fraction above which a point counts as molten
  const Real _threshold;

  /// CALPHAD knot temperatures [C]
  const std::vector<Real> & _t_phase;
  /// CALPHAD liquid fraction table
  const std::vector<Real> & _f_liquid;
  /// CALPHAD primary solid fraction table
  const std::vector<Real> & _f_primary;
  /// CALPHAD secondary solid fraction table
  const std::vector<Real> & _f_secondary;

  /// lumped nodal volumes (the element volume split equally over its nodes),
  /// keyed by the global node id
  std::unordered_map<dof_id_type, Real> _nodal_volume;

  /// running maximum of the local liquid fraction
  Real _max_liquid;
  /// accumulated volume-weighted liquid content
  Real _liquid_integral;
  /// accumulated volume that is more than half molten
  Real _molten_volume;
  /// accumulated volume
  Real _volume;
};
