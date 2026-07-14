// /api/reports — Wiki DB 기반 보고서 생성 서비스(/reports)로의 JSON 프록시.

export const runtime = "nodejs";

import { proxyRagJson } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagJson(req, "/reports");
}
