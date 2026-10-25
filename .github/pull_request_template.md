<!-- What changed and why, in a few lines. -->

## Documentation (required)

A change is not done until the documents that describe it are true. Tick what applies, or say "n/a".

- [ ] `README.md` — features, commands, counts, versions, screenshots' captions
- [ ] `docs/*.md` — the page that explains this area (`methodology`, `traces`, `incidents`, `enterprise-runbook`, `architecture`)
- [ ] Site copy under `web/src/pages/` — `/methodology/`, `/about/`, `/enterprise/`, `/traces/`, the home page
- [ ] `CHANGELOG.md` — an entry under `[Unreleased]`
- [ ] `scripts/check_docs_drift.py` — a check added for any new fact a doc now quotes

## Gates

- [ ] `uv run ruff check . && uv run ruff format --check .` · `uv run mypy agentdossier` · `uv run pytest -q`
- [ ] Web (if touched): `npm run check` · `npx vitest run` · `npm run build` · `npm run audit`
