# Flat ZIP Knowledge Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users drop all source ZIP files into one folder while the ingest pipeline stores source paths and organizes the knowledge base with document metadata, embeddings, and review flags.

**Architecture:** Keep the filesystem as an input queue and Supabase as the organization layer. The watcher recursively scans ZIPs and records `source_path`; the pipeline classifies document task category from filename/body text and stores confidence plus review-required metadata.

**Tech Stack:** Python ingest worker, Supabase migrations, unittest, existing fake embedder.

---

### Task 1: Source ZIP Path Tracking

**Files:**
- Modify: `ingest/kmu_ingest/watcher.py`
- Modify: `ingest/kmu_ingest/store.py`
- Modify: `ingest/kmu_ingest/backfill.py`
- Create: `supabase/migrations/0005_source_organization.sql`
- Test: `ingest/tests/test_watcher.py`
- Test: `ingest/tests/test_backfill.py`

- [ ] Write failing tests for recursive ZIP discovery, relative `source_path` registration, and backfill lookup by nested source path.
- [ ] Run the focused tests and confirm they fail because the current watcher is flat and `source_path` is not stored.
- [ ] Implement recursive scanning, optional `zip_root` on `iter_work`, `register_zip(..., source_path=...)`, and backfill source path lookup.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Knowledge Organization Metadata

**Files:**
- Create: `ingest/kmu_ingest/classification.py`
- Modify: `ingest/kmu_ingest/models.py`
- Modify: `ingest/kmu_ingest/metadata.py`
- Modify: `ingest/kmu_ingest/pipeline.py`
- Modify: `ingest/kmu_ingest/store.py`
- Create: `ingest/tests/test_classification.py`
- Modify: `ingest/tests/test_pipeline.py`

- [ ] Write failing tests for classifying 파견교환학생 and low-confidence unknown documents.
- [ ] Run the focused tests and confirm they fail because classification fields do not exist.
- [ ] Add `task_category`, `classification_confidence`, and `review_required` to `FileMeta`, classification helpers, pipeline metadata enrichment, and Supabase upsert rows.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `ingest/README.md`
- Modify: `plans/kmu-wiki-master-plan.md`

- [ ] Document that source ZIPs can live in one folder and knowledge organization is metadata/embedding driven.
- [ ] Run `python3 -m unittest discover tests` from `ingest`.
- [ ] Run `git diff --check`.
