"""
Self-Knowledge Aggregator — Gathers DeepStack's Current State

Queries all 9 subsystems and assembles a structured context string
for Claude API calls. Combined with consciousness (~2500 tokens),
the total system prompt stays under ~4500 tokens.

This is what lets DeepStack answer "what's the scoop?" intelligently —
it has access to its own state, not just canned identity text.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def gather_self_knowledge(bot) -> str:
    """
    Gather the bot's current state from all subsystems into a context string.

    Designed to be called on each Telegram query. Pulls live data from:
    - Balance and positions (bot state)
    - Risk management (Kelly, EmotionalFirewall)
    - Strategy health (PerformanceTracker)
    - Market regime (GovernanceEngine)
    - Recent Captain's Log entries
    - Recent governance decisions
    - Health status
    - Active config

    Returns:
        ~2000-token context block as a formatted string.
    """
    sections: List[str] = []

    # 1. Balance, positions, daily P&L
    sections.append(_gather_portfolio(bot))

    # 2. Strategy health + Kelly stats
    sections.append(_gather_strategy_health(bot))

    # 3. Market regime + confidence
    sections.append(_gather_regime(bot))

    # 4. Risk management state
    sections.append(_gather_risk_state(bot))

    # 5. Recent Captain's Log entries
    log_section = await _gather_recent_log(bot)
    if log_section:
        sections.append(log_section)

    # 6. Recent governance decisions
    sections.append(_gather_governance(bot))

    # 7. Health status
    sections.append(_gather_health(bot))

    # 8. Capital allocation plan
    sections.append(_gather_allocation(bot))

    # 9. Active config summary
    sections.append(_gather_config(bot))

    return "\n\n".join(s for s in sections if s)


def _gather_portfolio(bot) -> str:
    """Current portfolio state."""
    lines = ["## Portfolio State"]

    balance = getattr(bot, 'risk', None)
    if balance:
        stats = balance.get_daily_stats()
        lines.append(f"- Balance: ${balance.account_balance:.2f}")
        lines.append(f"- Daily P&L: ${stats['daily_pnl']:.2f} ({stats['daily_pnl_pct']:+.1f}%)")
        lines.append(f"- Trades today: {stats['daily_trades']}")
        lines.append(f"- Loss limit remaining: ${stats['loss_limit_remaining']:.2f}")
        lines.append(f"- Can trade: {'yes' if stats['can_trade'] else 'NO — loss limit hit'}")
    else:
        lines.append("- Risk management not initialized")

    positions = getattr(bot, 'open_positions', {})
    lines.append(f"- Open positions: {len(positions)}")
    if positions:
        for ticker, pos in list(positions.items())[:5]:
            side = pos.get('side', '?')
            contracts = pos.get('contracts', pos.get('count', '?'))
            avg_price = pos.get('avg_price', pos.get('average_price', '?'))
            lines.append(f"  - {ticker}: {contracts} contracts ({side}) @ {avg_price}c")
        if len(positions) > 5:
            lines.append(f"  - ... and {len(positions) - 5} more")

    lines.append(f"- Bot running: {'yes' if getattr(bot, '_running', False) else 'no'}")
    lines.append(f"- Bot paused: {'yes' if getattr(bot, '_paused', False) else 'no'}")
    lines.append(f"- Dry run: {'yes' if getattr(bot, 'dry_run', False) else 'no'}")

    return "\n".join(lines)


def _gather_strategy_health(bot) -> str:
    """Strategy performance and Kelly stats from PerformanceTracker."""
    lines = ["## Strategy Health"]

    tracker = getattr(bot, 'performance_tracker', None)
    manager = getattr(bot, 'strategy_manager', None)

    if tracker:
        try:
            health_map = tracker.evaluate_all()
            for name, health in health_map.items():
                status = health.status if hasattr(health, 'status') else str(health)
                lines.append(f"- {name}: {status}")

                # Add blended stats if available
                try:
                    stats = tracker.get_blended_stats(name)
                    kelly_frac = stats.get('kelly_fraction', stats.get('adjusted_kelly', '?'))
                    lines.append(
                        f"  win_rate={stats['win_rate']:.1%}, "
                        f"avg_win={stats['avg_win_cents']:.1f}c, "
                        f"avg_loss={stats['avg_loss_cents']:.1f}c, "
                        f"kelly={kelly_frac}"
                    )
                except Exception:
                    pass
        except Exception as e:
            lines.append(f"- Error reading health: {e}")

    if manager:
        try:
            strategy_stats = manager.get_strategy_stats()
            enabled = [n for n, s in strategy_stats.items() if s.get('enabled')]
            disabled = [n for n, s in strategy_stats.items() if not s.get('enabled')]
            lines.append(f"- Enabled strategies: {', '.join(enabled) or 'none'}")
            if disabled:
                lines.append(f"- Disabled strategies: {', '.join(disabled)}")
        except Exception:
            pass

    # Structural awareness: paper vs live, governance priors, API requirements
    lines.append("")
    lines.append("### Execution Mode Per Strategy")
    config = getattr(bot, 'config', None)
    governor = getattr(bot, 'market_governor', None)
    if config and hasattr(config, 'strategies'):
        from kalshi_trader.market_governor import StrategyRegimeFitnessTracker
        has_priors = set()
        if governor and hasattr(governor, 'strategy_router'):
            has_priors = set(governor.strategy_router.DEFAULT_PRIORS.keys())

        for strat_cfg in config.strategies:
            name = getattr(strat_cfg, 'name', str(strat_cfg))
            enabled = getattr(strat_cfg, 'enabled', False)
            paper = getattr(strat_cfg, 'paper_trade', False)
            if not enabled:
                continue
            mode = "PAPER (simulated fills, no real orders)" if paper else "LIVE (real orders)"
            prior_status = "has governance priors" if name in has_priors else "NO governance priors (defaults to 0.5)"
            lines.append(f"- {name}: {mode} | {prior_status}")

    # Auto-disabled strategies
    auto_disabled = getattr(bot, '_auto_disabled_strategies', set())
    if auto_disabled:
        lines.append(f"- Auto-disabled (poor performance): {', '.join(auto_disabled)}")

    # Round 7 P0 (Sullivan): Execution history — trade counts and recency.
    # Self-knowledge must include what the bot has DONE, not just what it CAN do.
    journal = getattr(bot, 'journal', None)
    if journal:
        try:
            conn = journal._get_conn()
            # Total trade count
            total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            lines.append(f"- Total trades (all time): {total}")
            # Per-strategy trade counts
            rows = conn.execute(
                "SELECT strategy, COUNT(*) as cnt FROM trades "
                "GROUP BY strategy ORDER BY cnt DESC"
            ).fetchall()
            if rows:
                for row in rows:
                    lines.append(f"  - {row['strategy']}: {row['cnt']} trades")
            # Last trade time
            last_row = conn.execute(
                "SELECT created_at FROM trades ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if last_row:
                last_trade = last_row["created_at"]
                lines.append(f"- Last trade: {last_trade}")
                try:
                    last_dt = datetime.fromisoformat(str(last_trade).replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    delta = now - last_dt
                    days = delta.days
                    hours = delta.seconds // 3600
                    if days > 0:
                        lines.append(f"- Time since last trade: {days}d {hours}h")
                    else:
                        lines.append(f"- Time since last trade: {hours}h")
                except Exception:
                    pass
            else:
                lines.append("- Last trade: NEVER — zero trades executed")
        except Exception:
            pass

    # Inaction status
    inaction = getattr(bot, '_inaction_cycles', {})
    if inaction:
        alert_threshold = getattr(bot, '_inaction_alert_threshold', 50)
        for strat, cycles in inaction.items():
            if cycles >= alert_threshold:
                lines.append(f"- WARNING: '{strat}' has had ZERO opportunities for {cycles} cycles")

    return "\n".join(lines)


def _gather_regime(bot) -> str:
    """Current market regime from GovernanceEngine."""
    lines = ["## Market Regime"]

    governor = getattr(bot, 'market_governor', None)
    if governor:
        try:
            regime_snapshot = getattr(governor, 'current_regime', None)
            if regime_snapshot:
                lines.append(f"- Current regime: {regime_snapshot.regime.value}")
                lines.append(f"- Confidence: {regime_snapshot.confidence:.1%}")
                lines.append(f"- Volatility: {regime_snapshot.volatility:.2f}")
                lines.append(f"- Trend: {regime_snapshot.trend_strength:.3f}")
            else:
                lines.append("- Current regime: not yet detected (cold start, need 5+ snapshots)")
            lines.append(f"- Governance mode: {getattr(governor, 'mode', 'unknown')}")
            lines.append(f"- Min confidence for routing: {getattr(governor, 'min_confidence', '?')}")

            # Governance-disabled strategies
            gov_disabled = getattr(governor, '_governance_disabled', {})
            if gov_disabled:
                lines.append(f"- Governance-disabled strategies: {', '.join(gov_disabled.keys())}")
        except Exception:
            lines.append("- Regime detection error")
    else:
        lines.append("- Governor not active")

    return "\n".join(lines)


def _gather_risk_state(bot) -> str:
    """EmotionalFirewall and Kelly sizer state."""
    lines = ["## Risk Management"]

    risk = getattr(bot, 'risk', None)
    if not risk:
        lines.append("- Not initialized")
        return "\n".join(lines)

    stats = risk.get_daily_stats()
    lines.append(f"- Portfolio heat: {stats['portfolio_heat']:.1%}")
    lines.append(f"- Current streak: {stats['current_streak']}")

    if stats['active_cooldown']:
        lines.append(f"- COOLDOWN ACTIVE: {stats.get('cooldown_reason', 'unknown reason')}")
    else:
        lines.append("- No active cooldowns")

    # Circuit breakers
    breakers = getattr(bot, '_strategy_circuit_breakers', {})
    tripped = {name: b for name, b in breakers.items()
               if b.get('consecutive_losses', 0) >= 3}
    if tripped:
        for name, b in tripped.items():
            lines.append(
                f"- Circuit breaker [{name}]: {b['consecutive_losses']} consecutive losses, "
                f"total P&L {b.get('total_pnl_cents', 0)}c"
            )

    return "\n".join(lines)


async def _gather_recent_log(bot) -> Optional[str]:
    """Recent Captain's Log entries for conversational context."""
    captains_log = getattr(bot, 'captains_log', None)
    if not captains_log:
        return None

    try:
        entries = await captains_log.get_recent_entries_for_analysis_async(limit=5)
        if not entries:
            return None

        lines = ["## Recent Captain's Log"]
        for entry in entries:
            # Truncate long entries
            text = entry[:150] + "..." if len(entry) > 150 else entry
            lines.append(f"- {text}")
        return "\n".join(lines)
    except Exception:
        return None


