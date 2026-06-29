-- Admin dashboard RPCs.
-- Web routes call these with the logged-in user's JWT. No service_role key is
-- needed in the web app; each function verifies auth.uid() is an admin.

create or replace function current_user_is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from access_roles r
    where r.user_id = auth.uid()
      and r.role = 'admin'
  );
$$;

create or replace function require_current_user_admin()
returns void
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  if auth.uid() is null or not current_user_is_admin() then
    raise exception 'admin role required';
  end if;
end;
$$;

create or replace function raise_admin_required()
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  raise exception 'admin role required';
end;
$$;

create or replace function admin_dashboard_summary()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select case
    when not current_user_is_admin() then
      raise_admin_required()
    else jsonb_build_object(
      'zip_count', (select count(*) from zip_archives),
      'document_count', (select count(*) from documents),
      'chunk_count', (select count(*) from doc_chunks),
      'review_required', (select count(*) from documents where review_required),
      'status_counts', coalesce((
        select jsonb_object_agg(status_text, n)
        from (
          select status::text as status_text, count(*) as n
          from documents
          group by status
          order by status::text
        ) s
      ), '{}'::jsonb),
      'category_counts', coalesce((
        select jsonb_object_agg(category, n)
        from (
          select coalesce(task_category, '미분류') as category, count(*) as n
          from documents
          group by coalesce(task_category, '미분류')
          order by count(*) desc, coalesce(task_category, '미분류')
          limit 12
        ) c
      ), '{}'::jsonb),
      'latest_imported_at', (select max(imported_at) from zip_archives),
      'latest_processed_at', (select max(processed_at) from documents)
    )
  end;
$$;

create or replace function admin_review_documents(limit_count int default 50)
returns table (
  id uuid,
  filename text,
  source_path text,
  path_in_zip text,
  status doc_status,
  dept text,
  security_level text,
  task_category text,
  classification_confidence numeric,
  review_required boolean,
  doc_date date,
  error text
)
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  perform require_current_user_admin();

  return query
  select
    d.id,
    d.filename,
    z.source_path,
    d.path_in_zip,
    d.status,
    d.dept,
    d.security_level,
    d.task_category,
    d.classification_confidence,
    d.review_required,
    d.doc_date,
    d.error
  from documents d
  left join zip_archives z on z.id = d.zip_id
  where d.review_required
     or d.status in ('pending_password', 'pending_ocr', 'quarantine', 'failed')
  order by d.created_at desc
  limit greatest(1, least(coalesce(limit_count, 50), 200));
end;
$$;

create or replace function admin_update_document_metadata(
  document_id uuid,
  dept_text text,
  security_level_text text,
  task_category_text text,
  review_required_value boolean
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  perform require_current_user_admin();

  update documents
  set dept = dept_text,
      security_level = security_level_text,
      task_category = task_category_text,
      review_required = coalesce(review_required_value, review_required)
  where id = document_id;
end;
$$;

revoke all on function current_user_is_admin() from public;
revoke all on function require_current_user_admin() from public;
revoke all on function admin_dashboard_summary() from public;
revoke all on function raise_admin_required() from public;
revoke all on function admin_review_documents(int) from public;
revoke all on function admin_update_document_metadata(uuid, text, text, text, boolean) from public;

grant execute on function current_user_is_admin() to authenticated;
grant execute on function admin_dashboard_summary() to authenticated;
grant execute on function admin_review_documents(int) to authenticated;
grant execute on function admin_update_document_metadata(uuid, text, text, text, boolean) to authenticated;
