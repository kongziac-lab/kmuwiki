// /api/studio — Python 스튜디오 서비스(/studio)로의 JSON 프록시.
// 마인드맵·슬라이드(Marp)·인포그래픽(SVG)·지표를 한 번에 반환한다(비-LLM).

export const runtime = "nodejs";

import { proxyRagJson } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagJson(req, "/studio");
}
