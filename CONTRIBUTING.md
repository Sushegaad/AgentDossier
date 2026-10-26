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

The weekly refresh files candidate incidents in `data/curated/incident_candidates.yaml` and then
**reviews them with a model** (`agentdossier incidents review`, `ANTHROPIC_API_KEY`): each
candidate's article is read, and the record is published when it describes a specific, real event
with confidence ≥ 0.8 from a non-aggregator source, or dismissed with the reason on file (see
`docs/incidents.md`). Nobody has to act on a candidate. If you want to:

- `uv run agentdossier incidents dismiss <cand-id> --note "why"` retracts a decision — delete the
  published row too if there is one.
- `uv run agentdossier incidents draft <cand-id>` scaffolds a `status: placeholder` record for one
  you would rather write by hand; the next review will read its sources and publish or remove it
  unless you publish it first.

A record is "as reported": figures are the sources' own, MITRE tactics are the reviewer's reading,
and nothing is published about a private individual. A row you check yourself gets your name in
`reviewer` and the date in `checked_on`; a row the model published says so.

## Keeping the docs true

Every change that alters a number, a version, a command, a page or a workflow also updates the
documents that state it — `README.md`, the relevant `docs/*.md`, the site copy under `web/src/pages`,
and `CHANGELOG.md`. `scripts/check_docs_drift.py` (run by CI and by `pytest`) verifies the facts it
can: the test count, Python and Node versions across README, CI and the Dockerfile, the docs index,
and the incident counts. When you add a fact a doc will quote, add a check for it there.

