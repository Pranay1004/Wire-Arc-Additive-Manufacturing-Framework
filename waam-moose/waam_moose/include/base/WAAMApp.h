//* WAAM-MOOSE application
//* The MOOSE lane of the WAAM framework (see moose.md / moose_v2.md).
//* Registration of the app + the physics modules it links against.

#pragma once

#include "MooseApp.h"

class WAAMApp : public MooseApp
{
public:
  static InputParameters validParams();

  WAAMApp(InputParameters parameters);
  virtual ~WAAMApp();

  static void registerApps();
  static void registerAll(Factory & f, ActionFactory & af, Syntax & s);
};
