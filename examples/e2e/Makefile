GOAL ?= goal.md
export PYTHONPATH := $(abspath ../..):$(PYTHONPATH)
AGENT := python3 -m panoptes.e2e_agent
include ../../vendor/create-mvp/build.mk
$(B)/plan.json: ../../panoptes/e2e_agent.py ../../panoptes/corpus.py $(wildcard ../../panoptes/data/*)
$(B)/audit.done: ../../panoptes/_vendor/hermes_scaffold.py
