# Admin Dashboard And Local Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an authenticated admin dashboard that can inspect Supabase ingest status and trigger local-folder ingest only when the web server is running on the operator's machine.

**Architecture:** Supabase Auth remains the login source. Admin reads/writes use SECURITY DEFINER RPC functions that verify `auth.uid()` has `access_roles.role='admin'`, avoiding service role keys in the web app. Local ingest execution is a Next.js server route that is disabled in production and spawns the Python CLI using `KMU_ZIP_DIR`, so Mac, Windows, or NAS paths are environment configuration rather than code.

**Tech Stack:** Next.js App Router, Supabase JS, PostgreSQL RPC migrations, Python ingest CLI, Node built-in test runner.

---

### Task 1: Admin RPC Surface

**Files:**
- Create: `supabase/migrations/0006_admin_dashboard_rpc.sql`
- Test: `web/tests/adminApi.test.ts`

- [ ] Write failing tests that expect admin RPC names `admin_dashboard_summary`, `admin_review_documents`, and `admin_update_document_metadata` to exist in migrations.
- [ ] Run `npm test` and confirm the new test fails because migration `0006` does not exist.
- [ ] Add SECURITY DEFINER functions. Each function checks admin role with `auth.uid()`, returns dashboard counts or review rows, and updates only editable metadata fields.
- [ ] Run `npm test` and confirm the migration-name tests pass.

### Task 2: Local Ingest API Guard

**Files:**
- Create: `web/lib/adminAuth.ts`
- Create: `web/lib/localIngest.ts`
- Create: `web/app/api/admin/summary/route.ts`
- Create: `web/app/api/admin/review/route.ts`
- Create: `web/app/api/admin/ingest/route.ts`
- Test: `web/tests/adminApi.test.ts`

- [ ] Write failing tests for `isLocalIngestAllowed` so production is blocked and localhost/non-production is allowed.
- [ ] Write failing tests for building the ingest command from `KMU_ZIP_DIR`, including Windows/NAS-style paths.
- [ ] Implement admin auth helpers, Supabase RPC proxy routes, and a local ingest route that requires Authorization, checks admin RPC, blocks production, and runs `python -m kmu_ingest.cli run --path <KMU_ZIP_DIR>`.
- [ ] Run `npm test` and confirm the focused tests pass.

### Task 3: Admin Dashboard UI

**Files:**
- Create: `web/app/admin/page.tsx`
- Modify: `web/app/page.tsx`
- Modify: `web/app/search/page.tsx`
- Modify: `web/.env.example`
- Modify: `README.md`
- Modify: `ingest/README.md`

- [ ] Build `/admin` as a restrained operational dashboard: login gate, status counts, review-required table, local ingest path/status, and disabled production ingest state.
- [ ] Add navigation links to Admin from chat/search.
- [ ] Document `KMU_ZIP_DIR` examples for macOS, Windows drive letters, and NAS UNC paths.
- [ ] Run `npm test`, `npm run build`, `python3 -m unittest discover -s tests`, and `git diff --check`.
