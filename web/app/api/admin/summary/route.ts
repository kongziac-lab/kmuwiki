export const runtime = "nodejs";

import { bearerToken, errorResponse, requireAdmin } from "@/lib/adminAuth";

export async function GET(req: Request) {
  try {
    const client = await requireAdmin(bearerToken(req));
    const { data, error } = await client.rpc("admin_dashboard_summary");
    if (error) throw error;
    return Response.json(data ?? {});
  } catch (error) {
    return errorResponse(error);
  }
}
