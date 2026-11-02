//* WAAM-MOOSE application
//* The MOOSE lane of the WAAM framework (see moose.md / moose_v2.md).

#include "WAAMApp.h"
#include "Factory.h"
#include "ActionFactory.h"
#include "AppFactory.h"
#include "MooseSyntax.h"
#include "Registry.h"

// Physics modules
#include "HeatTransferApp.h"
#include "HeatConductionApp.h"
#include "SolidMechanicsApp.h"

InputParameters
WAAMApp::validParams()
{
  InputParameters params = MooseApp::validParams();

  params.set<bool>("automatic_automatic_scaling") = false;
  params.set<bool>("use_legacy_material_output") = false;
  params.set<bool>("use_legacy_initial_residual_evaluation_behavior") = false;

  return params;
}

registerKnownLabel("WAAMApp");

WAAMApp::WAAMApp(InputParameters parameters) : MooseApp(parameters)
{
  WAAMApp::registerAll(_factory, _action_factory, _syntax);
}

WAAMApp::~WAAMApp() {}

void
WAAMApp::registerApps()
{
  registerApp(WAAMApp);
  HeatConductionApp::registerApps();
  HeatTransferApp::registerApps();
  SolidMechanicsApp::registerApps();
}

void
WAAMApp::registerAll(Factory & f, ActionFactory & af, Syntax & s)
{
  Registry::registerObjectsTo(f, {"WAAMApp"});
  Registry::registerActionsTo(af, {"WAAMApp"});

  HeatConductionApp::registerAll(f, af, s);
  HeatTransferApp::registerAll(f, af, s);
  SolidMechanicsApp::registerAll(f, af, s);
}

extern "C" void
WAAMApp__registerAll(Factory & f, ActionFactory & af, Syntax & s)
{
  WAAMApp::registerAll(f, af, s);
}

extern "C" void
WAAMApp__registerApps()
{
  WAAMApp::registerApps();
}
