create extension if not exists "pgcrypto";
create extension if not exists "citext";

create schema if not exists identity;
create schema if not exists academics;
create schema if not exists social;
create schema if not exists community;

create table if not exists identity.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email citext unique,
  display_name text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists identity.user_privacy_settings (
  user_id uuid primary key references identity.profiles(id) on delete cascade,
  share_courses_with_friends boolean not null default true,
  share_schedule_with_friends boolean not null default false,
  share_program_with_friends boolean not null default true,
  allow_friend_requests boolean not null default true,
  allow_nfc_discovery boolean not null default true,
  updated_at timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_profiles_updated_at on identity.profiles;
create trigger trg_profiles_updated_at
before update on identity.profiles
for each row
execute function public.set_updated_at();

create table if not exists academics.schools (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  country text,
  website text,
  timezone text,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_schools_name on academics.schools(name);

create table if not exists academics.programs (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references academics.schools(id) on delete cascade,
  name text not null,
  degree_level text,
  department_name text,
  created_at timestamptz not null default now()
);

create index if not exists idx_programs_school_id on academics.programs(school_id);
create index if not exists idx_programs_school_name on academics.programs(school_id, name);

create table if not exists academics.program_versions (
  id uuid primary key default gen_random_uuid(),
  program_id uuid not null references academics.programs(id) on delete cascade,
  catalog_year integer not null check (catalog_year >= 1900 and catalog_year <= 3000),
  version_label text,
  source_type text not null check (source_type in ('pdf', 'url', 'manual')),
  source_url text,
  source_file_path text,
  source_hash text,
  status text not null default 'pending' check (status in ('pending', 'processing', 'done', 'failed')),
  error_msg text,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_program_versions_program_year unique (program_id, catalog_year, version_label)
);

create index if not exists idx_program_versions_program_id on academics.program_versions(program_id);
create index if not exists idx_program_versions_status on academics.program_versions(status);
create index if not exists idx_program_versions_source_hash on academics.program_versions(source_hash);

drop trigger if exists trg_program_versions_updated_at on academics.program_versions;
create trigger trg_program_versions_updated_at
before update on academics.program_versions
for each row
execute function public.set_updated_at();

create table if not exists academics.program_requirement_categories (
  id uuid primary key default gen_random_uuid(),
  program_version_id uuid not null references academics.program_versions(id) on delete cascade,
  parent_id uuid references academics.program_requirement_categories(id) on delete cascade,
  name text not null,
  category_type text,
  min_courses integer,
  min_credits numeric(6,2),
  max_courses integer,
  note text,
  sort_order integer,
  created_at timestamptz not null default now()
);

create index if not exists idx_program_requirement_categories_program_version_id
  on academics.program_requirement_categories(program_version_id);

create index if not exists idx_program_requirement_categories_parent_id
  on academics.program_requirement_categories(parent_id);

create table if not exists academics.courses (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references academics.schools(id) on delete cascade,
  canonical_code text,
  canonical_name text not null,
  normalized_code text,
  normalized_name text,
  subject_code text,
  course_number text,
  credits_default numeric(6,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_courses_school_id on academics.courses(school_id);
create index if not exists idx_courses_school_normalized_code on academics.courses(school_id, normalized_code);
create index if not exists idx_courses_school_normalized_name on academics.courses(school_id, normalized_name);

create unique index if not exists uq_courses_school_normalized_code_not_null
on academics.courses(school_id, normalized_code)
where normalized_code is not null;

drop trigger if exists trg_courses_updated_at on academics.courses;
create trigger trg_courses_updated_at
before update on academics.courses
for each row
execute function public.set_updated_at();

create table if not exists academics.course_versions (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references academics.courses(id) on delete cascade,
  catalog_year integer not null check (catalog_year >= 1900 and catalog_year <= 3000),
  code text,
  title text not null,
  description text,
  credits numeric(6,2),
  hours text,
  language text,
  grading text,
  raw_text text,
  source_program_version_id uuid references academics.program_versions(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_course_versions_course_id on academics.course_versions(course_id);
create index if not exists idx_course_versions_catalog_year on academics.course_versions(catalog_year);
create index if not exists idx_course_versions_source_program_version_id
  on academics.course_versions(source_program_version_id);

drop trigger if exists trg_course_versions_updated_at on academics.course_versions;
create trigger trg_course_versions_updated_at
before update on academics.course_versions
for each row
execute function public.set_updated_at();

create table if not exists academics.program_course_requirements (
  id uuid primary key default gen_random_uuid(),
  category_id uuid not null references academics.program_requirement_categories(id) on delete cascade,
  program_version_id uuid not null references academics.program_versions(id) on delete cascade,
  course_version_id uuid not null references academics.course_versions(id) on delete cascade,
  requirement_type text not null check (requirement_type in ('required', 'elective', 'optional')),
  term_recommendation text,
  credits_counted numeric(6,2),
  note text,
  created_at timestamptz not null default now(),
  constraint uq_program_course_requirements unique (category_id, course_version_id)
);

create index if not exists idx_program_course_requirements_program_version_id
  on academics.program_course_requirements(program_version_id);

create index if not exists idx_program_course_requirements_course_version_id
  on academics.program_course_requirements(course_version_id);

create table if not exists academics.course_prerequisite_rules (
  id uuid primary key default gen_random_uuid(),
  course_version_id uuid not null references academics.course_versions(id) on delete cascade,
  raw_text text,
  parsed_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_course_prerequisite_rules_course_version_id
  on academics.course_prerequisite_rules(course_version_id);

create table if not exists academics.course_prerequisite_edges (
  id uuid primary key default gen_random_uuid(),
  course_version_id uuid not null references academics.course_versions(id) on delete cascade,
  prerequisite_course_version_id uuid not null references academics.course_versions(id) on delete cascade,
  relation_type text not null check (relation_type in ('prerequisite', 'corequisite', 'recommended')),
  group_no integer,
  min_grade text,
  note text,
  constraint chk_course_prerequisite_not_self check (course_version_id <> prerequisite_course_version_id),
  constraint uq_course_prerequisite_edge unique (course_version_id, prerequisite_course_version_id, relation_type, group_no)
);

create index if not exists idx_course_prerequisite_edges_course_version_id
  on academics.course_prerequisite_edges(course_version_id);

create index if not exists idx_course_prerequisite_edges_prerequisite_course_version_id
  on academics.course_prerequisite_edges(prerequisite_course_version_id);

create table if not exists academics.course_sections (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references academics.schools(id) on delete cascade,
  course_version_id uuid not null references academics.course_versions(id) on delete cascade,
  term_code text not null,
  section_code text not null,
  instructor text,
  capacity integer,
  campus text,
  delivery_mode text check (delivery_mode in ('in_person', 'online', 'hybrid')),
  unique_key text,
  created_at timestamptz not null default now()
);

create index if not exists idx_course_sections_course_version_term
  on academics.course_sections(course_version_id, term_code);

create unique index if not exists uq_course_sections_unique_key
  on academics.course_sections(unique_key)
  where unique_key is not null;

create table if not exists academics.meeting_times (
  id uuid primary key default gen_random_uuid(),
  section_id uuid not null references academics.course_sections(id) on delete cascade,
  day_of_week integer not null check (day_of_week between 1 and 7),
  start_time time not null,
  end_time time not null,
  timezone text,
  start_date date,
  end_date date,
  location text,
  location_extra jsonb not null default '{}'::jsonb,
  recurrence text check (recurrence in ('weekly', 'biweekly', 'irregular')),
  weeks text,
  constraint chk_meeting_times_time_range check (start_time < end_time)
);

create index if not exists idx_meeting_times_section_id on academics.meeting_times(section_id);

create table if not exists academics.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references identity.profiles(id) on delete set null,
  school_id uuid references academics.schools(id) on delete set null,
  program_version_id uuid references academics.program_versions(id) on delete set null,
  job_type text not null check (job_type in ('parse_catalog', 'merge_courses', 'import_sections', 'resolve_schedule')),
  status text not null default 'pending' check (status in ('pending', 'processing', 'done', 'failed')),
  input_payload jsonb not null default '{}'::jsonb,
  output_payload jsonb not null default '{}'::jsonb,
  error_msg text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create index if not exists idx_processing_jobs_user_id on academics.processing_jobs(user_id);
create index if not exists idx_processing_jobs_status on academics.processing_jobs(status);
create index if not exists idx_processing_jobs_program_version_id on academics.processing_jobs(program_version_id);

create table if not exists academics.course_merge_candidates (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references academics.schools(id) on delete cascade,
  left_course_id uuid not null references academics.courses(id) on delete cascade,
  right_course_id uuid not null references academics.courses(id) on delete cascade,
  score numeric(5,4) not null,
  reason jsonb not null default '{}'::jsonb,
  decided_status text not null default 'pending' check (decided_status in ('pending', 'merged', 'rejected')),
  decided_by uuid references identity.profiles(id) on delete set null,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  constraint chk_course_merge_not_self check (left_course_id <> right_course_id)
);

create index if not exists idx_course_merge_candidates_school_id
  on academics.course_merge_candidates(school_id);

create index if not exists idx_course_merge_candidates_decided_status
  on academics.course_merge_candidates(decided_status);

create table if not exists academics.user_programs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity.profiles(id) on delete cascade,
  school_id uuid not null references academics.schools(id) on delete cascade,
  program_id uuid not null references academics.programs(id) on delete cascade,
  program_version_id uuid references academics.program_versions(id) on delete set null,
  start_year integer check (start_year >= 1900 and start_year <= 3000),
  expected_grad_year integer check (expected_grad_year >= 1900 and expected_grad_year <= 3000),
  is_primary boolean not null default true,
  status text not null default 'active' check (status in ('active', 'graduated', 'dropped', 'transferred')),
  created_at timestamptz not null default now()
);

create index if not exists idx_user_programs_user_id on academics.user_programs(user_id);
create index if not exists idx_user_programs_program_id on academics.user_programs(program_id);

create unique index if not exists uq_user_programs_primary_per_user
on academics.user_programs(user_id)
where is_primary = true and status = 'active';

create table if not exists academics.user_courses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity.profiles(id) on delete cascade,
  course_id uuid not null references academics.courses(id) on delete cascade,
  course_version_id uuid references academics.course_versions(id) on delete set null,
  status text not null check (status in ('planned', 'selected', 'in_progress', 'completed', 'dropped')),
  grade text,
  term_code text,
  source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_user_courses_user_id on academics.user_courses(user_id);
create index if not exists idx_user_courses_user_status on academics.user_courses(user_id, status);
create index if not exists idx_user_courses_user_course on academics.user_courses(user_id, course_id);

create unique index if not exists uq_user_courses_user_course_term
on academics.user_courses(user_id, course_id, term_code)
where term_code is not null;

drop trigger if exists trg_user_courses_updated_at on academics.user_courses;
create trigger trg_user_courses_updated_at
before update on academics.user_courses
for each row
execute function public.set_updated_at();

create table if not exists academics.user_term_plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity.profiles(id) on delete cascade,
  term_code text not null,
  title text,
  status text not null default 'draft' check (status in ('draft', 'finalized')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_user_term_plans_user_id on academics.user_term_plans(user_id);
create index if not exists idx_user_term_plans_user_term on academics.user_term_plans(user_id, term_code);

drop trigger if exists trg_user_term_plans_updated_at on academics.user_term_plans;
create trigger trg_user_term_plans_updated_at
before update on academics.user_term_plans
for each row
execute function public.set_updated_at();

create table if not exists academics.user_term_plan_sections (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null references academics.user_term_plans(id) on delete cascade,
  section_id uuid not null references academics.course_sections(id) on delete cascade,
  priority integer,
  status text not null check (status in ('candidate', 'chosen', 'conflict', 'rejected')),
  created_at timestamptz not null default now(),
  constraint uq_user_term_plan_sections unique (plan_id, section_id)
);

create index if not exists idx_user_term_plan_sections_plan_id
  on academics.user_term_plan_sections(plan_id);

create table if not exists social.nfc_tags (
  id uuid primary key default gen_random_uuid(),
  tag_uid text not null unique,
  claimed_by_user_id uuid references identity.profiles(id) on delete set null,
  claimed_at timestamptz,
  status text not null default 'unclaimed' check (status in ('unclaimed', 'claimed', 'disabled')),
  created_at timestamptz not null default now()
);

create table if not exists social.nfc_scan_logs (
  id uuid primary key default gen_random_uuid(),
  tag_id uuid not null references social.nfc_tags(id) on delete cascade,
  scanned_by_user_id uuid references identity.profiles(id) on delete set null,
  action text not null check (action in ('claim', 'connect', 'invalid')),
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_nfc_scan_logs_tag_id on social.nfc_scan_logs(tag_id);
create index if not exists idx_nfc_scan_logs_scanned_by_user_id on social.nfc_scan_logs(scanned_by_user_id);

create table if not exists social.friendships (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity.profiles(id) on delete cascade,
  friend_id uuid not null references identity.profiles(id) on delete cascade,
  user_low uuid generated always as (least(user_id, friend_id)) stored,
  user_high uuid generated always as (greatest(user_id, friend_id)) stored,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'blocked')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_friendships_not_self check (user_id <> friend_id),
  constraint uq_friendships_pair unique (user_low, user_high)
);

create index if not exists idx_friendships_user_id on social.friendships(user_id);
create index if not exists idx_friendships_friend_id on social.friendships(friend_id);
create index if not exists idx_friendships_status on social.friendships(status);

drop trigger if exists trg_friendships_updated_at on social.friendships;
create trigger trg_friendships_updated_at
before update on social.friendships
for each row
execute function public.set_updated_at();

create table if not exists social.chats (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('direct', 'group')),
  created_at timestamptz not null default now()
);

create table if not exists social.chat_participants (
  chat_id uuid not null references social.chats(id) on delete cascade,
  user_id uuid not null references identity.profiles(id) on delete cascade,
  joined_at timestamptz not null default now(),
  last_read_message_id uuid,
  primary key (chat_id, user_id)
);

create index if not exists idx_chat_participants_user_id
  on social.chat_participants(user_id);

create table if not exists social.messages (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references social.chats(id) on delete cascade,
  sender_id uuid not null references identity.profiles(id) on delete cascade,
  content text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists idx_messages_chat_id_created_at
  on social.messages(chat_id, created_at);

create index if not exists idx_messages_sender_id
  on social.messages(sender_id);

drop trigger if exists trg_messages_updated_at on social.messages;
create trigger trg_messages_updated_at
before update on social.messages
for each row
execute function public.set_updated_at();

alter table social.chat_participants
  add constraint fk_chat_participants_last_read_message
  foreign key (last_read_message_id)
  references social.messages(id)
  on delete set null;

create table if not exists community.communities (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name text not null,
  introduction text,
  icon text,
  created_at timestamptz not null default now()
);

create table if not exists community.posts (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references identity.profiles(id) on delete cascade,
  community_id uuid references community.communities(id) on delete set null,
  content text not null,
  attachments jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists idx_posts_author_id on community.posts(author_id);
create index if not exists idx_posts_community_id_created_at
  on community.posts(community_id, created_at desc);

drop trigger if exists trg_posts_updated_at on community.posts;
create trigger trg_posts_updated_at
before update on community.posts
for each row
execute function public.set_updated_at();

create table if not exists community.comments (
  id uuid primary key default gen_random_uuid(),
  post_id uuid not null references community.posts(id) on delete cascade,
  author_id uuid not null references identity.profiles(id) on delete cascade,
  parent_comment_id uuid references community.comments(id) on delete cascade,
  content text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists idx_comments_post_id_created_at
  on community.comments(post_id, created_at);

create index if not exists idx_comments_parent_comment_id
  on community.comments(parent_comment_id);

create index if not exists idx_comments_author_id
  on community.comments(author_id);

drop trigger if exists trg_comments_updated_at on community.comments;
create trigger trg_comments_updated_at
before update on community.comments
for each row
execute function public.set_updated_at();

create table if not exists community.post_votes (
  post_id uuid not null references community.posts(id) on delete cascade,
  user_id uuid not null references identity.profiles(id) on delete cascade,
  value integer not null check (value in (1, -1)),
  created_at timestamptz not null default now(),
  primary key (post_id, user_id)
);

create index if not exists idx_post_votes_user_id
  on community.post_votes(user_id);

create table if not exists community.comment_votes (
  comment_id uuid not null references community.comments(id) on delete cascade,
  user_id uuid not null references identity.profiles(id) on delete cascade,
  value integer not null check (value in (1, -1)),
  created_at timestamptz not null default now(),
  primary key (comment_id, user_id)
);

create index if not exists idx_comment_votes_user_id
  on community.comment_votes(user_id);

