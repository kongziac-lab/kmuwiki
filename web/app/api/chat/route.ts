// /api/chat — Python 검색·RAG 서비스(/chat)로의 스트리밍 프록시.
// 클라이언트의 Authorization(사용자 JWT)을 그대로 전달해 RLS가 적용되게 한다.
// Python URL은 서버 환경변수로만 두어 클라이언트에 노출하지 않는다.

export const runtime = "nodejs";

const PY_API = process.env.PY_API_URL ?? "http://localhost:8000";

export async function POST(req: Request) {
  const body = await req.text();
  const auth = req.headers.get("authorization") ?? "";

  const upstream = await fetch(`${PY_API}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: auth },
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
