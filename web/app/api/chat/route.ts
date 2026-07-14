// /api/chat — Python 검색·RAG 서비스(/chat)로의 스트리밍 프록시.
// 클라이언트의 Authorization(사용자 JWT)을 그대로 전달해 RLS가 적용되게 한다.
// Vercel Services 배포에서는 같은 origin의 /rag 서비스로 호출한다.
// 로컬 개발에서만 PY_API_URL로 별도 FastAPI 서버를 가리킬 수 있다.

export const runtime = "nodejs";

import { proxyRagStream } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagStream(req, "/chat");
}
