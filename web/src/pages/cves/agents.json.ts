// Per catalog agent: how many CVEs the registry links to it (the search result's mark). Small.
import type { APIRoute } from "astro";
import { agentCveSummary } from "../../lib/cves";

export const GET: APIRoute = () => new Response(JSON.stringify(agentCveSummary()), { headers: { "Content-Type": "application/json" } });
