---
name: kmu-wiki-search
description: Search KMU Wiki documents through the authenticated kmuwiki API, detect recurring work, and prepare evidence-backed workflow or report drafts without reading source ZIP files directly.
---

# KMU Wiki Search

Use this skill when the user asks Hermes to find KMU Wiki documents, improve a
search query, detect recurring administrative work, prepare next-year draft
candidates, or build a report from kmuwiki sources.

## Trust Boundary

- Never read original ZIP/HWP/PDF files from the NAS filesystem.
- Never query Supabase tables directly. Supabase Auth login for the dedicated
  limited kmuwiki account is allowed.
- Never use or request a Supabase service-role key.
- Use only the kmuwiki API helper in this skill. The API enforces user JWT,
  RLS, masking, rerank, and audit logging.

## Required Configuration

The Hermes container must have:

- `KMUWIKI_API_BASE_URL`: API base URL, for example `https://<app>/api`,
  `https://<app>/rag`, or `http://<rag-host>:8000`.
- Either `KMUWIKI_AUTH_TOKEN` for a one-off user JWT, or all of:
  `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
  `KMUWIKI_AUTH_EMAIL`, and `KMUWIKI_AUTH_PASSWORD`.
- `KMUWIKI_API_SECRET`: optional RAG shared secret for direct Python API calls.

The helper script is:

```sh
python /opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py
```

## Workflow

1. Extract likely filters from the user's request:
   - `source_year`: the year of documents to search.
   - `target_year`: the future year for draft generation.
   - `dept`: department filter when the user names one.
   - `k`: use 12 by default unless the user requests broader coverage.
2. Run `workflow` first for combined search and Hermes recurring-work output.
3. If the user needs only evidence snippets, run `search`.
4. If the user needs a formal report draft, run `reports` after search.
5. In the final response, separate:
   - best evidence sources,
   - recurring-work patterns,
   - draft/report candidates,
   - missing information or follow-up checks.

## Commands

Combined search plus recurring-work detection:

```sh
python /opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py workflow \
  --query "<question>" \
  --source-year 2026 \
  --target-year 2027 \
  --k 12
```

Search only:

```sh
python /opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py search \
  --query "<question>" \
  --source-year 2026 \
  --dept "<department>" \
  --k 12
```

Recurring work and next-year draft candidates:

```sh
python /opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py hermes \
  --query "<question>" \
  --source-year 2026 \
  --target-year 2027 \
  --k 12
```

Report draft:

```sh
python /opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py reports \
  --query "<question>" \
  --source-year 2026 \
  --target-year 2027 \
  --report-type result \
  --k 12
```

## Output Rules

- Treat API output as the only evidence.
- Cite `label`, `filename`, `doc_no`, `doc_date`, or `document_id` when present.
- If no source is returned, say that the authenticated kmuwiki search returned
  no accessible source for the current token and filters.
- Do not invent document numbers, departments, dates, or draft body text.
