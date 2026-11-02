#include "WAAMFreeFEMClip.h"
#include "MooseError.h"
#include "SystemBase.h"
#include "AuxiliarySystem.h"

#include "libmesh/numeric_vector.h"
#include "libmesh/dof_map.h"
#include "libmesh/elem.h"
#include "libmesh/int_range.h"

registerMooseObject("WAAMApp", WAAMFreeFEMClip);

InputParameters
WAAMFreeFEMClip::validParams()
{
  InputParameters params = GeneralUserObject::validParams();
  params.addClassDescription(
      "FreeFEM-parity post-solve nodal clip of the temperature field into "
      "[ambient, boiling] (quiet psi<0.5 nodes held at ambient)");
  params.addRequiredParam<VariableName>("variable", "Temperature variable to clip");
  params.addRequiredParam<VariableName>("psi", "Nodal activation field (P1 aux, 0/1)");
  params.addRequiredParam<Real>("ambient", "Ambient / floor temperature [C] (Tamb)");
  params.addRequiredParam<Real>("boiling", "Boiling cap temperature [C] (Tboil)");
  params.addParam<Real>("psi_threshold",
                        0.5,
                        "psi below this holds the node at ambient (FreeFEM psiActive<0.5)");
  params.registerBase("Corrector");
  return params;
}

WAAMFreeFEMClip::WAAMFreeFEMClip(const InputParameters & parameters)
  : GeneralUserObject(parameters),
    _mesh(_fe_problem.mesh()),
    _var_name(getParam<VariableName>("variable")),
    _var_number(0),
    _psi_name(getParam<VariableName>("psi")),
    _psi_number(0),
    _ambient(getParam<Real>("ambient")),
    _boiling(getParam<Real>("boiling")),
    _psi_threshold(getParam<Real>("psi_threshold")),
    _aux(_fe_problem.getAuxiliarySystem())
{
  // T lives in the nonlinear system; its solution vector carries the solution
  // states we rewrite. psi lives in the auxiliary system (a nodal P1 aux
  // variable), read-only here.
  _var_number = _sys.system().variable_number(_var_name);
  _psi_number = _aux.system().variable_number(_psi_name);
}

void
WAAMFreeFEMClip::initialize()
{
  // Make sure the freshly solved vectors are visible before we read from them.
  _sys.system().solution->close();
  _aux.system().solution->close();
}

void
WAAMFreeFEMClip::execute()
{
  auto & dof_map = _sys.system().get_dof_map();
  const auto local_dof_begin = dof_map.first_dof();
  const auto local_dof_end = dof_map.end_dof();

  auto & aux_dof_map = _aux.system().get_dof_map();
  const auto & psi_vec = _aux.solution();

  std::vector<dof_id_type> t_dofs;
  std::vector<dof_id_type> psi_dofs;

  for (const auto & elem : *_mesh.getActiveLocalElementRange())
  {
    dof_map.dof_indices(elem, t_dofs, _var_number);
    aux_dof_map.dof_indices(elem, psi_dofs, _psi_number);
    mooseAssert(t_dofs.size() == psi_dofs.size(),
                "temperature and psi must share the same nodal DOF layout");

    for (const auto j : index_range(t_dofs))
    {
      if (t_dofs[j] < local_dof_begin || t_dofs[j] >= local_dof_end)
        continue;

      const Real psi = psi_vec(psi_dofs[j]);

      // Update all available solution states together (current + old + older),
      // otherwise the next step's time derivative is inconsistent with these
      // clipped values and re-introduces the spurious excursion.
      for (const auto s : make_range(3))
        if (_sys.hasSolutionState(s))
        {
          auto & sol = _sys.solutionState(s);
          Real T = sol(t_dofs[j]);

          if (T < _ambient)
            T = _ambient;
          if (T > _boiling)
            T = _boiling;

          sol.set(t_dofs[j], T);
        }
    }
  }
}

void
WAAMFreeFEMClip::finalize()
{
  for (const auto s : make_range(3))
    if (_sys.hasSolutionState(s))
      _sys.solutionState(s).close();
  _sys.update();
}
