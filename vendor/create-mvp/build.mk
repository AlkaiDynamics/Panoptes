# create-mvp engine — goal.md → effort → plan → components (parallel, dep-ordered) → review gate
#
# Effort budget (Phase 0): explicit TIER param (s|m|l), no classifier.
#   tier     | fanout | review_depth | model_hint | thinking
#   vague    | 2-3    | smoke        | small      | low
#   standard | 3-5    | standard     | default    | medium
#   prd      | 5-8    | full         | large      | high
# Consumption: fanout → plan prompt component count; model_hint/thinking →
#   pi flags (--model via MODEL_SMALL/MODEL_LARGE env, --thinking direct);
#   review_depth → review rubric (smoke: check.sh only … full: evals mandatory).
#
# Project Makefile is 3 lines:
#   GOAL ?= goal.md        # optional overrides: GOAL, B, SRC, AGENT
#   include engine/build.mk
#
# Nested decomposition (docs/rfc-nested.md): a plan component may be
# "kind":"composite" with a "sub_goal" — it becomes a full nested project at
# src/<id>/ running this same file. Bounds, all deterministic (not prompt trust):
#   AGENTMAKE_MAXDEPTH (default 3) — deeper composites forced to leaf
#   MAXTIER — subtree tier clamped to parent tier (monotone non-increasing)
#   MAXFANOUT (default 8) — plan gate rejects wider decompositions per level
#
SHELL := /bin/bash
.DELETE_ON_ERROR:  # failed agent ≠ done artifact

ENGINE := $(dir $(lastword $(MAKEFILE_LIST)))
GOAL  ?= goal.md
B     ?= build
SRC   ?= src
AGENT ?= $(ENGINE)agent
export GOAL B SRC   # agent adapter reads these

# ── Recursion bounds (rfc-nested §3a). Exported for the agent subprocess
# (prompt conditional), NOT for child make — child overrides ride the $(MAKE)
# command line (strongest origin; env would silently defeat the child's ?=).
# TIER: explicit budget — s|m|l (or vague|standard|prd). No classifier: user
# effort knob is a parameter, not an inference. Subtrees inherit parent tier
# through MAXTIER clamp.
TIER ?= standard
# MAXTIER: subtree tier ceiling (root unbounded). MAXFANOUT: top of prd
# fanout range, per-level tree-width insurance. No inline comments here —
# make keeps the trailing whitespace and a MAXTIER of "prd   " defeats the clamp.
AGENTMAKE_DEPTH    ?= 0
AGENTMAKE_MAXDEPTH ?= 3
MAXTIER            ?= prd
MAXFANOUT          ?= 8
export AGENTMAKE_DEPTH AGENTMAKE_MAXDEPTH MAXTIER
NEXT_DEPTH := $(shell expr $(AGENTMAKE_DEPTH) + 1)
AT_CAP     := $(shell [ $(AGENTMAKE_DEPTH) -ge $(AGENTMAKE_MAXDEPTH) ] && echo 1 || echo 0)

.PHONY: all progress graph clean

all: $(B)/report.md

# ── Phase 0: effort knobs from explicit TIER (deterministic, no agent — classifier
# removed; single source of truth for the knob table, MAXTIER clamp included)
$(B)/effort.json: $(GOAL) | $(B)
	jq -cn --arg t "$(TIER)" --arg max "$(MAXTIER)" 'def r: {"vague":0,"standard":1,"prd":2}; def row: {"vague": {tier:"vague",fanout:"2-3",review_depth:"smoke",model_hint:"small",thinking:"low"},"standard":{tier:"standard",fanout:"3-5",review_depth:"standard",model_hint:"default",thinking:"medium"},"prd":{tier:"prd",fanout:"5-8",review_depth:"full",model_hint:"large",thinking:"high"}}; if (r[$$t] // 1) > r[$$max] then row[$$max] else row[$$t] // row["standard"] end' > $@
	jq -e '(.tier|IN("vague","standard","prd")) and (.fanout|test("^[0-9]+-[0-9]+$$")) and (.review_depth|IN("smoke","standard","full")) and (.model_hint|IN("small","default","large")) and (.thinking|IN("off","low","medium","high"))' $@ > /dev/null   # gate: schema

# ── Phase 1: decomposition (agent, no tools)
$(B)/plan.json: $(GOAL) $(B)/effort.json
	$(AGENT) plan $< > $@
	jq -e --argjson maxf $(MAXFANOUT) 'def okid: type=="string" and test("^[a-z0-9][a-z0-9-]{0,63}$$"); (.components | length > 0 and length <= $$maxf) and all(.components[]; (.id|okid) and all(.deps[]?; okid) and ((.kind // "leaf") == "leaf" or (.sub_goal | type=="string" and length > 0)))' $@ > /dev/null   # gate: bounded fanout; composite ⇒ sub_goal; id/dep charset — ids splice into make targets + shell recipe lines via the jq template (LLM output = trust boundary)

