# Contributing

Corrections, new resources and evidence links are welcome as GitHub issues
or pull requests. Every change to a record needs a source link.

- **Correct a record:** open an issue with the resource name, the field, the
  correct value and a link to the evidence. The maintainer records the
  decision in `data/changelog/trust-changelog.jsonl`.
- **Add a resource:** open a pull request adding it to
  `data/review/additions.yaml` with its URL and, if available, its ARD entry,
  A2A Agent Card or MCP server card.
- **Change scoring, taxonomy or a framework:** edit `config/` in a pull
  request. These files are code-owned and always reviewed.
- **Code:** `uv sync --extra dev`, `uv run ruff check .`, `uv run pytest`.
  Commits follow Conventional Commits. By contributing you agree your
  contribution is licensed under MIT (Developer Certificate of Origin;
  sign off with `git commit -s`).

Nothing in this project is for sale: no payment for inclusion, badges, tier
or position.

## Incident candidates and the registry

The weekly refresh files candidate incidents in `data/curated/incident_candidates.yaml` (see
`docs/incidents.md`). To act on one:

- `uv run agentdossier incidents draft <cand-id>` scaffolds a `status: placeholder` record in
  `data/curated/incidents.yaml`; complete the `TODO` fields from the sources, then set
  `status: published`.
- `uv run agentdossier incidents dismiss <cand-id> --note "why"` retires one.

A record is "as reported": figures are the sources' own, MITRE tactics are your reading of them, and
nothing is published about a private individual. Set `reviewer` and `checked_on` once you have
checked every line against its sources.

## Keeping the docs true

Every change that alters a number, a version, a command, a page or a workflow also updates the
documents that state it — `README.md`, the relevant `docs/*.md`, the site copy under `web/src/pages`,
and `CHANGELOG.md`. `scripts/check_docs_drift.py` (run by CI and by `pytest`) verifies the facts it
can: the test count, Python and Node versions across README, CI and the Dockerfile, the docs index,
and the incident counts. When you add a fact a doc will quote, add a check for it there.