def _gather_governance(bot) -> str:
    """Recent governance decisions."""
    lines = ["## Recent Governance"]

    governor = getattr(bot, 'market_governor', None)
    if not governor:
        lines.append("- Governor not active")
        return "\n".join(lines)

    try:
        decisions = governor.get_recent_decisions(limit=5)
        if not decisions:
            lines.append("- No recent decisions")
        else:
            for d in decisions:
                action = getattr(d, 'action', str(d))
                strategy = getattr(d, 'strategy', '?')
                reason = getattr(d, 'reason', '')
                lines.append(f"- {action} [{strategy}]: {reason[:100]}")
    except Exception:
        lines.append("- Error reading decisions")

    return "\n".join(lines)


def _gather_health(bot) -> str:
    """Bot health status."""
    lines = ["## Health"]

    health = getattr(bot, '_latest_health', {})
    if health:
        lines.append(f"- API: {health.get('api_status', 'unknown')}")
        lines.append(f"- Database: {health.get('db_status', 'unknown')}")
        lines.append(f"- Uptime: {health.get('uptime', 'unknown')}")
    else:
        lines.append("- No health data available")

    # Check for circuit breaker (global)
    cb = getattr(bot, 'circuit_breaker', None)
    if cb and hasattr(cb, 'is_open'):
        if cb.is_open:
            lines.append("- CIRCUIT BREAKER: OPEN (API calls blocked)")

    return "\n".join(lines)


