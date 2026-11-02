#pragma once

#include "GeneralUserObject.h"
#include "MooseMesh.h"

class AuxiliarySystem;

/// FreeFEM-parity post-solve nodal clip.
///
/// The generated FreeFEM program runs the following after EVERY linear solve,
/// and it is central to the baseline's behaviour, not a numerical afterthought:
///
///     Temp = max(Temp, Tamb);                  // no undershoot, ever
///     if (psiActive < 0.5) Temp = Tamb;        // quiet nodes held at ambient
///     if (Temp >= Tboil) Temp = Tboil;         // no overshoot, ever
///     Tpeak = max(Tpeak, Temp);                // peak tracker (separate field)
///
/// MOOSE has no post-solve nodal assignment, so this Corrector reproduces the
/// clip exactly: after the nonlinear solve it rewrites the current (and old /
/// older) temperature solution states on every local node so that the audited
/// field matches the FreeFEM baseline's [Tamb, Tboil] band and quiet-node hold.
///
/// This is the literal FreeFEM port (documented MOOSE mechanism: see
/// framework/doc/content/syntax/Correctors/index.md). It is complemented by
/// WAAMBoilingCapKernel (smooth in-solve upper relaxation so Newton sees the
/// cap) and WAAMLumpedHeatTimeDerivative (lump-mass time integration, which
/// removes the P1 moving-source ringing at its root so the clip rarely fires).
/// All solution states must be updated together, or the next step's time
/// derivative sees an inconsistent old value and re-introduces a spike; the
/// three-state loop below follows PointwiseRenormalizeVector.
class WAAMFreeFEMClip : public GeneralUserObject
{
public:
  static InputParameters validParams();

  WAAMFreeFEMClip(const InputParameters & parameters);

  void initialize() override;
  void execute() override;
  void finalize() override;

  void threadJoin(const UserObject &) override {}

protected:
  /// reference to the mesh
  MooseMesh & _mesh;

  /// bounded temperature variable name
  const VariableName _var_name;
  /// internal variable number
  unsigned int _var_number;
  /// nodal activation field name (auxiliary system)
  const VariableName _psi_name;
  /// internal psi variable number in the auxiliary system
  unsigned int _psi_number;

  const Real _ambient;
  const Real _boiling;
  const Real _psi_threshold;

  /// the auxiliary system holding psi (temperature lives in the nonlinear system)
  AuxiliarySystem & _aux;
};
