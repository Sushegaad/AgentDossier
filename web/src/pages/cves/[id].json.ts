// One CVE record as JSON (Export JSON on the detail page).
import type { APIRoute } from "astro";
import { cveSlug, loadCves } from "../../lib/cves";

export function getStaticPaths() {
  return (loadCves()?.records ?? []).map((rec) => ({ params: { id: cveSlug(rec.id) }, props: { rec } }));
}

export const GET: APIRoute = ({ props }) =>
  new Response(JSON.stringify((props as { rec: unknown }).rec, null, 1), { headers: { "Content-Type": "application/json" } });
