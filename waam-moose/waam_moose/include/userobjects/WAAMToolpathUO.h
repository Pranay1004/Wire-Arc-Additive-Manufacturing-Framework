#pragma once

#include "GeneralUserObject.h"

#include <map>
#include <utility>
#include <vector>

/// Torch state returned by WAAMToolpathUO queries.
struct WAAMTorchState
{
  unsigned int segment = 0;   //!< toolpath row index of the segment start
  Real seg_frac = 0.0;        //!< fraction along the current segment [0, 1]
  int layer = -1;             //!< current layer (last finished layer during dwell)
  bool in_pass = false;       //!< true while inside a layer weld-pass window
  Real t_local = 0.0;         //!< time inside the layer pass window [s]
  Real t_gcode = 0.0;         //!< mapped toolpath-clock time [s]
  Real p_state = 0.0;         //!< 1 = welding (arc on), 0 = rapid / dwell
  Point position;             //!< torch position (SI metres)
};

/// Slicer toolpath + FreeFEM-parity activation ledger.
///
/// Semantics replicated from the generated FreeFEM program (edp_builder):
///
///  * Layer mapping: rows bucketed per layer by z-match against
///    zc(l) = hz_base + 0.5*h_first (l=0) / hz_base + h_first +
///    (l-1)*h_sub + 0.5*h_sub, tol = match_tol_frac * layer height.  Within a
///    layer window tLocal in [0, tPass] maps 1:1 onto the row window
///    [tpT[j0], tpT[j1]] anchored at j0 (row-wise clock skip of inter-pass
///    dwell rows; no phase drift).
///  * Arc gating: pState = tpP[idx2] (state of the move ENDING at the
///    segment's second endpoint), zero outside the window/dwells.
///  * Activation ledger is NODE-cumulative (psi per mesh node, exactly like
///    the FreeFEM P1 field): at every execute (i.e. at the simulation step
///    times, matching the FreeFEM per-step gate sampling) every deposit node
///    inside ((x-xT)^2/af^2 + (y-yT)^2/bG^2 <= 1) && |z-zT| <=
///    max(cG, z_frac*h_l) is marked active -- binary, cumulative, IGNORES
///    pState (rapids inside a layer activate too).  Substrate nodes
///    (z <= hz_base + 1e-6) are active from t = 0.
///  * After each layer pass, all nodes with z <= max(z_top, z_torch_end +
///    h/2) + 1e-5 activate (consolidation).
///  * Element birth mask = majority vote of its nodes (P0 projection of the
///    P1 psi field: count/4 > 0.5).  Element source / conduction masks and
///    materials apply their own floors (1e-5 birth, 1e-4 conductivity).
///  * Restart: the ledger and consolidation flags are restartable data
///    (vector<char> per node), so interrupted runs resume bit-identically.
class WAAMToolpathUO : public GeneralUserObject
{
public:
  static InputParameters validParams();

  WAAMToolpathUO(const InputParameters & parameters);

  virtual void initialize() override;
  virtual void initialSetup() override;
  virtual void execute() override;
  virtual void finalize() override {}

  /// Torch / arc state at global simulation time t (clamped at the bounds).
  WAAMTorchState torchStateAt(Real t) const;

  /// Instantaneous activation gate at a point (binary, incl. substrate rule).
  Real gateInstant(const Point & point, Real t) const;

  /// Cumulative per-node activation (FreeFEM psi): 1 = active.
  Real psiNode(dof_id_type node_id) const;

  /// Cumulative element birth mask (majority of nodes); substrate / unknown
  /// elements return 1.
  Real faCumulative(dof_id_type elem_id) const;

  /// Activation of a node at time ``t`` as a pure function of the schedule:
  /// persisted ledger OR the instantaneous gate at ``t`` OR layer
  /// consolidation reached by ``t``.  With ``t`` = the current step's new time
  /// this reproduces FreeFEM's per-step assembly state exactly (the gate of
  /// step n is visible to step n's own assembly).
  Real psiAt(dof_id_type node_id, Real t) const;

  /// Element birth mask (node majority) at time ``t`` (see psiAt).
  Real faAt(dof_id_type elem_id, Real t) const;

  /// Number of deposit elements whose majority is active at time ``t``.
  unsigned int numActiveAt(Real t) const;

  /// Un-gated Goldak double-ellipsoid volumetric power density [W/m^3] with
  /// the FreeFEM-parity tanh front/rear split along +/-x by layer parity.
  /// ``elem_length`` is unused by the parity formula (kept for interface
  /// stability); eps defaults to max(0.1*min(af,ar), split_epsilon).
  Real goldakQ(const Point & p, Real t, Real elem_length = 0.0) const;

  /// Effective arc power P_weld * eta [W].
  Real arcPower() const { return _p_weld * _eta; }

  /// Number of deposit (non-substrate) elements tracked by the ledger.
  unsigned int numDepositElems() const { return cast_int<unsigned int>(_deposit_elems.size()); }

  /// Number of deposit elements whose node majority is active.
  unsigned int numActiveCumulative() const;

  unsigned int segmentCount() const { return _tp_t.size(); }
  const Point & segmentPoint(unsigned int i) const { return _tp_p[i]; }
  Real segmentTime(unsigned int i) const { return _tp_t[i]; }
  int layerCount() const { return _n_layers; }

  /// Weld-pass wall time of layer l [s] (tPass in the FreeFEM schedule).
  Real passTime(unsigned int l) const { return _pass_time[l]; }
  /// Simulation time at which layer l's weld pass starts [s].
  Real layerStart(unsigned int l) const { return _layer_start[l]; }
  /// Dwell staircase cap between layers [s] (dtWait).
  Real dwellTime() const { return _dwell_time; }

  /// Direction of travel of toolpath segment i (unit vector; +x fallback).
  Point segmentDirection(unsigned int i) const;

protected:
  void buildSchedule();
  void buildLedger();
  void advanceActivation(const WAAMTorchState & st);
  void consolidateLayers(Real t);

  const FileName & _toolpath_file;
  const FileName & _layer_times_file;
  const Real _hz_base;
  const Real _h_first;
  const Real _h_sub;
  const Real _match_tol_frac;
  const Real _dwell_time;

  const Real _af;
  const Real _ar;
  const Real _bG;
  const Real _cG;
  const Real _z_frac;
  const bool _bidirectional;

  const Real _p_weld;
  const Real _eta;
  const Real _ff;
  const Real _fr;
  const Real _split_epsilon;

  std::vector<Real> _tp_t;
  std::vector<Point> _tp_p;
  std::vector<int> _tp_state;

  int _n_layers = 0;
  std::vector<Real> _pass_time;
  std::vector<Real> _layer_start;
  std::vector<int> _lay_sta;
  std::vector<int> _lay_end;
  std::vector<Real> _zc;
  std::vector<Real> _zh;
  std::vector<Real> _z_consol; // per-layer consolidation plane [m]

  std::vector<std::vector<dof_id_type>> _layer_bins; // candidate NODE ids per layer
  std::map<dof_id_type, Point> _node_pts;            // tracked deposit node coords
  std::vector<std::pair<Real, dof_id_type>> _nodes_by_z;
  std::map<dof_id_type, std::vector<dof_id_type>> _elem_nodes;
  std::vector<dof_id_type> _deposit_elems;

  /// Restartable ledgers: per-LibMesh-node-id activation (1 = active) and
  /// per-layer consolidation flags.
  std::vector<char> & _psi_data;
  std::vector<char> & _consolidated;

  bool _schedule_built = false;
  bool _ledger_built = false;
};
