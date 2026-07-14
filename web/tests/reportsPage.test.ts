import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function readWebFile(path: string): string {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

test("reports page exposes the wiki report writer workflow", () => {
  const source = readWebFile("app/reports/page.tsx");

  assert.match(source, /\/api\/reports/);
  assert.match(source, /\/api\/hermes\/hwpx/);
  assert.match(source, /\/api\/reports\/template-hwpx/);
  assert.match(source, /wiki-report-writer/);
  assert.match(source, /korean-gov-doc/);
  assert.match(source, /hwpx-autofill-conversion/);
  assert.match(source, /보고서 생성/);
  assert.match(source, /기본 HWPX/);
  assert.match(source, /HWPX 양식 업로드/);
  assert.match(source, /업로드 양식으로 HWPX/);
  assert.match(source, /근거 문서/);
});

test("reports proxy keeps the authenticated RAG boundary", () => {
  const source = readWebFile("app/api/reports/route.ts");
  const proxy = readWebFile("lib/ragProxy.ts");

  assert.match(source, /proxyRagJson/);
  assert.match(proxy, /rejectMissingAuthorization/);
  assert.match(proxy, /buildRagHeaders/);
  assert.match(source, /\/reports/);
});

test("report template hwpx proxy handles multipart upload safely", () => {
  const source = readWebFile("app/api/reports/template-hwpx/route.ts");

  assert.match(source, /rejectMissingAuthorization/);
  assert.match(source, /formData/);
  assert.match(source, /template_base64/);
  assert.match(source, /\/reports\/template-hwpx/);
  assert.match(source, /application\/hwp\+zip/);
});

test("primary navigation exposes report generation", () => {
  const source = readWebFile("components/AppShell.tsx");

  assert.match(source, /href: "\/reports"/);
  assert.match(source, /label: "보고서 생성"/);
});
