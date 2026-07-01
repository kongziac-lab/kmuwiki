// /api/reports/template-hwpx — 업로드한 HWPX 양식에 보고서 본문을 채워 내보내는 프록시.

export const runtime = "nodejs";

import { buildRagHeaders, rejectMissingAuthorization, resolveRagBase } from "@/lib/ragProxy";

const MAX_TEMPLATE_BYTES = 10 * 1024 * 1024;

export async function POST(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  const form = await req.formData();
  const template = form.get("template");
  if (!(template instanceof File)) {
    return new Response("missing template", { status: 400 });
  }
  if (!template.name.toLowerCase().endsWith(".hwpx")) {
    return new Response("template must be .hwpx", { status: 400 });
  }
  if (template.size > MAX_TEMPLATE_BYTES) {
    return new Response("template too large", { status: 413 });
  }

  const templateBase64 = Buffer.from(await template.arrayBuffer()).toString("base64");
  const payload = {
    title: String(form.get("title") ?? template.name ?? "wiki-report"),
    body: String(form.get("body") ?? ""),
    template_base64: templateBase64,
  };

  const upstream = await fetch(`${resolveRagBase(req.url)}/reports/template-hwpx`, {
    method: "POST",
    headers: buildRagHeaders(auth),
    body: JSON.stringify(payload),
  });

  if (!upstream.ok) {
    return new Response(`upstream error: ${upstream.status}`, { status: 502 });
  }

  return new Response(await upstream.arrayBuffer(), {
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/hwp+zip",
      "content-disposition": upstream.headers.get("content-disposition") ?? "attachment; filename=\"wiki-report.hwpx\"",
      "cache-control": "no-store",
    },
  });
}
