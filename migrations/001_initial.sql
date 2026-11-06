-- Supabase PostgreSQL schema. The application can also create these tables on startup.
create table if not exists transactions (
 id bigserial primary key, user_id varchar(128) not null, kind varchar(24) not null,
 amount numeric(14,2) not null check (amount > 0), currency varchar(3) not null default 'INR',
 category varchar(80) not null default 'Other', description varchar(300) not null,
 merchant varchar(200), occurred_on date not null, created_at timestamp not null default now(),
 source varchar(24) not null default 'manual', receipt_path varchar(500), deleted boolean not null default false
);
create index if not exists ix_transactions_user_id on transactions(user_id);
create index if not exists ix_transactions_user_date on transactions(user_id, occurred_on);
create index if not exists ix_transactions_category on transactions(category);
create table if not exists budgets (
 id bigserial primary key, user_id varchar(128) not null, category varchar(80) not null default 'Overall',
 month varchar(7) not null, amount numeric(14,2) not null check (amount > 0)
);
create index if not exists ix_budgets_user_month on budgets(user_id, month);
create table if not exists audit_logs (
 id bigserial primary key, user_id varchar(128) not null, action varchar(40) not null,
 transaction_id bigint, created_at timestamp not null default now()
);

-- Enable RLS before connecting a browser directly to Supabase. This app keeps DB access server-side.
alter table transactions enable row level security;
alter table budgets enable row level security;
alter table audit_logs enable row level security;
