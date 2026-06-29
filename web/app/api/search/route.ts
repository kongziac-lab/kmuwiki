// /api/search — Python 검색 서비스(/search)로의 JSON 프록시.
// 클라이언트의 Authorization(사용자 JWT)을 그대로 전달해 RLS가 적용되게 한다.

export const runtime = "nodejs";

import { buildRagHeaders, rejectMissingAuthorization, resolveRagBase } from "@/lib/ragProxy";

export async function POST(req: Request) {
  const body = await req.text();
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  const upstream = await fetch(`${resolveRagBase(req.url)}/search`, {
    method: "POST",
    headers: buildRagHeaders(auth),
    body,
  });

  const responseBody = await upstream.text();
  if (!upstream.ok) {
    return new Response(`upstream error: ${upstream.status}`, { status: 502 });
  }

  return new Response(responseBody, {
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
