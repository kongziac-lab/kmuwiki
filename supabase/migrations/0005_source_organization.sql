-- Source ZIP organization and automatic knowledge-base classification metadata.

alter table zip_archives
  add column if not exists source_path text;

update zip_archives
set source_path = filename
where source_path is null;

create index if not exists idx_zip_archives_source_path
  on zip_archives(source_path);

alter table documents
  add column if not exists classification_confidence numeric not null default 0,
  add column if not exists review_required boolean not null default true;

create index if not exists idx_documents_task_category
  on documents(task_category);

create index if not exists idx_documents_review_required
  on documents(review_required);
