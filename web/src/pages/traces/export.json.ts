// The whole incident registry as JSON (Export on the registry index).
import type { APIRoute } from "astro";
import { loadIncidents } from "../../lib/incidents";

export const GET: APIRoute = () =>
  new Response(JSON.stringify(loadIncidents() ?? { incidents: [] }, null, 1), { headers: { "Content-Type": "application/json" } });
