-- Run this in the Supabase SQL Editor after a Hermes smoke test.
-- It verifies that the dedicated Hermes account generated access_log rows.

select
  al.at,
  u.email,
  al.action,
  al.query,
  al.document_id,
  al.result_count,
  al.latency_ms,
  al.rerank_provider,
  al.rerank_applied
from access_log al
left join auth.users u on u.id = al.user_id
where u.email = 'hermes-agent@kmu.local'
  and al.at > now() - interval '30 minutes'
order by al.at desc
limit 20;
