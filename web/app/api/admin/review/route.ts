export const runtime = "nodejs";

import { bearerToken, errorResponse, requireAdmin } from "@/lib/adminAuth";

function textOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export async function GET(req: Request) {
  try {
    const client = await requireAdmin(bearerToken(req));
    const limit = Number(new URL(req.url).searchParams.get("limit") ?? 50);
    const { data, error } = await client.rpc("admin_review_documents", { limit_count: limit });
    if (error) throw error;
    return Response.json({ documents: data ?? [] });
  } catch (error) {
    return errorResponse(error);
  }
}

export async function PATCH(req: Request) {
  try {
    const client = await requireAdmin(bearerToken(req));
    const body = await req.json();
    if (!body?.document_id) {
      return new Response("missing document_id", { status: 400 });
    }
    const { error } = await client.rpc("admin_update_document_metadata", {
      document_id: body.document_id,
      dept_text: textOrNull(body.dept),
      security_level_text: textOrNull(body.security_level),
      task_category_text: textOrNull(body.task_category),
      review_required_value: Boolean(body.review_required),
    });
    if (error) throw error;
    return Response.json({ ok: true });
  } catch (error) {
    return errorResponse(error);
  }
}
