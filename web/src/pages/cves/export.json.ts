// The whole CVE registry as JSON (Export on the list): every record with the official description,
// CVSS, CWE, products, references and this registry's classification and status.
import type { APIRoute } from "astro";
import { loadCves } from "../../lib/cves";

export const GET: APIRoute = () =>
  new Response(JSON.stringify(loadCves() ?? { records: [] }, null, 1), { headers: { "Content-Type": "application/json" } });
