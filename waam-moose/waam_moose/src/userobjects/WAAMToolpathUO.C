#include "WAAMToolpathUO.h"

#include "FEProblemBase.h"
#include "MooseMesh.h"
#include "MooseUtils.h"
#include "libmesh/libmesh.h"

#include <algorithm>
#include <cmath>
#include <fstream>

registerMooseObject("WAAMApp", WAAMToolpathUO);

InputParameters
WAAMToolpathUO::validParams()
{
  InputParameters params = GeneralUserObject::validParams();
  params.addClassDescription(
      "Slicer toolpath + activation schedule (FreeFEM-parity deposition semantics)");

  params.addRequiredParam<FileName>("toolpath_file", "Slicer toolpath.txt (t x y z pState, SI)");
  params.addRequiredParam<FileName>("layer_times_file",
                                    "layer_pass_times.txt (per-layer pass durations)");
  params.addRequiredParam<Real>("hz_base", "Substrate top z [m] (permanently active)");
  params.addRequiredParam<Real>("h_bead_first", "First layer height [m]");
  params.addRequiredParam<Real>("h_bead_sub", "Subsequent layer height [m]");
  params.addParam<Real>("match_tol_frac", 0.45, "Layer z-match tolerance (fraction of layer height)");
  params.addParam<Real>("dwell_time", 0.0, "Inter-pass dwell duration [s]");

  params.addRequiredParam<Real>("af", "Goldak front semi-axis along travel [m]");
  params.addRequiredParam<Real>("ar", "Goldak rear semi-axis along travel [m]");
  params.addRequiredParam<Real>("bG", "Goldak transverse semi-axis [m]");
  params.addRequiredParam<Real>("cG", "Goldak depth semi-axis [m]");
  params.addParam<Real>("z_activation_frac",
                        0.85,
                        "Activation z half-band = max(cG, z_activation_frac * layer height)");
  params.addParam<bool>("bidirectional",
                        true,
                        "Flip the Goldak front/rear tilt on odd layers (FreeFEM dirSign)");

  params.addRequiredParam<Real>("P_weld", "Arc power [W] (before efficiency)");
  params.addParam<Real>("eta", 1.0, "Arc efficiency");
  params.addRequiredParam<Real>("ff", "Goldak front fraction");
  params.addRequiredParam<Real>("fr", "Goldak rear fraction");
  params.addParam<Real>("split_epsilon",
                        -1.0,
                        "Front/rear tanh split width [m] (FreeFEM epsSplit); "
                        "< 0 falls back to max(0.1 * min(af, ar), 1e-9)");
  return params;
}

WAAMToolpathUO::WAAMToolpathUO(const InputParameters & parameters)
  : GeneralUserObject(parameters),
    _toolpath_file(getParam<FileName>("toolpath_file")),
    _layer_times_file(getParam<FileName>("layer_times_file")),
    _hz_base(getParam<Real>("hz_base")),
    _h_first(getParam<Real>("h_bead_first")),
    _h_sub(getParam<Real>("h_bead_sub")),
    _match_tol_frac(getParam<Real>("match_tol_frac")),
    _dwell_time(getParam<Real>("dwell_time")),
    _af(getParam<Real>("af")),
    _ar(getParam<Real>("ar")),
    _bG(getParam<Real>("bG")),
    _cG(getParam<Real>("cG")),
    _z_frac(getParam<Real>("z_activation_frac")),
    _bidirectional(getParam<bool>("bidirectional")),
    _p_weld(getParam<Real>("P_weld")),
    _eta(getParam<Real>("eta")),
    _ff(getParam<Real>("ff")),
    _fr(getParam<Real>("fr")),
    _split_epsilon(getParam<Real>("split_epsilon")),
    _psi_data(declareRestartableData<std::vector<char>>("psi_data")),
    _consolidated(declareRestartableData<std::vector<char>>("consolidated"))
{
  if (_af <= 0.0 || _ar <= 0.0 || _bG <= 0.0 || _cG <= 0.0)
    paramError("af", "Goldak semi-axes must be positive");
  if (_p_weld <= 0.0)
    paramError("P_weld", "Arc power must be positive");
  if (std::abs(_ff + _fr - 2.0) > 1e-6)
    paramError("ff", "Goldak fractions must satisfy ff + fr = 2 (got ", _ff + _fr, ")");

  buildSchedule();
}

