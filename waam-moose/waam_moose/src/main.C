//* WAAM-MOOSE application
//* The MOOSE lane of the WAAM framework (see moose.md / moose_v2.md).

#include "WAAMApp.h"
#include "MooseMain.h"

int
main(int argc, char * argv[])
{
  return Moose::main<WAAMApp>(argc, argv);
}
