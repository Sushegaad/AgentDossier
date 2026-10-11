// One incident as JSON (Export JSON on the detail page).
import type { APIRoute } from "astro";
import { incidentSlug, loadIncidents } from "../../lib/incidents";

export function getStaticPaths() {
  return (loadIncidents()?.incidents ?? []).map((inc) => ({ params: { id: incidentSlug(inc.id) }, props: { inc } }));
}

export const GET: APIRoute = ({ props }) =>
  new Response(JSON.stringify((props as { inc: unknown }).inc, null, 1), { headers: { "Content-Type": "application/json" } });
