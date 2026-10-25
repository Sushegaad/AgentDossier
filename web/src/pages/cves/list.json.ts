// The slim row per CVE that the /cves/ list fetches (filter, sort, search, render); the full record
// is on each CVE's page and in export.json.
import type { APIRoute } from "astro";
import { allRows } from "../../lib/cves";

export const GET: APIRoute = () => new Response(JSON.stringify(allRows()), { headers: { "Content-Type": "application/json" } });
