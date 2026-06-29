import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

function read(path: string): string {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

test("workflow pages expose saved workflow navigation and detail view", () => {
  assert.equal(existsSync(new URL("../app/workflows/page.tsx", import.meta.url)), true);
  assert.equal(existsSync(new URL("../app/workflows/[id]/page.tsx", import.meta.url)), true);

  assert.match(read("components/AppShell.tsx"), /href: "\/workflows"/);
  assert.match(read("app/workflows/page.tsx"), /저장된 업무흐름도/);
  assert.match(read("app/workflows/[id]/page.tsx"), /WorkflowBoard/);
});

test("insights page can save the generated workflow snapshot", () => {
  const source = read("app/insights/page.tsx");

  assert.match(source, /업무흐름도 저장/);
  assert.match(source, /postJson<SaveWorkflowResponse>\("\/api\/workflows"/);
  assert.match(source, /workflowNodes/);
});

test("saved workflow API uses authenticated Supabase RLS boundary", () => {
  assert.equal(existsSync(new URL("../app/api/workflows/route.ts", import.meta.url)), true);
  assert.equal(existsSync(new URL("../app/api/workflows/[id]/route.ts", import.meta.url)), true);

  const listRoute = read("app/api/workflows/route.ts");
  const itemRoute = read("app/api/workflows/[id]/route.ts");

  assert.match(listRoute, /rejectMissingAuthorization/);
  assert.match(listRoute, /saved_workflows/);
  assert.match(listRoute, /createSupabaseRouteClient/);
  assert.match(itemRoute, /rejectMissingAuthorization/);
  assert.match(itemRoute, /saved_workflows/);
  assert.match(itemRoute, /createSupabaseRouteClient/);
});

test("saved workflows migration enables owner-scoped RLS", () => {
  const migration = read("../supabase/migrations/0007_saved_workflows.sql");

  assert.match(migration, /create table if not exists saved_workflows/);
  assert.match(migration, /owner_id\s+uuid\s+not null\s+default auth\.uid\(\)/);
  assert.match(migration, /alter table saved_workflows enable row level security/);
  assert.match(migration, /owner_id = auth\.uid\(\)/);
});
