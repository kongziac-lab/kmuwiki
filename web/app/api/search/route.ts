// /api/search — Python 검색 서비스(/search)로의 JSON 프록시.
// 클라이언트의 Authorization(사용자 JWT)을 그대로 전달해 RLS가 적용되게 한다.

export const runtime = "nodejs";

import { proxyRagJson } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagJson(req, "/search");
}