# ── Phase 2: plan generates the DAG — dep edges come from the agent
# Fork per component kind (rfc-nested §3b): leaf → build agent; composite →
# scaffold subtree + recurse. AT_CAP=1 forces the leaf branch regardless of the
# planner (deterministic depth bound). Child vars go on the $(MAKE) command
# line: kills the export env leak AND beats MAKEFLAGS-propagated assignments.
# MAXTIER=$$(jq -r .tier …) resolves at recipe run time — parent's tier
# becomes the child's ceiling. Uniform tail (check.sh + touch) keeps
# sentinel semantics identical for both kinds.
-include $(B)/components.mk
$(B)/components.mk: $(B)/plan.json
	jq -r --arg cap "$(AT_CAP)" '.components[] | "$(B)/\(.id).done: $(B)/plan.json \(.deps | map("$(B)/\(.).done") | join(" "))\n" + (if (.kind // "leaf") == "composite" and $$cap != "1" then "\t$$(ENGINE)subtree \(.id)\n\t+$$(MAKE) -C $(SRC)/\(.id) GOAL=goal.md B=build SRC=src AGENTMAKE_DEPTH=$(NEXT_DEPTH) TIER=$$$$(jq -r .tier $(B)/effort.json) MAXTIER=$$$$(jq -r .tier $(B)/effort.json) all\n" else "\t$$(AGENT) build \(.id)\n" end) + "\tbash $(SRC)/\(.id)/check.sh\n\ttouch $$@\nCOMPONENTS += $(B)/\(.id).done\n"' $< > $@

# ── Phase 3: reviewer agent gate
# components.mk prereq: without it, a failed plan/effort gate leaves COMPONENTS
# empty and review would run against nothing (-include hides remake failure)
$(B)/report.md: $(B)/components.mk $(COMPONENTS)
	$(AGENT) review > $@
	grep -q 'VERDICT: PASS' $@

$(B):
	mkdir -p $@

# ── Observability
ARTIFACTS = $(B)/effort.json $(B)/plan.json $(COMPONENTS) $(B)/report.md
progress:
	@done=0; total=0; \
	for f in $(ARTIFACTS); do \
	  total=$$((total+1)); \
	  if [ -f $$f ]; then done=$$((done+1)); printf ' \033[32m✓\033[0m %s\n' $$f; \
	  else printf ' \033[2m·\033[0m %s\n' $$f; fi; \
	done; \
	pct=$$((done*100/total)); n=$$((done*24/total)); \
	bar=""; [ $$n -gt 0 ] && bar=$$(printf '#%.0s' $$(seq 1 $$n)); \
	printf '[%-24s] %d/%d (%d%%)\n' "$$bar" $$done $$total $$pct
# nested: per-level bars, no global rollup — merged percent across unequal-cost
# subtrees would lie; "not scaffolded" = honest rendering of lazy planning
	@for d in $$(jq -r '.components[] | select((.kind // "leaf")=="composite") | .id' $(B)/plan.json 2>/dev/null); do \
	  [ -f $(SRC)/$$d/Makefile ] || { printf ' \033[2m·\033[0m %s (subtree, not scaffolded)\n' $$d; continue; }; \
	  echo " └─ $$d:"; \
	  $(MAKE) -s -C $(SRC)/$$d progress | sed 's/^/    /'; \
	done

# ponytail: awk-parsed mermaid; ceiling = pattern/order-only deps; upgrade = makefile2graph
graph:
	@echo 'graph TD'; \
	awk -F: '/^[a-zA-Z$$(][^=]*:([^=]|$$)/ && $$1!~/PHONY|DELETE_ON_ERROR/ \
	  {t=$$1; n=split($$2,d," "); for(i=1;i<=n;i++) if(d[i]!="|") printf "  %s --> %s\n", d[i], t}' \
	  $(ENGINE)build.mk $(B)/components.mk 2>/dev/null | sed -e 's/$$(B)/$(B)/g' -e 's/$$(GOAL)/$(GOAL)/g'
# nested: subgraph per composite; sed namespaces child node ids or mermaid
# merges identically-named nodes across subtrees; last edge shows the bubble
	@for d in $$(jq -r '.components[] | select((.kind // "leaf")=="composite") | .id' $(B)/plan.json 2>/dev/null); do \
	  [ -f $(SRC)/$$d/Makefile ] || continue; \
	  echo "  subgraph $$d"; \
	  $(MAKE) -s -C $(SRC)/$$d graph | tail -n +2 | sed -e "s|build/|$$d/build/|g" -e "s|^  goal.md|  $$d/goal.md|" -e 's/^/  /'; \
	  echo "  end"; \
	  echo "  $$d/build/report.md --> $(B)/$$d.done"; \
	done

clean:
	rm -rf $(B) $(SRC)
