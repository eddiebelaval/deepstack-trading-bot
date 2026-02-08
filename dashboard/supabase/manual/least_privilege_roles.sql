-- Least-Privilege Roles for DeepStack Control Plane (Manual)
--
-- Goal:
-- - Dashboard server can insert commands and read status/state.
-- - Bot can read pending commands + write state/logs + update command status.
--
-- Notes:
-- - Run as an admin role in Postgres (not from the browser).
-- - Adjust password management to your environment (Vault, 1Password, etc).

-- 1) Create roles (no superuser, no createdb, no createrole)
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'deepstack_dashboard_rw') then
    create role deepstack_dashboard_rw login;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'deepstack_bot_rw') then
    create role deepstack_bot_rw login;
  end if;
end $$;

-- 2) Revoke broad access (defense in depth)
revoke all on schema public from deepstack_dashboard_rw;
revoke all on schema public from deepstack_bot_rw;

grant usage on schema public to deepstack_dashboard_rw;
grant usage on schema public to deepstack_bot_rw;

-- 3) Dashboard permissions (read most tables + insert commands)
grant select on
  deepstack_trades,
  deepstack_daily_summary,
  deepstack_opportunities,
  deepstack_dashboard_state,
  deepstack_strategy_status,
  deepstack_log_entries,
  deepstack_market_snapshots,
  deepstack_performance_metrics,
  deepstack_bot_config,
  deepstack_bot_commands
to deepstack_dashboard_rw;

grant insert on deepstack_bot_commands to deepstack_dashboard_rw;

-- Optional: allow dashboard to update bot_config (if you use /api/config PATCH)
grant update (mode, poll_interval_seconds, max_position_size_cents, daily_loss_limit_cents, kelly_fraction, profile, use_grok)
on deepstack_bot_config to deepstack_dashboard_rw;

-- 4) Bot permissions
grant select on deepstack_bot_commands to deepstack_bot_rw;
grant update (status, result, executed_at) on deepstack_bot_commands to deepstack_bot_rw;

grant select, update on deepstack_bot_config to deepstack_bot_rw;
grant insert on
  deepstack_dashboard_state,
  deepstack_log_entries,
  deepstack_opportunities,
  deepstack_trades,
  deepstack_market_snapshots
to deepstack_bot_rw;

grant insert, update on deepstack_strategy_status to deepstack_bot_rw;

