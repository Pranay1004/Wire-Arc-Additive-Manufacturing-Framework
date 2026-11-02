###############################################################################
################### MOOSE Application Standard Makefile #######################
###############################################################################
#
# WAAM-MOOSE: the MOOSE lane of the WAAM framework.
# Uses the prebuilt MOOSE tree on this machine (see core/BUILD_NOTES.md).
#
###############################################################################

MOOSE_DIR          ?= /Users/pandeyji/projects/moose
FRAMEWORK_DIR      := $(MOOSE_DIR)/framework
MODULE_DIR         := $(MOOSE_DIR)/modules

include $(FRAMEWORK_DIR)/build.mk
include $(FRAMEWORK_DIR)/moose.mk

################################## MODULES ####################################
# Physics modules linked into the app (libs are prebuilt in the tree).
HEAT_TRANSFER      := yes
SOLID_MECHANICS    := yes
include $(MODULE_DIR)/modules.mk
###############################################################################

APPLICATION_DIR    := $(CURDIR)
APPLICATION_NAME   := waam_moose
BUILD_EXEC         := yes
GEN_REVISION       := no
include            $(FRAMEWORK_DIR)/app.mk