void
WAAMToolpathUO::initialize()
{
  buildSchedule();
}

void
WAAMToolpathUO::initialSetup()
{
  buildLedger();
}

void
WAAMToolpathUO::buildSchedule()
{
  if (_schedule_built)
    return;

  {
    std::ifstream in(_toolpath_file.c_str());
    if (!in.good())
      mooseError("WAAMToolpathUO: cannot open toolpath file '", _toolpath_file, "'");

    std::string line;
    std::getline(in, line);
    std::vector<std::string> header;
    MooseUtils::tokenize(line, header, 1, " \t\r");
    if (header.size() != 1)
      mooseError("WAAMToolpathUO: malformed toolpath header '", line, "'");
    const std::size_t n_rows = std::stoul(header[0]);

    _tp_t.reserve(n_rows);
    _tp_p.reserve(n_rows);
    _tp_state.reserve(n_rows);
    std::vector<std::string> tok;
    while (std::getline(in, line))
    {
      if (line.empty())
        continue;
      MooseUtils::tokenize(line, tok, 1, " \t\r");
      if (tok.size() < 5)
        mooseError("WAAMToolpathUO: malformed toolpath row '", line, "'");
      _tp_t.push_back(std::stod(tok[0]));
      _tp_p.emplace_back(std::stod(tok[1]), std::stod(tok[2]), std::stod(tok[3]));
      _tp_state.push_back(std::stoi(tok[4]) > 0 ? 1 : 0);
    }
    if (_tp_t.size() < 2 || _tp_t.size() != n_rows)
      mooseError("WAAMToolpathUO: toolpath declares ",
                 n_rows,
                 " rows but ",
                 _tp_t.size(),
                 " were read");
    for (std::size_t i = 1; i < _tp_t.size(); ++i)
      if (_tp_t[i] < _tp_t[i - 1] - 1e-12)
        mooseError("WAAMToolpathUO: toolpath times are not non-decreasing at row ", i);
  }

  {
    std::ifstream in(_layer_times_file.c_str());
    if (!in.good())
      mooseError("WAAMToolpathUO: cannot open layer times file '", _layer_times_file, "'");

    std::string line;
    std::getline(in, line);
    std::vector<std::string> header;
    MooseUtils::tokenize(line, header, 1, " \t\r");
    _n_layers = std::stoi(header[0]);
    _pass_time.assign(_n_layers, 0.0);
    int read = 0;
    std::vector<std::string> tok;
    while (std::getline(in, line))
    {
      if (line.empty())
        continue;
      MooseUtils::tokenize(line, tok, 1, " \t\r");
      if (tok.size() < 2)
        mooseError("WAAMToolpathUO: malformed layer times row '", line, "'");
      const int idx = std::stoi(tok[0]);
      if (idx < 1 || idx > _n_layers)
        mooseError("WAAMToolpathUO: layer index ", idx, " out of range");
      _pass_time[idx - 1] = std::stod(tok[1]);
      ++read;
    }
    if (read != _n_layers)
      mooseError("WAAMToolpathUO: expected ", _n_layers, " layer pass times, read ", read);
  }

  _zc.assign(_n_layers, 0.0);
  _zh.assign(_n_layers, 0.0);
  _lay_sta.assign(_n_layers, -1);
  _lay_end.assign(_n_layers, -1);

  for (int l = 0; l < _n_layers; ++l)
  {
    _zh[l] = (l == 0) ? _h_first : _h_sub;
    _zc[l] = (l == 0) ? _hz_base + 0.5 * _h_first
                      : _hz_base + _h_first + (l - 1) * _h_sub + 0.5 * _h_sub;
    const Real tol = _match_tol_frac * _zh[l];
    for (std::size_t j = 0; j < _tp_t.size(); ++j)
      if (std::abs(_tp_p[j](2) - _zc[l]) <= tol)
      {
        if (_lay_sta[l] < 0)
          _lay_sta[l] = cast_int<int>(j);
        _lay_end[l] = cast_int<int>(j);
      }
    if (_lay_sta[l] < 0)
      mooseError("WAAMToolpathUO: no toolpath rows match layer ",
                 l + 1,
                 " z-center ",
                 _zc[l],
                 " (tol ",
                 tol,
                 "); re-slice with the current slicer");
    if (l > 0 && _lay_sta[l] <= _lay_end[l - 1])
      mooseError("WAAMToolpathUO: layer ", l + 1, " row window overlaps layer ", l);
  }

  _layer_start.assign(_n_layers, 0.0);
  for (int l = 1; l < _n_layers; ++l)
    _layer_start[l] = _layer_start[l - 1] + _pass_time[l - 1] + _dwell_time;

  _z_consol.assign(_n_layers, 0.0);
  for (int l = 0; l < _n_layers; ++l)
    _z_consol[l] = std::max(_zc[l] + 0.5 * _zh[l], _tp_p[_lay_end[l]](2) + 0.5 * _zh[l]) + 1e-5;

  _schedule_built = true;
}

