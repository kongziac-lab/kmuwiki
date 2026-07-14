import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  buildIngestCommand,
  isPrivateNetworkHost,
  isSupportedLocalFolderPath,
  isLocalIngestAllowed,
  isZipDirAllowed,
  parseAllowedIngestDirs,
  resolveZipDir,
} from "../lib/localIngest.ts";

const root = path.resolve(process.cwd(), "..");
const migrationPath = path.join(root, "supabase/migrations/0006_admin_dashboard_rpc.sql");

test("admin dashboard migration defines required SECURITY DEFINER RPCs", () => {
  assert.equal(existsSync(migrationPath), true);
  const sql = readFileSync(migrationPath, "utf8");

  for (const name of [
    "current_user_is_admin",
    "admin_dashboard_summary",
    "admin_review_documents",
    "admin_update_document_metadata",
  ]) {
    assert.match(sql, new RegExp(`create or replace function\\s+${name}\\b`, "i"));
  }
  assert.match(sql, /security definer/i);
  assert.match(sql, /auth\.uid\(\)/i);
});

test("admin summary API exposes storage health monitoring", () => {
  const route = readFileSync(new URL("../app/api/admin/summary/route.ts", import.meta.url), "utf8");

  assert.match(route, /admin_dashboard_summary/);
  assert.match(route, /admin_storage_health/);
  assert.match(route, /admin_search_monitoring_summary/);
  assert.match(route, /storage_health/);
  assert.match(route, /search_monitoring/);
});

test("local ingest is allowed only from local admin mode", () => {
  assert.equal(isLocalIngestAllowed({ nodeEnv: "production", requestHost: "kmuwiki.vercel.app" }), false);
  assert.equal(isLocalIngestAllowed({ nodeEnv: "development", requestHost: "localhost:3000" }), true);
  assert.equal(isLocalIngestAllowed({ nodeEnv: "development", requestHost: "172.20.4.55:3000" }), false);
  assert.equal(isLocalIngestAllowed({
    nodeEnv: "production",
    requestHost: "127.0.0.1:3000",
    enableFlag: "1",
    trustProxyHeaders: "1",
    clientAddress: "127.0.0.1",
  }), true);
  assert.equal(isLocalIngestAllowed({ nodeEnv: "production", requestHost: "kmuwiki.vercel.app", enableFlag: "1" }), false);
});

test("production local ingest trusts only explicitly enabled proxy client addresses", () => {
  assert.equal(isPrivateNetworkHost("172.20.4.55:3000"), true);
  assert.equal(isPrivateNetworkHost("192.168.0.25:3000"), true);
  assert.equal(isPrivateNetworkHost("10.0.0.8"), true);
  assert.equal(isPrivateNetworkHost("kmuwiki.vercel.app"), false);

  assert.equal(isLocalIngestAllowed({ nodeEnv: "production", requestHost: "172.20.4.55:3000" }), false);
  assert.equal(isLocalIngestAllowed({
    nodeEnv: "production",
    requestHost: "kmuwiki.internal",
    enableFlag: "1",
    trustProxyHeaders: "1",
    clientAddress: "172.20.4.55",
  }), true);
  assert.equal(isLocalIngestAllowed({
    nodeEnv: "production",
    requestHost: "172.20.4.55:3000",
    enableFlag: "1",
    trustProxyHeaders: "1",
    clientAddress: "203.0.113.10",
  }), false);
});

test("ingest command uses configured zip folder without shell interpolation", () => {
  const zipDir = resolveZipDir({ KMU_ZIP_DIR: String.raw`\\NAS\KMU Wiki\2026` });
  const command = buildIngestCommand(zipDir, { pythonBin: "python", ingestCwd: String.raw`C:\kmuwiki\ingest` });

  assert.equal(command.command, "python");
  assert.deepEqual(command.args, ["-m", "kmu_ingest.cli", "run", "--path", String.raw`\\NAS\KMU Wiki\2026`]);
  assert.equal(command.cwd, String.raw`C:\kmuwiki\ingest`);
});

