export function resolveRagBase(
  requestUrl: string,
  ragPath = process.env.NEXT_PUBLIC_RAG_URL ?? "/rag",
  localPyApi = process.env.NODE_ENV === "production" ? "" : process.env.PY_API_URL,
): string {
  if (localPyApi) {
    return localPyApi.replace(/\/$/, "");
  }
  if (/^https?:\/\//.test(ragPath)) {
    return ragPath.replace(/\/$/, "");
  }
  const origin = new URL(requestUrl).origin;
  const path = ragPath.startsWith("/") ? ragPath : `/${ragPath}`;
  return `${origin}${path}`.replace(/\/$/, "");
}

export function buildRagHeaders(auth: string | null, apiSecret = process.env.KMU_API_SHARED_SECRET ?? "") {
  if (process.env.NODE_ENV === "production" && !apiSecret) {
    throw new Error("KMU_API_SHARED_SECRET is required in production");
  }
  const headers: Record<string, string> = {
    "content-type": "application/json",
    authorization: auth ?? "",
  };
  if (apiSecret) {
    headers["x-kmuwiki-api-secret"] = apiSecret;
  }
  return headers;
}

export function rejectMissingAuthorization(auth: string | null): Response | null {
  if (!auth || !auth.toLowerCase().startsWith("bearer ")) {
    return new Response("missing authorization", { status: 401 });
  }
  return null;
}

function boundedEnvNumber(name: string, fallback: number, min: number, max: number): number {
  const value = Number(process.env[name] ?? fallback);
  return Number.isFinite(value) && value >= min && value <= max ? value : fallback;
}

export async function readLimitedBody(
  req: Request,
  maxBytes = boundedEnvNumber("KMU_WEB_MAX_BODY_KB", 64, 1, 1024) * 1024,
): Promise<string> {
  const rawLength = req.headers.get("content-length");
  if (rawLength && Number(rawLength) > maxBytes) {
    throw new Response("request body too large", { status: 413 });
  }
  if (!req.body) return "";

  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel("request body too large");
      throw new Response("request body too large", { status: 413 });
    }
    chunks.push(value);
  }
  const merged = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(merged);
}

export async function fetchRag(
  req: Request,
  path: string,
  auth: string,
  body: BodyInit,
  { streaming = false }: { streaming?: boolean } = {},
): Promise<Response> {
  const timeoutMs = streaming
    ? boundedEnvNumber("KMU_RAG_STREAM_TIMEOUT_MS", 300_000, 1_000, 900_000)
    : boundedEnvNumber("KMU_RAG_TIMEOUT_MS", 60_000, 1_000, 300_000);
  return fetch(`${resolveRagBase(req.url)}${path}`, {
    method: "POST",
    headers: buildRagHeaders(auth),
    body,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
}

export function proxyError(error: unknown): Response {
  if (error instanceof Response) return error;
  if (error instanceof Error && error.name === "TimeoutError") {
    return new Response("upstream timeout", { status: 504 });
  }
  return new Response("upstream unavailable", { status: 502 });
}

function mappedUpstreamStatus(status: number): number {
  return [400, 401, 403, 413, 429].includes(status) ? status : 502;
}

export async function proxyRagJson(req: Request, path: string): Promise<Response> {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;
  try {
    const body = await readLimitedBody(req);
    const upstream = await fetchRag(req, path, auth, body);
    const responseBody = await upstream.text();
    if (!upstream.ok) {
      return new Response(`upstream error: ${upstream.status}`, {
        status: mappedUpstreamStatus(upstream.status),
      });
    }
    return new Response(responseBody, {
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    return proxyError(error);
  }
}

export async function proxyRagStream(req: Request, path: string): Promise<Response> {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;
  try {
    const body = await readLimitedBody(req);
    const upstream = await fetchRag(req, path, auth, body, { streaming: true });
    if (!upstream.ok || !upstream.body) {
      return new Response(`upstream error: ${upstream.status}`, {
        status: mappedUpstreamStatus(upstream.status),
      });
    }
    return new Response(upstream.body, {
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  } catch (error) {
    return proxyError(error);
  }
}

export async function proxyRagFile(
  req: Request,
  path: string,
  fallbackType: string,
  fallbackDisposition: string,
): Promise<Response> {
  const auth = req.headers.get("authorization") ?? "";
  const unauthorized = rejectMissingAuthorization(auth);
  if (unauthorized) return unauthorized;
  try {
    const maxBytes = boundedEnvNumber("KMU_WEB_MAX_EXPORT_BODY_MB", 24, 1, 32) * 1024 * 1024;
    const body = await readLimitedBody(req, maxBytes);
    const upstream = await fetchRag(req, path, auth, body);
    if (!upstream.ok) {
      return new Response(`upstream error: ${upstream.status}`, {
        status: mappedUpstreamStatus(upstream.status),
      });
    }
    return new Response(await upstream.arrayBuffer(), {
      headers: {
        "content-type": upstream.headers.get("content-type") ?? fallbackType,
        "content-disposition": upstream.headers.get("content-disposition") ?? fallbackDisposition,
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    return proxyError(error);
  }
}
