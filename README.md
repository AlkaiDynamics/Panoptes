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
python -m panoptes.cli campaign --target 72 --output /tmp/panoptes-72.json
python -m panoptes.cli campaign --target 300 --output /tmp/panoptes-300.json
python -m panoptes.cli ledger
```

See [details](docs/PLANNER.md). The source ledger records one implemented and
tested planning-framework contribution, with **zero accepted operational
repository integrations**. The current review certifies planning artifacts.
Completion of the 72 and 300 source products requires source-specific code,
behavior tests and independent audit.
