#pragma once

#include "BoundsBase.h"

/// FreeFEM-parity temperature bounds for the PETSc variational-inequality
/// solver (snes_type = vinewtonrsls).
///
/// The FreeFEM .edp clips the nodal field after every linear solve:
///
///     if (Temp < Tamb)        Temp = Tamb;       // no undershoot
///     if (psiActive < 0.5)    Temp = Tamb;       // hold quiet nodes at Tamb
///     if (Temp >= Tboil)      Temp = Tboil;      // no overshoot
///
/// A MOOSE Corrector cannot reproduce this: postprocessors are element user
/// objects and run BEFORE general user objects in the timestep_end batch, so
/// tmin/tmax sample the raw (unclipped) field (measured -267 C in the CSV even
/// though the clip itself provably works). Bounds instead constrain the
/// solution INSIDE the SNES solve, so every postprocessor, output and the next
/// step's residual all see the clipped field with no ordering games.
///
/// This object sets ONE side of that band per active node:
///   upper bound: quiet node -> Tamb ; active node -> Tboil
///   lower bound: quiet node -> Tamb ; active node -> Tamb
/// so a quiet node is pinned to [Tamb, Tamb] and an active node to
/// [Tamb, Tboil] -- exactly the FreeFEM post-solve clip, enforced variationally.
class WAAMFreeFEMBounds : public BoundsBase
{
public:
  static InputParameters validParams();

  WAAMFreeFEMBounds(const InputParameters & parameters);

protected:
  virtual Real getBound() override;

  /// nodal activation field (P1 aux, 0/1)
  const VariableValue & _psi;
  /// psi below this is treated as a quiet / unactivated node
  const Real _psi_threshold;
  /// ambient / floor temperature [C]
  const Real _ambient;
  /// boiling cap temperature [C]
  const Real _boiling;
};
