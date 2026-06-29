// /api/chat — Python 검색·RAG 서비스(/chat)로의 스트리밍 프록시.
// 클라이언트의 Authorization(사용자 JWT)을 그대로 전달해 RLS가 적용되게 한다.
// Vercel Services 배포에서는 같은 origin의 /rag 서비스로 호출한다.
// 로컬 개발에서만 PY_API_URL로 별도 FastAPI 서버를 가리킬 수 있다.

export const runtime = "nodejs";

import { buildRagHeaders, resolveRagBase } from "@/lib/ragProxy";

export async function POST(req: Request) {
  const body = await req.text();
  const auth = req.headers.get("authorization") ?? "";

  const upstream = await fetch(`${resolveRagBase(req.url)}/chat`, {
    method: "POST",
    headers: buildRagHeaders(auth),
    body,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(`upstream error: ${upstream.status}`, { status: 502 });
  }

  // SSE 스트림을 그대로 흘려보낸다.
  return new Response(upstream.body, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}
