import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

function readWebFile(path: string): string {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

test("insights page wires Phase 4 and Phase 5 APIs into the web UI", () => {
  const pageUrl = new URL("../app/insights/page.tsx", import.meta.url);
  assert.equal(existsSync(pageUrl), true, "/insights page should exist");

  const source = readFileSync(pageUrl, "utf8");
  assert.match(source, /\/api\/insights/);
  assert.match(source, /\/api\/hermes/);
  assert.match(source, /\/api\/hermes\/hwpx/);
  assert.match(source, /workflow_mermaid/);
  assert.match(source, /work_items/);
  assert.match(source, /calendar_drafts/);
  assert.match(source, /report_draft/);
  assert.match(source, /report_workflow/);
  assert.match(source, /recurring_work/);
  assert.match(source, /drafts/);
  assert.match(source, /hwpx_filename/);
  assert.match(source, /HWPX 다운로드/);
});

test("hwpx export proxy keeps the same authenticated RAG boundary", () => {
  const source = readWebFile("app/api/hermes/hwpx/route.ts");
  assert.match(source, /rejectMissingAuthorization/);
  assert.match(source, /buildRagHeaders/);
  assert.match(source, /\/hermes\/hwpx/);
  assert.match(source, /application\/hwp\+zip/);
});

test("primary navigation exposes the insights workspace", () => {
  assert.match(readWebFile("components/AppShell.tsx"), /href: "\/insights"/);
});
