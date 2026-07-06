export const runtime = "nodejs";

import { bearerToken, errorResponse, requireAdmin } from "@/lib/adminAuth";

export async function GET(req: Request) {
  try {
    const client = await requireAdmin(bearerToken(req));
    const [summary, storageHealth, searchMonitoring] = await Promise.all([
      client.rpc("admin_dashboard_summary"),
      client.rpc("admin_storage_health"),
      client.rpc("admin_search_monitoring_summary"),
    ]);
    if (summary.error) throw summary.error;
    if (storageHealth.error) throw storageHealth.error;
    return Response.json({
      ...(summary.data ?? {}),
      storage_health: storageHealth.data ?? null,
      search_monitoring: searchMonitoring.error ? null : searchMonitoring.data ?? null,
    });
  } catch (error) {
    return errorResponse(error);
  }
}
