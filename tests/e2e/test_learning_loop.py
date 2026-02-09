"""
E2E Test: Learning Loop (Bayesian Performance Tracking)

Tests that Bayesian priors are registered, blended stats shift
after wins/losses, and health evaluation works end-to-end.
"""

import pytest


@pytest.mark.asyncio
async def test_priors_registered_at_startup(trading_bot):
    """All active strategies have priors registered in the performance tracker."""
    tracker = trading_bot.performance_tracker

    # mean_reversion should have a prior
    prior = tracker.get_prior("mean_reversion")
    assert prior is not None
    assert prior.strategy_name == "mean_reversion"
    assert 0 < prior.win_rate < 1
    assert prior.avg_win_cents > 0
    assert prior.avg_loss_cents > 0
    assert prior.prior_strength > 0


@pytest.mark.asyncio
async def test_blended_stats_start_at_prior(trading_bot):
    """With no trades, blended stats equal the prior."""
    tracker = trading_bot.performance_tracker

    prior = tracker.get_prior("mean_reversion")
    blended = tracker.get_blended_stats("mean_reversion")

    # With zero trades, blended should match prior exactly
    assert abs(blended["win_rate"] - prior.win_rate) < 0.01
    assert abs(blended["avg_win_cents"] - prior.avg_win_cents) < 0.1
    assert abs(blended["avg_loss_cents"] - prior.avg_loss_cents) < 0.1


@pytest.mark.asyncio
async def test_blended_stats_shift_after_wins(trading_bot):
    """After recording winning trades, blended win rate increases."""
    tracker = trading_bot.performance_tracker
    journal = trading_bot.journal

    prior = tracker.get_prior("mean_reversion")
    initial_blended = tracker.get_blended_stats("mean_reversion")

    # Record several winning trades in the journal
    for i in range(5):
        trade_id = journal.log_trade(
            market_ticker=f"WIN-{i}",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=46,
            strategy="mean_reversion",
        )
        journal.close_trade(
            trade_id=trade_id,
            exit_price_cents=54,  # +8c profit per contract
        )

    # Blended stats should shift toward observed (100% win rate)
    new_blended = tracker.get_blended_stats("mean_reversion")
    assert new_blended["win_rate"] >= initial_blended["win_rate"]


@pytest.mark.asyncio
async def test_blended_stats_shift_after_losses(trading_bot):
    """After recording losing trades, blended win rate decreases."""
    tracker = trading_bot.performance_tracker
    journal = trading_bot.journal

    initial_blended = tracker.get_blended_stats("mean_reversion")

    # Record several losing trades
    for i in range(5):
        trade_id = journal.log_trade(
            market_ticker=f"LOSS-{i}",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=46,
            strategy="mean_reversion",
        )
        journal.close_trade(
            trade_id=trade_id,
            exit_price_cents=41,  # -5c loss per contract
        )

    new_blended = tracker.get_blended_stats("mean_reversion")
    assert new_blended["win_rate"] <= initial_blended["win_rate"]


@pytest.mark.asyncio
async def test_health_evaluation_healthy(trading_bot):
    """Strategy with positive EV is evaluated as healthy."""
    tracker = trading_bot.performance_tracker

    health = tracker.evaluate_health("mean_reversion")
    # With only priors (positive EV strategy), should be healthy
    assert health.health_status == "healthy"
    assert health.blended_ev_cents > 0
    assert health.confidence >= 0


@pytest.mark.asyncio
async def test_health_evaluation_degrades_with_losses(trading_bot):
    """Strategy health degrades after sustained losses."""
    tracker = trading_bot.performance_tracker
    journal = trading_bot.journal

    # Record many losing trades to overwhelm the prior
    for i in range(30):
        trade_id = journal.log_trade(
            market_ticker=f"BAD-{i}",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=46,
            strategy="mean_reversion",
        )
        journal.close_trade(
            trade_id=trade_id,
            exit_price_cents=36,  # -10c loss each
        )

    health = tracker.evaluate_health("mean_reversion")
    # After many losses, should be warning or critical
    assert health.health_status in ("warning", "critical")
    assert health.blended_ev_cents < 0


@pytest.mark.asyncio
async def test_confidence_increases_with_trades(trading_bot):
    """Confidence metric increases as more trades are recorded."""
    tracker = trading_bot.performance_tracker
    journal = trading_bot.journal

    # Initial confidence (no trades)
    health_initial = tracker.evaluate_health("mean_reversion")

    # Add some trades
    for i in range(10):
        trade_id = journal.log_trade(
            market_ticker=f"CONF-{i}",
            side="yes",
            action="buy",
            contracts=5,
            price_cents=48,
            strategy="mean_reversion",
        )
        journal.close_trade(
            trade_id=trade_id,
            exit_price_cents=52,
        )

    health_after = tracker.evaluate_health("mean_reversion")
    # More trades = higher confidence (n / (n + k))
    assert health_after.confidence >= health_initial.confidence


@pytest.mark.asyncio
async def test_tracker_attached_to_strategies(trading_bot):
    """Performance tracker is injected into strategy instances."""
    for name, state in trading_bot.strategy_manager._strategies.items():
        strategy = state.strategy
        assert strategy._performance_tracker is not None, (
            f"Strategy '{name}' should have a performance tracker attached"
        )


@pytest.mark.asyncio
async def test_get_historical_stats_uses_blended(trading_bot):
    """Strategy.get_historical_stats() routes through tracker when attached."""
    strategy = trading_bot.strategy_manager._strategies["mean_reversion"].strategy

    # get_historical_stats should return blended stats (not just priors)
    stats = strategy.get_historical_stats()
    assert "win_rate" in stats
    assert "avg_win_cents" in stats
    assert "avg_loss_cents" in stats

    # Should match what the tracker returns
    tracker_stats = trading_bot.performance_tracker.get_blended_stats("mean_reversion")
    assert abs(stats["win_rate"] - tracker_stats["win_rate"]) < 0.01