void
WAAMToolpathUO::buildLedger()
{
  if (_ledger_built)
    return;

  _layer_bins.assign(_n_layers, {});
  _node_pts.clear();
  _nodes_by_z.clear();
  _elem_nodes.clear();
  _deposit_elems.clear();

  const dof_id_type n_nodes = _fe_problem.mesh().getMesh().max_node_id();
  if (_app.isRestarting() || _app.isRecovering())
  {
    if (_psi_data.size() != n_nodes)
      mooseError("WAAMToolpathUO: restart ledger size (",
                 _psi_data.size(),
                 ") does not match mesh node count (",
                 n_nodes,
                 "); the mesh must be identical across a restart");
  }
  else
  {
    _psi_data.assign(n_nodes, 0);
    _consolidated.assign(_n_layers, 0);
    for (const auto & node : _fe_problem.mesh().getMesh().active_node_ptr_range())
      if (node->id() < n_nodes && (*node)(2) <= _hz_base + 1e-6)
        _psi_data[node->id()] = 1;
  }

  for (const auto & elem : _fe_problem.mesh().getMesh().active_element_ptr_range())
  {
    const Point c = elem->vertex_average();
    const dof_id_type eid = elem->id();

    std::vector<dof_id_type> nids;
    std::vector<Point> npts;
    nids.reserve(elem->n_vertices());
    npts.reserve(elem->n_vertices());
    for (unsigned int v = 0; v < elem->n_vertices(); ++v)
    {
      nids.push_back(elem->node_ref(v).id());
      npts.push_back(elem->point(v));
    }
    _elem_nodes[eid] = nids;

    if (c(2) <= _hz_base + 1e-9)
      continue;
    _deposit_elems.push_back(eid);

    for (std::size_t k = 0; k < nids.size(); ++k)
    {
      const dof_id_type nid = nids[k];
      if (_node_pts.count(nid))
        continue;

      const Point & np = npts[k];
      _node_pts.emplace(nid, np);

      if (np(2) <= _hz_base + 1e-6)
        continue; // substrate node: implicitly active

      _nodes_by_z.emplace_back(np(2), nid);

      for (int l = 0; l < _n_layers; ++l)
      {
        const Real z_band = std::max(_cG, _z_frac * _zh[l]);
        if (std::abs(np(2) - _zc[l]) <= z_band + 0.5 * _zh[l])
          _layer_bins[l].push_back(nid);
      }
    }
  }

  if (_deposit_elems.empty())
    mooseError("WAAMToolpathUO: no deposit elements found above hz_base");
  std::sort(_nodes_by_z.begin(), _nodes_by_z.end());
  _ledger_built = true;
}

WAAMTorchState
WAAMToolpathUO::torchStateAt(Real t) const
{
  WAAMTorchState st;
  if (_n_layers <= 0)
    return st;

  int l_next = -1;
  for (int k = 0; k < _n_layers; ++k)
    if (t < _layer_start[k] + _pass_time[k])
    {
      l_next = k;
      break;
    }

  const bool in_pass = (l_next >= 0) && (t >= _layer_start[l_next]);
  const int l = in_pass ? l_next : (l_next < 0 ? _n_layers - 1 : std::max(l_next - 1, 0));

  st.layer = l;
  st.in_pass = in_pass;
  st.t_local = in_pass ? (t - _layer_start[l]) : _pass_time[l];

  const int j0 = _lay_sta[l];
  const int j1 = _lay_end[l];
  const Real t_win = _tp_t[j1] - _tp_t[j0];
  st.t_gcode = _tp_t[j0] + std::min(st.t_local, std::max(t_win, 0.0));

  int seg = j0;
  for (int i = j0; i < j1; ++i)
    if (st.t_gcode >= _tp_t[i] && st.t_gcode <= _tp_t[i + 1])
    {
      seg = i;
      break;
    }
  seg = std::min(seg, j1 - 1);
  st.segment = cast_int<unsigned int>(seg);

  const int i2 = std::min(seg + 1, j1);
  const Real dt = _tp_t[i2] - _tp_t[seg];
  st.seg_frac = (dt > 1e-12) ? (st.t_gcode - _tp_t[seg]) / dt : 0.0;
  st.seg_frac = std::min(std::max(st.seg_frac, 0.0), 1.0);
  st.position = _tp_p[seg] * (1.0 - st.seg_frac) + _tp_p[i2] * st.seg_frac;
  const bool in_window = (st.t_local <= t_win + 1e-9);
  // FreeFEM's first weld sample is at tLocal = dt > 0 and dwell steps carry
  // Tsource = 0, so the exact pass-start instant (t_local == 0) is silent --
  // the dwell's final step lands exactly on the next layer_start and must not
  // report the upcoming layer's row pState as arc-on.
  st.p_state = (st.in_pass && in_window && st.t_local > 1e-9)
                   ? (_tp_state[i2] > 0 ? 1.0 : 0.0)
                   : 0.0;

  return st;
}

