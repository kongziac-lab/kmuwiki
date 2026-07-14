// /api/hermes/hwpx — Hermes 문서 초안을 HWPX 파일로 내보내는 프록시.

export const runtime = "nodejs";

import { proxyRagFile } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagFile(
    req,
    "/hermes/hwpx",
    "application/hwp+zip",
    "attachment; filename=\"draft.hwpx\"",
  );
}