test("web local ingest can use an admin supplied absolute zip folder", () => {
  assert.equal(isSupportedLocalFolderPath("/Users/kdh/Documents/KMU-Wiki-Zips"), true);
  assert.equal(isSupportedLocalFolderPath(String.raw`Z:\KMU-Wiki-Zips`), true);
  assert.equal(isSupportedLocalFolderPath(String.raw`\\NAS\KMU-Wiki-Zips`), true);
  assert.equal(isSupportedLocalFolderPath("KMU-Wiki-Zips"), false);

  const requested = resolveZipDir({}, String.raw`\\NAS\KMU-Wiki-Zips\2026`);
  const command = buildIngestCommand(requested, { pythonBin: "python", ingestCwd: String.raw`C:\kmuwiki\ingest` });

  assert.deepEqual(command.args, ["-m", "kmu_ingest.cli", "run", "--path", String.raw`\\NAS\KMU-Wiki-Zips\2026`]);
});

test("zip folder allowlist restricts admin supplied paths when configured", () => {
  // 미설정이면 실행 경로를 신뢰할 근거가 없으므로 fail-closed 한다.
  assert.equal(isZipDirAllowed(String.raw`Z:\anything`, parseAllowedIngestDirs(undefined)), false);
  assert.equal(isZipDirAllowed("/tmp/x", parseAllowedIngestDirs("")), false);

  const allowed = parseAllowedIngestDirs(String.raw`\\NAS\jdh\kmuwiki, Z:\KMU-Wiki-Zips`);
  // 하위 경로·대소문자·구분자(\, /) 차이는 허용
  assert.equal(isZipDirAllowed(String.raw`\\NAS\jdh\kmuwiki\2026`, allowed), true);
  assert.equal(isZipDirAllowed("//nas/JDH/kmuwiki", allowed), true);
  assert.equal(isZipDirAllowed(String.raw`Z:\KMU-Wiki-Zips\2025`, allowed), true);
  // 목록 밖·이름 접두사 우회·".." 탈출은 거부
  assert.equal(isZipDirAllowed(String.raw`\\NAS\jdh\other`, allowed), false);
  assert.equal(isZipDirAllowed(String.raw`\\NAS\jdh\kmuwiki-evil`, allowed), false);
  assert.equal(isZipDirAllowed(String.raw`\\NAS\jdh\kmuwiki\..\secret`, allowed), false);
});

test("admin ingest route enforces the zip folder allowlist", () => {
  const route = readFileSync(new URL("../app/api/admin/ingest/route.ts", import.meta.url), "utf8");

  assert.match(route, /parseAllowedIngestDirs\(process\.env\.KMU_LOCAL_INGEST_ALLOWED_DIRS\)/);
  assert.match(route, /isZipDirAllowed\(status\.zipDir, allowedDirs\)/);
  assert.match(route, /status: 403/);
});

test("admin ingest page posts the selected local folder path", () => {
  const page = readFileSync(new URL("../app/admin/page.tsx", import.meta.url), "utf8");
  const route = readFileSync(new URL("../app/api/admin/ingest/route.ts", import.meta.url), "utf8");

  assert.match(page, /zipDirInput/);
  assert.match(page, /로컬 ZIP 폴더/);
  assert.match(page, /JSON\.stringify\(\{ zipDir: zipDirInput\.trim\(\) \}\)/);
  assert.match(route, /readIngestBody/);
  assert.match(route, /ingestStatus\(req, body\.zipDir\)/);
  assert.match(route, /resolveZipDir\(process\.env, requestedZipDir\)/);
});

test("admin page presents dashboard cards and a collapsed review queue", () => {
  const page = readFileSync(new URL("../app/admin/page.tsx", import.meta.url), "utf8");
  const globals = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

  assert.match(page, /className="admin-metric/);
  assert.match(page, /className="admin-dashboard-grid"/);
  assert.match(page, /<details className="admin-review-panel">/);
  assert.doesNotMatch(page, /<details className="admin-review-panel" open>/);
  assert.match(page, /<summary className="admin-review-summary">/);

  assert.match(globals, /\.admin-metric\s*\{/);
  assert.match(globals, /\.admin-metric::before\s*\{/);
  assert.match(globals, /place-items: center/);
  assert.match(globals, /--metric-accent/);
  assert.match(globals, /\.admin-dashboard-grid\s*\{/);
  assert.match(globals, /\.admin-review-panel\s*\{/);
});
