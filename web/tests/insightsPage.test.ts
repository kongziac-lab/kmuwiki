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
  assert.match(source, /workflow_mermaid/);
  assert.match(source, /calendar_drafts/);
  assert.match(source, /report_draft/);
  assert.match(source, /recurring_work/);
  assert.match(source, /drafts/);
});

test("primary navigation exposes the insights workspace", () => {
  for (const path of ["app/page.tsx", "app/search/page.tsx", "app/admin/page.tsx"]) {
    assert.match(readWebFile(path), /href="\/insights"/, `${path} should link to /insights`);
  }
});
