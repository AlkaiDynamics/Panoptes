# Panoptes

Panoptes includes a reproducible end-to-end **corpus planning pipeline**.
It runs the pinned MIT-licensed `create-mvp` Make engine with a Panoptes
adapter: goal → plan → dependency-ordered parallel builds → checks → review.
It produces distinct provisional 72-source and 300-source campaigns.

Requires Python 3.11+, GNU Make, Bash and `jq`. From this directory:

```sh
python -m unittest discover -s tests -v
make -C examples/e2e -j2
cat examples/e2e/build/report.md
python -c 'import json; print(json.load(open("examples/e2e/src/audit/artifact.json"))["next_prompt"])'
python -m panoptes.cli campaign --target 72 --output /tmp/panoptes-72.json
python -m panoptes.cli campaign --target 300 --output /tmp/panoptes-300.json
python -m panoptes.cli ledger
# Plan a reproducible prompt-evolution round without paid inference:
python -m panoptes.cli prompt-evolve-plan population.json --seed 17
# With a separately operated Mnemos service:
MNEMOS_BASE=http://localhost:8000 MNEMOS_API_KEY=... \
  python -m panoptes.cli memory-search 'latest Panoptes checkpoint' --category projects
```

See [details](docs/PLANNER.md). The source ledger records four implemented and
tested contributions (planning framework, evidence-gated audit wrapper, Mnemos
memory adapter, and provider-neutral genetic prompt-round planner), with
**zero independently accepted operational
repository integrations**. The
current review certifies planning artifacts and prompt construction only.
Completion of the 72 and 300 source products requires source-specific code,
behavior tests and independent audit.
