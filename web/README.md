# web/

The public demo site (Astro 5 + React islands + TypeScript + MiniSearch), served
from GitHub Pages at https://sushegaad.github.io/AgentDossier/. It is fully
static: no server, no accounts; Google Analytics runs in cookieless consent mode on the
public demo only (`PUBLIC_GA_ID`), self-hosted builds ship no analytics. Search, the intent parser, the
explanations and the shortlist all run in the browser.

```bash
cd web
npm ci
CATALOG_DIR=../data/catalog npm run dev      # or any directory written by `agentdossier build`
npm test                                     # intent parser, search ranking, precision@10
npm run check && npm run build               # type-check, then build into dist/
npm run audit                                # launch gates: axe (WCAG 2.1 AA) + Lighthouse on the built site
```

Gates enforced by `npm test` and `npm run audit` (all run in CI):

| Gate | Source | Threshold |
| --- | --- | --- |
| precision@10 | `eval/queries.yaml` (50 hand-labelled queries) | ≥ 0.80 |
| intent chip accuracy | `eval/intent_cases.yaml` (52 cases) | ≥ 95 % |
| accessibility | axe-core, WCAG 2.0 A/AA + 2.1 AA, seven page types | 0 serious/critical |
| Lighthouse (desktop) | home and one agent profile | performance ≥ 85, accessibility ≥ 95, best practices ≥ 90, SEO ≥ 90 |

`scripts/sync-catalog.mjs` (run before `dev` and `build`) copies the catalog
into `public/catalog/` so the browser can fetch it, and its `ard.json` into
`public/.well-known/`. With no catalog the site still builds and says so.

| Route | What it is |
| --- | --- |
| `/` | Landing: statement hero, stats, the 12-domain grid, the evidence scale, how it works |
| `/search/` | Search: plain-language query → editable requirement chips → facet rail → ledger result cards with the trust profile; CSV/JSON export |
| `/enterprise/` | The self-hosted edition: safety controls, the eight-step procedure, `enterprise.json`, ways to run it |
| `/agents/<slug>/` | Dossier: trust profile above the fold, compliance evidence ledger (found / claimed / not found), GDPR assembled from checks, domain score breakdown, buyer checklist, provenance, news |
| `/domains/`, `/domains/<id>/` | The twelve ranked top-100 lists |
| `/compare/?ids=a,b,c` | Side-by-side comparison (up to four) |
| `/shortlist/` | Browser-local shortlist (localStorage), exportable as JSON |
| `/private/` | Opens a catalog from a self-hosted instance (file or URL) and searches it locally |
| `/changelog/` | Trust changelog (badges added / changed / removed per weekly build) |
| `/methodology/` | `docs/methodology.md` rendered, plus what the badges mean |
| `/agent/?id=…` | Dynamic dossier for self-hosted instances (built with `PUBLIC_DYNAMIC_AGENTS=1`), whose catalog changes with every scan |

The visual design follows the Claude Design mockups (editorial ledger: Archivo, one red accent,
ruled rows, tiers always written out); tokens live in `src/styles/global.css`, rule-driven
dossier blocks in `src/lib/dossier.ts`.

Configuration is read from the repository, not duplicated: `config/intent_rules.json`,
`config/taxonomy.json` and `config/frameworks/*.json` are imported at build time.
`SITE_BASE` (default `/AgentDossier`) and `SITE_URL` set the deployment path for
an enterprise instance served elsewhere; `PUBLIC_DYNAMIC_AGENTS=1` makes agent
links point at the client-rendered dossier (`deploy/Dockerfile` sets all three). `public/schema/` is a copy of
`../schema/` published for machine readers.
