// /api/hermes/hwpx — Hermes 문서 초안을 HWPX 파일로 내보내는 프록시.

export const runtime = "nodejs";

import { buildRagHeaders, rejectMissingAuthorization, resolveRagBase } from "@/lib/ragProxy";

export async function POST(req: Request) {
  const body = await req.text();
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  const upstream = await fetch(`${resolveRagBase(req.url)}/hermes/hwpx`, {
    method: "POST",
    headers: buildRagHeaders(auth),
    body,
  });

  if (!upstream.ok) {
    return new Response(`upstream error: ${upstream.status}`, { status: 502 });
  }

  return new Response(await upstream.arrayBuffer(), {
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/hwp+zip",
      "content-disposition": upstream.headers.get("content-disposition") ?? "attachment; filename=\"draft.hwpx\"",
      "cache-control": "no-store",
    },
  });
}
