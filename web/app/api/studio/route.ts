// /api/studio — Python 스튜디오 서비스(/studio)로의 JSON 프록시.
// 마인드맵·슬라이드(Marp)·인포그래픽(SVG)·지표를 한 번에 반환한다(비-LLM).

export const runtime = "nodejs";

import { buildRagHeaders, rejectMissingAuthorization, resolveRagBase } from "@/lib/ragProxy";

export async function POST(req: Request) {
  const body = await req.text();
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  const upstream = await fetch(`${resolveRagBase(req.url)}/studio`, {
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
