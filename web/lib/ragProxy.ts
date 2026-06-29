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
  const headers: Record<string, string> = {
    "content-type": "application/json",
    authorization: auth ?? "",
  };
  if (apiSecret) {
    headers["x-kmuwiki-api-secret"] = apiSecret;
  }
  return headers;
}
