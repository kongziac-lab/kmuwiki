export const runtime = "nodejs";

import { bearerToken, errorResponse, requireAdmin } from "@/lib/adminAuth";

export async function GET(req: Request) {
  try {
    const client = await requireAdmin(bearerToken(req));
    const [summary, storageHealth] = await Promise.all([
      client.rpc("admin_dashboard_summary"),
      client.rpc("admin_storage_health"),
    ]);
    if (summary.error) throw summary.error;
    if (storageHealth.error) throw storageHealth.error;
    return Response.json({
      ...(summary.data ?? {}),
      storage_health: storageHealth.data ?? null,
    });
  } catch (error) {
    return errorResponse(error);
  }
}
