export const runtime = "nodejs";

import { rejectMissingAuthorization } from "@/lib/ragProxy";
import { createSupabaseRouteClient } from "@/lib/supabaseRoute";

export async function GET(req: Request, context: { params: Promise<{ id: string }> }) {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  try {
    const { id } = await context.params;
    const supabase = createSupabaseRouteClient(auth);
    const { data, error } = await supabase
      .from("saved_workflows")
      .select("id,title,query,target_year,graph,source,created_at,updated_at")
      .eq("id", id)
      .single();
    if (error) throw error;
    return Response.json({ workflow: data }, { headers: { "cache-control": "no-store" } });
  } catch (error: unknown) {
    return new Response(error instanceof Error ? error.message : "workflow load failed", { status: 500 });
  }
}

export async function DELETE(req: Request, context: { params: Promise<{ id: string }> }) {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  try {
    const { id } = await context.params;
    const supabase = createSupabaseRouteClient(auth);
    const { error } = await supabase
      .from("saved_workflows")
      .delete()
      .eq("id", id);
    if (error) throw error;
    return new Response(null, { status: 204 });
  } catch (error: unknown) {
    return new Response(error instanceof Error ? error.message : "workflow delete failed", { status: 500 });
  }
}