def _gather_allocation(bot) -> str:
    """Current capital allocation plan from the master strategist layer."""
    lines = ["## Capital Allocation"]

    allocator = getattr(bot, 'capital_allocator', None)
    if not allocator:
        lines.append("- Capital Allocator not active")
        return "\n".join(lines)

    plan = allocator.current_plan
    if not plan:
        lines.append("- No allocation plan computed yet (cold start)")
        return "\n".join(lines)

    lines.append(f"- Capital phase: {plan.phase.value.upper()}")
    lines.append(f"- Thesis: {plan.thesis}")
    lines.append(f"- Deployed: {plan.deployed_pct:.0%} | Reserve: {plan.reserve_pct:.0%}")
    lines.append(f"- Max positions: {plan.max_simultaneous} | Scale: {plan.position_scale:.1f}x")
    lines.append("- Weights:")
    for name, weight in sorted(plan.weights.items(), key=lambda x: -x[1]):
        lines.append(f"  - {name}: {weight:.0%}")

    # Council of Masters verdict (Principle Router)
    router = getattr(allocator, 'principle_router', None)
    if router:
        verdict = getattr(router, 'last_verdict', None)
        if verdict:
            lines.append("")
            lines.append("### Council of Masters")
            lines.append(f"- Signal: {verdict.signal_label} ({verdict.convergence_score:.0%})")
            lines.append(f"- Caution level: {verdict.caution_level:.0%}")
            lines.append(f"- Sizing bias: {verdict.position_sizing_bias:.2f}x")
            lines.append(f"- Active voices: {', '.join(m.master for m in verdict.active_masters)}")
            # Top 3 directives
            for m in sorted(verdict.active_masters, key=lambda x: -x.weight)[:3]:
                lines.append(f"  - {m.master} ({m.weight:.0%}): {m.directive[:80]}")

    return "\n".join(lines)


def _gather_config(bot) -> str:
    """Active configuration summary."""
    lines = ["## Active Config"]

    config = getattr(bot, 'config', None)
    if config:
        lines.append(f"- Market series: {getattr(config, 'market_series', '?')}")
        lines.append(f"- Poll interval: {getattr(config, 'poll_interval_seconds', '?')}s")
        lines.append(f"- Kelly fraction: {getattr(config, 'kelly_fraction', '?')}")
        lines.append(f"- Max position: ${getattr(config, 'max_position_size', '?')}")
        lines.append(f"- Daily loss limit: ${getattr(config, 'daily_loss_limit', '?')}")

    return "\n".join(lines)
