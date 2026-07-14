// /api/hermes/docx — Hermes 문서 초안을 DOCX 파일로 내보내는 프록시.

export const runtime = "nodejs";

import { proxyRagFile } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagFile(
    req,
    "/hermes/docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "attachment; filename=\"draft.docx\"",
  );
}
