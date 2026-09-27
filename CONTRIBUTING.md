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
