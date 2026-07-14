# Hermes Agent on DS920+ kmuwiki Search Skill PoC

This deploys Hermes Agent as a Synology DS920+ Docker service for kmuwiki
search orchestration. Hermes does not read raw ZIP/HWP/PDF files and does not
query Supabase tables directly. It calls the existing kmuwiki API, so RLS,
masking, rerank, and audit logging stay in the current trust boundary.

## Skill Paths

The skill is kept in three places inside the container:

- `/opt/data/skills/kmuwiki`: read-only bind mount from this repository. This is
  the source for updates and the stable path used by direct smoke tests.
- `/opt/data/skills/kmu-wiki-search`: canonical Hermes discovery path.
  `HERMES_HOME=/opt/data`, so Hermes scans `/opt/data/skills`.
- `/opt/data/home/.hermes/skills/kmu-wiki-search`: compatibility copy for
  diagnostics and older profile-home assumptions.

`start-hermes.sh` syncs the repository-mounted skill into the Docker-managed
volume before starting the gateway.

## Install On NAS

Copy this folder to the NAS, then run on the NAS through SSH, DSM Task
Scheduler, or the DSM terminal:

```sh
export HOME=/root
cd /volume1/jdh/repo/deploy/hermes
sh start-hermes.sh
```

If `.env` does not exist, the first run creates it and exits. Edit
`/volume1/jdh/repo/deploy/hermes/.env`, then run `sh start-hermes.sh` again.

## Required `.env` Values

- `API_SERVER_KEY`: strong bearer token for the Hermes API server.
- `KMUWIKI_API_BASE_URL`: kmuwiki API base URL, such as `https://<app>/api`.
- `NEXT_PUBLIC_SUPABASE_URL`: public Supabase project URL.
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`: public Supabase anon key.
- `KMUWIKI_AUTH_EMAIL`: dedicated limited kmuwiki account email.
- `KMUWIKI_AUTH_PASSWORD`: dedicated limited kmuwiki account password.
- `KMUWIKI_AUTH_TOKEN`: optional one-off user JWT override. Leave empty for
  dedicated-account login.
- `KMUWIKI_API_SECRET`: optional direct RAG shared secret.
- `OPENROUTER_API_KEY` or `OPENAI_API_KEY`: optional for basic search/workflow,
  but required for the final `/v1/chat/completions` smoke test.

Do not put a Supabase service-role key in Hermes.

## Dedicated Account

Create a normal Supabase Auth user, for example:

```text
hermes-agent@kmu.local
```

Grant only the departments Hermes should search:

```sql
insert into access_roles (user_id, dept, role)
select id, '<department-name>', 'staff'
from auth.users
where email = 'hermes-agent@kmu.local'
on conflict (user_id, dept)
do update set role = excluded.role;
```

Add one `access_roles` row per allowed department. Keep `role='staff'` unless
Hermes really needs broader access.

## Verify

Full operational check:

```sh
export HOME=/root
cd /volume1/jdh/repo/deploy/hermes
HERMES_FORCE_RECREATE=1 sh verify-hermes.sh
sh status-hermes.sh
```

Final check with chat-completions smoke test:

```sh
export HOME=/root
cd /volume1/jdh/repo/deploy/hermes
sh final-check-hermes.sh
```

If this fails with `FAILED_NO_INFERENCE_PROVIDER`, add one inference provider
key to `/volume1/jdh/repo/deploy/hermes/.env`, usually `OPENROUTER_API_KEY` or
`OPENAI_API_KEY`, then run the final check again.

The final check skips image pull by default (`HERMES_SKIP_PULL=1`) and forces one
container recreation so updated `.env` provider keys are copied into the Hermes
data volume.

The final check syncs whitelisted `.env` values into `/opt/data/.env` and
`/opt/data/home/.hermes/.env` inside the running container, then restarts the
container before verification. This avoids the slow one-off preparation
container path.

From Windows PowerShell, if SSH is enabled on the NAS:

```powershell
Y:\repo\deploy\hermes\run-final-check-from-windows.ps1
```

You may be prompted twice: once for SSH login and once for `sudo`, because
Docker on Synology usually requires root privileges.

For a double-click-friendly wrapper:

```powershell
Y:\repo\deploy\hermes\run-final-check-from-windows.cmd
```

For DSM Task Scheduler, use:

```text
Y:\repo\deploy\hermes\RUN_FINAL_CHECK_DSM_TASK.txt
```

Expected summary:

```text
start-hermes=0
wait-hermes-api=0
check-hermes=0
test-hermes-skills=0
test-kmuwiki=0
test-kmuwiki-workflow=0
```

Individual checks:

```sh
sh check-hermes.sh
sh test-hermes-skills.sh
sh test-kmuwiki.sh
sh test-kmuwiki-workflow.sh
```

Optional Hermes chat completion check:

```sh
HERMES_RUN_CHAT_TEST=1 sh verify-hermes.sh
sh status-hermes.sh
```

This calls `/v1/chat/completions` and may use the configured upstream LLM.

Logs are written to:

```text
/volume1/jdh/repo/deploy/hermes/logs/
```

If skill discovery still fails, inspect:

```sh
tail -n 200 /volume1/jdh/repo/deploy/hermes/logs/hermes-skills-test.log
```

## Direct Helper Test

Run inside the Hermes container:

```sh
docker compose exec hermes python /opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py search \
  --query "exchange student promotion" \
  --source-year 2026
```

## Ask Hermes

Example chat prompt:

```text
Use the kmu-wiki-search skill to find 2026 exchange student promotion work and prepare 2027 draft candidates.
```

## Access Log Check

After a search, workflow, or chat test, run `access-log-check.sql` in the
Supabase SQL Editor. It should show recent `access_log` rows for
`hermes-agent@kmu.local`.

## Cleanup

If old `hermes` folders or `hermes-*.log` files were accidentally created at the
NAS share root, preview cleanup first:

```sh
cd /volume1/jdh/repo/deploy/hermes
sh cleanup-hermes-root.sh --dry-run
```

Then remove only those old root artifacts:

```sh
sh cleanup-hermes-root.sh --apply
```

## Security Notes

- Keep `HERMES_API_BIND_ADDR=127.0.0.1` unless access is restricted by VPN,
  Tailscale, or a locked-down LAN firewall.
- Do not publish port `8642` directly to the internet.
- Do not mount `/volume1/jdh/kmuwiki/01_raw` into Hermes.
- Do not put Supabase service-role keys in Hermes.
