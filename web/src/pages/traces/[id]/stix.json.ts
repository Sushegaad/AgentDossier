// One incident as a STIX 2.1 bundle (Export STIX 2.1).
import type { APIRoute } from "astro";
import { type Incident, incidentSlug, loadIncidents, toStix } from "../../../lib/incidents";

export function getStaticPaths() {
  return (loadIncidents()?.incidents ?? []).map((inc) => ({ params: { id: incidentSlug(inc.id) }, props: { inc } }));
}

export const GET: APIRoute = ({ props }) =>
  new Response(JSON.stringify(toStix((props as { inc: Incident }).inc), null, 1), { headers: { "Content-Type": "application/json" } });