Point
WAAMToolpathUO::segmentDirection(unsigned int i) const
{
  const unsigned int i2 = std::min<unsigned int>(i + 1, _tp_t.size() - 1);
  Point d = _tp_p[i2] - _tp_p[i];
  const Real n = d.norm();
  if (n < 1e-12)
    return Point(1.0, 0.0, 0.0);
  return d / n;
}

Real
WAAMToolpathUO::gateInstant(const Point & point, Real t) const
{
  if (point(2) <= _hz_base + 1e-6)
    return 1.0;

  const WAAMTorchState st = torchStateAt(t);
  if (st.layer < 0)
    return 0.0;

  const Real dx = point(0) - st.position(0);
  const Real dy = point(1) - st.position(1);
  const Real dz = point(2) - st.position(2);

  if (dx * dx / (_af * _af) + dy * dy / (_bG * _bG) > 1.0)
    return 0.0;

  const Real z_band = std::max(_cG, _z_frac * _zh[st.layer]);
  return (std::abs(dz) <= z_band) ? 1.0 : 0.0;
}

void
WAAMToolpathUO::advanceActivation(const WAAMTorchState & st)
{
  // FreeFEM's first gate sample inside a layer happens at tLocal = dt > 0
  // (tLocal = 0 is the pre-weld state), and dwells perform no sampling.
  if (st.layer < 0 || !st.in_pass || st.t_local <= 1e-9)
    return;

  const int l = st.layer;
  const Real z_band = std::max(_cG, _z_frac * _zh[l]);
  const Real xt = st.position(0);
  const Real yt = st.position(1);
  const Real zt = st.position(2);

  for (const auto nid : _layer_bins[l])
  {
    if (nid >= _psi_data.size() || _psi_data[nid])
      continue;

    const Point & p = _node_pts[nid];
    if (std::abs(p(2) - zt) > z_band)
      continue;

    const Real dx = p(0) - xt;
    const Real dy = p(1) - yt;
    if (dx * dx / (_af * _af) + dy * dy / (_bG * _bG) <= 1.0)
      _psi_data[nid] = 1;
  }
}

void
WAAMToolpathUO::consolidateLayers(Real t)
{
  for (int l = 0; l < _n_layers; ++l)
  {
    // Strictly past the pass end: the last weld step's own assembly does not yet
    // see the consolidation, exactly like the FreeFEM post-loop placement.
    if (_consolidated[l] || t <= _layer_start[l] + _pass_time[l] + 1e-9)
      continue;

    for (const auto & entry : _nodes_by_z)
    {
      if (entry.first > _z_consol[l])
        break;
      if (entry.second < _psi_data.size())
        _psi_data[entry.second] = 1;
    }
    _consolidated[l] = 1;
  }
}

void
WAAMToolpathUO::execute()
{
  buildLedger();
  const WAAMTorchState st = torchStateAt(_t);
  advanceActivation(st);
  consolidateLayers(_t);
}

Real
WAAMToolpathUO::psiNode(dof_id_type node_id) const
{
  if (node_id >= _psi_data.size())
    return 1.0;
  return _psi_data[node_id] ? 1.0 : 0.0;
}

