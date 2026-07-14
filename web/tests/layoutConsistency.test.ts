import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

function readWebFile(path: string): string {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

test("all primary pages use the shared app shell", () => {
  const shellUrl = new URL("../components/AppShell.tsx", import.meta.url);
  assert.equal(existsSync(shellUrl), true, "shared AppShell should exist");

  const shell = readFileSync(shellUrl, "utf8");
  assert.match(shell, /className="page app-shell"/);
  assert.match(shell, /<Link className="brand" href="\/">KMU Wiki<\/Link>/);
  assert.doesNotMatch(shell, /^"use client"/);
  assert.match(shell, /챗봇/);
  assert.match(shell, /문서 검색/);
  assert.match(shell, /업무 활용/);
  assert.match(shell, /관리자/);

  for (const path of ["app/page.tsx", "app/search/layout.tsx", "app/insights/layout.tsx", "app/admin/layout.tsx"]) {
    const source = readWebFile(path);
    assert.match(source, /@\/components\/AppShell/, `${path} should import AppShell`);
    assert.match(source, /<AppShell\s+active=/, `${path} should render AppShell`);
  }
});

test("primary query inputs share one form treatment", () => {
  const globals = readWebFile("app/globals.css");
  assert.match(globals, /\.app-shell\s*\{/);
  assert.match(globals, /\.query-form\s*\{/);
  assert.match(globals, /\.query-grid\s*\{/);
  assert.match(globals, /\.query-submit\s*\{/);

  for (const path of ["app/ChatClient.tsx", "app/search/page.tsx", "app/insights/page.tsx"]) {
    const source = readWebFile(path);
    assert.match(source, /className="glass query-form"/, `${path} should use the common query form shell`);
    assert.match(source, /className="query-grid"/, `${path} should use the common query grid`);
    assert.match(source, /className="query-submit/, `${path} should use the common submit button treatment`);
  }
});

test("Next.js applies baseline browser security headers", () => {
  const config = readWebFile("next.config.mjs");
  assert.match(config, /Content-Security-Policy/);
  assert.match(config, /frame-ancestors 'none'/);
  assert.match(config, /Strict-Transport-Security/);
  assert.match(config, /X-Content-Type-Options/);
  assert.match(config, /Permissions-Policy/);
  assert.match(config, /poweredByHeader: false/);
});
