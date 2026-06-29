// /api/chat — Python 검색·RAG 서비스(/chat)로의 스트리밍 프록시.
// 클라이언트의 Authorization(사용자 JWT)을 그대로 전달해 RLS가 적용되게 한다.
// Vercel Services 배포에서는 같은 origin의 /rag 서비스로 호출한다.
// 로컬 개발에서만 PY_API_URL로 별도 FastAPI 서버를 가리킬 수 있다.

export const runtime = "nodejs";

const RAG_PATH = process.env.NEXT_PUBLIC_RAG_URL ?? "/rag";
const LOCAL_PY_API = process.env.NODE_ENV === "production" ? "" : process.env.PY_API_URL;
const API_SECRET = process.env.KMU_API_SHARED_SECRET ?? "";

function upstreamBase(req: Request): string {
  if (LOCAL_PY_API) {
    return LOCAL_PY_API.replace(/\/$/, "");
  }
  if (/^https?:\/\//.test(RAG_PATH)) {
    return RAG_PATH.replace(/\/$/, "");
  }
  const origin = new URL(req.url).origin;
  const path = RAG_PATH.startsWith("/") ? RAG_PATH : `/${RAG_PATH}`;
  return `${origin}${path}`.replace(/\/$/, "");
}

export async function POST(req: Request) {
  const body = await req.text();
  const auth = req.headers.get("authorization") ?? "";
  const headers: Record<string, string> = {
    "content-type": "application/json",
    authorization: auth,
  };
  if (API_SECRET) {
    headers["x-kmuwiki-api-secret"] = API_SECRET;
  }

  const upstream = await fetch(`${upstreamBase(req)}/chat`, {
    method: "POST",
    headers,
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
