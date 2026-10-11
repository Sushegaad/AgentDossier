// The full bundle of one trace as JSON: the index line (hash-chained) plus every file in the bundle.
import type { APIRoute } from "astro";
import { loadBundle, loadTraceStore } from "../../../lib/catalog";

export function getStaticPaths() {
  return loadTraceStore().map((l) => ({ params: { id: l.id }, props: { line: l } }));
}

export const GET: APIRoute = ({ props }) => {
  const line = (props as { line: ReturnType<typeof loadTraceStore>[number] }).line;
  const files = line.record.bundle ? loadBundle(line.record.bundle) : {};
  return new Response(JSON.stringify({ line, files }, null, 1), { headers: { "Content-Type": "application/json" } });
};
