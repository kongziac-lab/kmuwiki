import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  buildIngestCommand,
  isSupportedLocalFolderPath,
  isLocalIngestAllowed,
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

test("local ingest is allowed only from local admin mode", () => {
  assert.equal(isLocalIngestAllowed({ nodeEnv: "production", requestHost: "kmuwiki.vercel.app" }), false);
  assert.equal(isLocalIngestAllowed({ nodeEnv: "development", requestHost: "localhost:3000" }), true);
  assert.equal(isLocalIngestAllowed({ nodeEnv: "production", requestHost: "127.0.0.1:3000", enableFlag: "1" }), true);
  assert.equal(isLocalIngestAllowed({ nodeEnv: "production", requestHost: "kmuwiki.vercel.app", enableFlag: "1" }), false);
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
