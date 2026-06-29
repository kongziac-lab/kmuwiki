export const runtime = "nodejs";

import { rejectMissingAuthorization } from "@/lib/ragProxy";
import { createSupabaseRouteClient } from "@/lib/supabaseRoute";

type WorkflowSaveRequest = {
  title?: string;
  query?: string;
  target_year?: number;
  graph?: unknown;
  source?: unknown;
};

export async function GET(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  try {
    const supabase = createSupabaseRouteClient(auth);
    const { data, error } = await supabase
      .from("saved_workflows")
      .select("id,title,query,target_year,created_at,updated_at,graph")
      .order("created_at", { ascending: false })
      .limit(100);
    if (error) throw error;
    return Response.json({ workflows: data ?? [] }, { headers: { "cache-control": "no-store" } });
  } catch (error: unknown) {
    return new Response(error instanceof Error ? error.message : "workflow list failed", { status: 500 });
  }
}

export async function POST(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  try {
    const body = await req.json() as WorkflowSaveRequest;
    if (!body.graph || typeof body.graph !== "object") {
      return new Response("graph is required", { status: 400 });
    }
    const title = String(body.title || body.query || "업무흐름도").trim() || "업무흐름도";
    const supabase = createSupabaseRouteClient(auth);
    const { data, error } = await supabase
      .from("saved_workflows")
      .insert({
        title,
        query: body.query ?? null,
        target_year: Number.isInteger(body.target_year) ? body.target_year : null,
        graph: body.graph,
        source: body.source ?? {},
      })
      .select("id,title")
      .single();
    if (error) throw error;
    const id = String(data.id);
    return Response.json({
      id,
      title: data.title,
      url: `/workflows/${id}`,
    }, { status: 201, headers: { "cache-control": "no-store" } });
  } catch (error: unknown) {
    return new Response(error instanceof Error ? error.message : "workflow save failed", { status: 500 });
  }
}
