import assert from "node:assert/strict";
import test from "node:test";

import { buildRagHeaders, resolveRagBase } from "../lib/ragProxy.ts";

test("resolveRagBase maps the default relative RAG path onto the request origin", () => {
  assert.equal(
    resolveRagBase("https://kmuwiki.vercel.app/api/search", "/rag", ""),
    "https://kmuwiki.vercel.app/rag",
  );
});

test("resolveRagBase prefers an explicit local Python API during development", () => {
  assert.equal(
    resolveRagBase("http://localhost:3000/api/search", "/rag", "http://localhost:8000/"),
    "http://localhost:8000",
  );
});

test("buildRagHeaders forwards auth and adds the server-side shared secret", () => {
  assert.deepEqual(buildRagHeaders("Bearer jwt", "secret-value"), {
    "content-type": "application/json",
    authorization: "Bearer jwt",
    "x-kmuwiki-api-secret": "secret-value",
  });
});
