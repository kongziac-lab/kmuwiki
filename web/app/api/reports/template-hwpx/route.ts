// /api/reports/template-hwpx — 업로드한 HWPX 양식에 보고서 본문을 채워 내보내는 프록시.

export const runtime = "nodejs";

import { fetchRag, proxyError, rejectMissingAuthorization } from "@/lib/ragProxy";

const MAX_TEMPLATE_BYTES = 10 * 1024 * 1024;

export async function POST(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;

  const contentLength = Number(req.headers.get("content-length") ?? 0);
  if (contentLength > MAX_TEMPLATE_BYTES + 1024 * 1024) {
    return new Response("template too large", { status: 413 });
  }

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
  const title = String(form.get("title") ?? template.name ?? "wiki-report");
  const reportBody = String(form.get("body") ?? "");
  if (title.length > 300 || reportBody.length > 500_000) {
    return new Response("report content too large", { status: 413 });
  }
  const payload = {
    title,
    body: reportBody,
    template_base64: templateBase64,
  };

  let upstream: Response;
  try {
    upstream = await fetchRag(req, "/reports/template-hwpx", auth, JSON.stringify(payload));
  } catch (error) {
    return proxyError(error);
  }

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
