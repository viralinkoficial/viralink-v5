create table if not exists public.campaign_queue (
  id bigint generated always as identity primary key,
  product_id text not null,
  product_name text not null,
  channel text not null check (channel in ('instagram','youtube','facebook','pinterest','blogger','tiktok','whatsapp')),
  scheduled_for timestamptz not null,
  status text not null default 'pending' check (status in ('pending','processing','scheduled','published','failed','paused','cancelled')),
  attempts integer not null default 0 check (attempts between 0 and 3),
  payload jsonb not null default '{}'::jsonb,
  external_id text,
  error_message text,
  created_by uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists campaign_queue_due_idx
  on public.campaign_queue(status, scheduled_for);

create index if not exists campaign_queue_product_channel_idx
  on public.campaign_queue(product_id, channel, created_at desc);

create unique index if not exists campaign_queue_unique_slot_idx
  on public.campaign_queue(channel, scheduled_for);

alter table public.campaign_queue enable row level security;

drop policy if exists "CEO can view campaign queue" on public.campaign_queue;
create policy "CEO can view campaign queue"
  on public.campaign_queue
  for select
  to authenticated
  using (lower(coalesce(auth.jwt()->>'email','')) = 'vivianeferreiracaroline@gmail.com');

revoke insert, update, delete on public.campaign_queue from anon, authenticated;
grant select on public.campaign_queue to authenticated;

create or replace function public.touch_campaign_queue_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists campaign_queue_touch_updated_at on public.campaign_queue;
create trigger campaign_queue_touch_updated_at
before update on public.campaign_queue
for each row execute function public.touch_campaign_queue_updated_at();