Real
WAAMToolpathUO::faCumulative(dof_id_type elem_id) const
{
  const auto it = _elem_nodes.find(elem_id);
  if (it == _elem_nodes.end())
    return 1.0;

  unsigned int n = 0;
  unsigned int act = 0;
  for (const auto nid : it->second)
  {
    ++n;
    if (psiNode(nid) >= 0.5)
      ++act;
  }
  return (2 * act > n) ? 1.0 : 0.0;
}

unsigned int
WAAMToolpathUO::numActiveCumulative() const
{
  unsigned int n = 0;
  for (const auto eid : _deposit_elems)
    if (faCumulative(eid) >= 0.5)
      ++n;
  return n;
}

Real
WAAMToolpathUO::psiAt(dof_id_type node_id, Real t) const
{
  if (node_id < _psi_data.size() && _psi_data[node_id])
    return 1.0;

  // Consolidation reached by t: planes grow with l, so the highest finished
  // layer dominates (strictly past its pass end, matching FreeFEM placement).
  int l_done = -1;
  for (int l = _n_layers - 1; l >= 0; --l)
    if (t > _layer_start[l] + _pass_time[l] + 1e-9)
    {
      l_done = l;
      break;
    }
  if (l_done >= 0)
  {
    const auto it = _node_pts.find(node_id);
    const Real z = (it != _node_pts.end()) ? it->second(2) : _hz_base;
    if (z <= _z_consol[l_done])
      return 1.0;
  }

  const WAAMTorchState st = torchStateAt(t);
  if (st.layer < 0 || !st.in_pass || st.t_local <= 1e-9)
    return 0.0;

  const auto it = _node_pts.find(node_id);
  if (it == _node_pts.end())
    return 0.0;

  const Point & p = it->second;
  if (p(2) <= _hz_base + 1e-6)
    return 1.0;

  const Real z_band = std::max(_cG, _z_frac * _zh[st.layer]);
  if (std::abs(p(2) - st.position(2)) > z_band)
    return 0.0;

  const Real dx = p(0) - st.position(0);
  const Real dy = p(1) - st.position(1);
  return (dx * dx / (_af * _af) + dy * dy / (_bG * _bG) <= 1.0) ? 1.0 : 0.0;
}

Real
WAAMToolpathUO::faAt(dof_id_type elem_id, Real t) const
{
  const auto it = _elem_nodes.find(elem_id);
  if (it == _elem_nodes.end())
    return 1.0;

  unsigned int n = 0;
  unsigned int act = 0;
  for (const auto nid : it->second)
  {
    ++n;
    if (psiAt(nid, t) >= 0.5)
      ++act;
  }
  return (2 * act > n) ? 1.0 : 0.0;
}

unsigned int
WAAMToolpathUO::numActiveAt(Real t) const
{
  unsigned int n = 0;
  for (const auto eid : _deposit_elems)
    if (faAt(eid, t) >= 0.5)
      ++n;
  return n;
}

Real
WAAMToolpathUO::goldakQ(const Point & p, Real t, Real elem_length) const
{
  (void)elem_length;

  const WAAMTorchState st = torchStateAt(t);
  if (st.p_state < 0.5)
    return 0.0;

  const Real dir_sign = (_bidirectional && (st.layer % 2 == 1)) ? -1.0 : 1.0;

  const Real dx = p(0) - st.position(0);
  const Real dy = p(1) - st.position(1);
  const Real dz = p(2) - st.position(2);

  Real eps = _split_epsilon;
  if (eps <= 0.0)
    eps = std::max(0.1 * std::min(_af, _ar), 1e-9);

  const Real P = arcPower();
  const Real q0f = 3.0 * std::sqrt(3.0) * _ff * P /
                   (libMesh::pi * std::sqrt(libMesh::pi) * _af * _bG * _cG);
  const Real q0r = 3.0 * std::sqrt(3.0) * _fr * P /
                   (libMesh::pi * std::sqrt(libMesh::pi) * _ar * _bG * _cG);

  const Real xi = dir_sign * dx;
  const Real front = 0.5 * (1.0 + std::tanh(xi / eps));
  const Real rear = 1.0 - front;

  return (q0f * std::exp(-3.0 * dx * dx / (_af * _af)) * front +
          q0r * std::exp(-3.0 * dx * dx / (_ar * _ar)) * rear) *
         std::exp(-3.0 * dy * dy / (_bG * _bG)) *
         std::exp(-3.0 * dz * dz / (_cG * _cG));
}
