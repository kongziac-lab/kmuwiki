// /api/studio/summary — Python 스튜디오 요약(/studio/summary)로의 스트리밍 프록시.
// /api/chat 과 동일하게 사용자 JWT를 전달하고 SSE를 그대로 흘려보낸다.

export const runtime = "nodejs";

import { proxyRagStream } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagStream(req, "/studio/summary");
}
