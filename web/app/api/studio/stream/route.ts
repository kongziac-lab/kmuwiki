// Single-retrieval Studio stream: artifacts first, followed by summary tokens.

export const runtime = "nodejs";

import { proxyRagStream } from "@/lib/ragProxy";

export async function POST(req: Request) {
  return proxyRagStream(req, "/studio/stream");
}
