// /api/insights — Python 활용 기능 서비스(/insights)로의 JSON 프록시.
// 사용자 JWT와 서버 전용 공유 시크릿을 함께 전달한다.

export const runtime = "nodejs";

import { proxyRagJson } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagJson(req, "/insights");
}
