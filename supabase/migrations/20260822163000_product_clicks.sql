create table if not exists public.product_clicks (
  id bigint generated always as identity primary key,
  product_id text not null,
  source text not null default 'vitrine' check (char_length(source) between 1 and 30),
  clicked_at timestamptz not null default now()
);

create index if not exists product_clicks_product_idx
  on public.product_clicks(product_id, clicked_at desc);

create index if not exists product_clicks_time_idx
  on public.product_clicks(clicked_at desc);

alter table public.product_clicks enable row level security;

drop policy if exists "Visitors can register product clicks" on public.product_clicks;
create policy "Visitors can register product clicks"
  on public.product_clicks
  for insert
  to anon, authenticated
  with check (char_length(product_id) between 1 and 100 and char_length(source) between 1 and 30);

drop policy if exists "CEO can view product clicks" on public.product_clicks;
create policy "CEO can view product clicks"
  on public.product_clicks
  for select
  to authenticated
  using (lower(coalesce(auth.jwt()->>'email','')) = 'vivianeferreiracaroline@gmail.com');

revoke update, delete on public.product_clicks from anon, authenticated;
grant insert on public.product_clicks to anon, authenticated;
grant select on public.product_clicks to authenticated;
