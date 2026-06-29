-- Access audit RPC.
-- The RAG service calls this with the user's JWT-bound Supabase client.
-- SECURITY DEFINER lets authenticated users write their own audit events without
-- granting direct INSERT on access_log.

create or replace function log_access(
  action_text text,
  query_text text default null,
  document_ids uuid[] default array[]::uuid[]
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  doc_id uuid;
begin
  if auth.uid() is null then
    raise exception 'authentication required';
  end if;

  if document_ids is null or array_length(document_ids, 1) is null then
    insert into access_log(user_id, document_id, action, query)
    values (auth.uid(), null, action_text, query_text);
    return;
  end if;

  foreach doc_id in array document_ids loop
    insert into access_log(user_id, document_id, action, query)
    values (auth.uid(), doc_id, action_text, query_text);
  end loop;
end;
$$;

revoke all on function log_access(text, text, uuid[]) from public;
grant execute on function log_access(text, text, uuid[]) to authenticated;
