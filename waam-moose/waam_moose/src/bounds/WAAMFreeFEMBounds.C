#include "WAAMFreeFEMBounds.h"

registerMooseObject("WAAMApp", WAAMFreeFEMBounds);

InputParameters
WAAMFreeFEMBounds::validParams()
{
  InputParameters params = BoundsBase::validParams();
  params.addClassDescription(
      "FreeFEM-parity temperature band via PETSc variational inequalities: active "
      "nodes in [Tamb, Tboil], quiet (psi<threshold) nodes pinned at Tamb");
  params.addRequiredCoupledVar("psi", "Nodal activation field (P1 aux, 0/1)");
  params.addParam<Real>("psi_threshold",
                        0.5,
                        "psi below this pins the node to the ambient bound (FreeFEM "
                        "psiActive<0.5 -> Tamb)");
  params.addRequiredParam<Real>("ambient", "Ambient / floor temperature [C] (Tamb)");
  params.addRequiredParam<Real>("boiling", "Boiling cap temperature [C] (Tboil)");
  return params;
}

WAAMFreeFEMBounds::WAAMFreeFEMBounds(const InputParameters & parameters)
  : BoundsBase(parameters),
    _psi(coupledValue("psi")),
    _psi_threshold(getParam<Real>("psi_threshold")),
    _ambient(getParam<Real>("ambient")),
    _boiling(getParam<Real>("boiling"))
{
  if (_boiling <= _ambient)
    paramError("boiling", "must exceed ambient");
}

Real
WAAMFreeFEMBounds::getBound()
{
  // _psi is a nodal field evaluated at the current node, so the quiet/active
  // decision is genuinely per-node (unlike an element-average shortcut).
  const Real psi = _psi[_qp];

  if (psi < _psi_threshold)
    // Quiet node: pin to ambient on BOTH sides. For the upper-bound object this
    // returns ambient; for the lower-bound object it also returns ambient, so
    // the node is held exactly at Tamb (FreeFEM `psiActive<0.5 -> Temp=Tamb`).
    return _ambient;

  // Active node: the upper-bound object caps at Tboil; the lower-bound object
  // floors at Tamb. Both are the FreeFEM clamp on the live region.
  return _type == UPPER ? _boiling : _ambient;
}
