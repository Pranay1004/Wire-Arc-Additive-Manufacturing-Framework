#include "WAAMMeltPoolPhase.h"

#include "MooseMesh.h"
#include "MooseVariable.h"
#include "SubProblem.h"

#include "libmesh/elem.h"

#include <algorithm>

registerMooseObject("WAAMApp", WAAMMeltPoolPhase);

InputParameters
WAAMMeltPoolPhase::validParams()
{
  InputParameters params = NodalVariablePostprocessor::validParams();
  params.addClassDescription(
      "Melt-pool phase statistics from the CALPHAD phase-fraction tables "
      "(max local liquid fraction, molten volume fraction or mean liquid fraction)");
  params.addRequiredParam<std::vector<Real>>("T_phase", "CALPHAD knot temperatures [C]");
  params.addRequiredParam<std::vector<Real>>("f_liquid", "CALPHAD liquid fraction table");
  params.addParam<std::vector<Real>>("f_primary",
                                      std::vector<Real>(),
                                      "CALPHAD primary solid fraction table");
  params.addParam<std::vector<Real>>("f_secondary",
                                      std::vector<Real>(),
                                      "CALPHAD secondary solid fraction table");
  params.addParam<std::string>(
      "mode",
      "max_liquid",
      "Reported quantity: 'max_liquid' (largest local liquid fraction), "
      "'molten_volume' (volume fraction that is more than half molten) or "
      "'mean_liquid' (volume-weighted mean liquid fraction)");
  params.addParam<Real>("threshold",
                        0.5,
                        "Liquid fraction above which a point counts as molten");
  return params;
}

WAAMMeltPoolPhase::WAAMMeltPoolPhase(const InputParameters & parameters)
  : NodalVariablePostprocessor(parameters),
    _mode(getParam<std::string>("mode")),
    _threshold(getParam<Real>("threshold")),
    _t_phase(getParam<std::vector<Real>>("T_phase")),
    _f_liquid(getParam<std::vector<Real>>("f_liquid")),
    _f_primary(getParam<std::vector<Real>>("f_primary")),
    _f_secondary(getParam<std::vector<Real>>("f_secondary")),
    _max_liquid(0.0),
    _liquid_integral(0.0),
    _molten_volume(0.0),
    _volume(0.0)
{
  if (_t_phase.size() != _f_liquid.size())
    paramError("f_liquid", "the table size must match T_phase");

  // Lumped nodal volumes: each element's volume is split equally over its
  // nodes. This is the standard nodal quadrature and keeps the statistic
  // volume weighted without needing an element loop in a nodal object. The
  // map is keyed by the global node id so it is valid across ranks.
  for (auto & elem : *_mesh.getActiveLocalElementRange())
  {
    const Real volume = elem->volume();
    const auto * nodes = elem->get_nodes();
    const Real share = volume / static_cast<Real>(elem->n_nodes());
    for (unsigned int i = 0; i < elem->n_nodes(); ++i)
      _nodal_volume[nodes[i]->id()] += share;
  }
}

Real
WAAMMeltPoolPhase::interp(const std::vector<Real> & knots,
                           const std::vector<Real> & values,
                           Real t)
{
  if (knots.empty() || values.empty())
    return 0.0;
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
WAAMMeltPoolPhase::initialize()
{
  _max_liquid = 0.0;
  _liquid_integral = 0.0;
  _molten_volume = 0.0;
  _volume = 0.0;
}

void
WAAMMeltPoolPhase::execute()
{
  const Real T = _u[_qp];
  const Real f_liquid = interp(_t_phase, _f_liquid, T);

  const auto it = _nodal_volume.find(_current_node->id());
  const Real weight = (it == _nodal_volume.end()) ? 0.0 : it->second;

  _max_liquid = std::max(_max_liquid, f_liquid);
  _volume += weight;
  _liquid_integral += weight * f_liquid;
  if (f_liquid > _threshold)
    _molten_volume += weight;
}

Real
WAAMMeltPoolPhase::getValue() const
{
  if (_mode == "max_liquid")
    return _max_liquid;
  if (_mode == "mean_liquid")
    return _volume > 0.0 ? _liquid_integral / _volume : 0.0;
  // 'molten_volume'
  return _volume > 0.0 ? _molten_volume / _volume : 0.0;
}

void
WAAMMeltPoolPhase::threadJoin(const UserObject & y)
{
  const auto & pps = static_cast<const WAAMMeltPoolPhase &>(y);
  _max_liquid = std::max(_max_liquid, pps._max_liquid);
  _liquid_integral += pps._liquid_integral;
  _molten_volume += pps._molten_volume;
  _volume += pps._volume;
}

void
WAAMMeltPoolPhase::finalize()
{
  gatherSum(_liquid_integral);
  gatherSum(_molten_volume);
  gatherSum(_volume);
  gatherMax(_max_liquid);
}
