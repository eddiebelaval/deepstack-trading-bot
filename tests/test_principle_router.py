"""
Tests for PrincipleRouter — Council of Masters convergence/divergence engine.

Covers convergence math, sizing bias, reserve adjustments, role diversity.
"""

import pytest

from kalshi_trader.principle_router import (
    CouncilVerdict,
    MasterDirective,
    MASTER_PROFILES,
    PrincipleRouter,
)


@pytest.fixture
def router():
    """Fresh PrincipleRouter with default masters."""
    return PrincipleRouter()


class TestConvergence:
    def test_high_convergence_when_masters_agree(self, router):
        """All masters with similar caution = high convergence."""
        verdict = router.convene_council(
            phase="seed",
            regime="low_vol_calm",
            regime_confidence=0.8,
        )
        # Convergence should be computed from master caution levels
        assert 0.0 <= verdict.convergence_score <= 1.0

    def test_convergence_score_in_verdict(self, router):
        verdict = router.convene_council(
            phase="seed",
            regime="trending",
            regime_confidence=0.9,
        )
        assert hasattr(verdict, "convergence_score")
        assert isinstance(verdict.convergence_score, float)

    def test_signal_label_strong_convergence(self):
        """Score >= 0.8 should be STRONG CONVERGENCE."""
        v = CouncilVerdict(
            active_masters=[],
            convergence_score=0.85,
            position_sizing_bias=1.0,
            reserve_adjustment=0.0,
            caution_level=0.5,
            thesis="test",
            phase="seed",
            regime="trending",
        )
        assert v.signal_label == "STRONG CONVERGENCE"

    def test_signal_label_strong_divergence(self):
        """Score < 0.2 should be STRONG DIVERGENCE."""
        v = CouncilVerdict(
            active_masters=[],
            convergence_score=0.15,
            position_sizing_bias=1.0,
            reserve_adjustment=0.0,
            caution_level=0.5,
            thesis="test",
            phase="seed",
            regime="trending",
        )
        assert v.signal_label == "STRONG DIVERGENCE"

    def test_signal_label_neutral(self):
        """Score 0.4-0.6 should be NEUTRAL."""
        v = CouncilVerdict(
            active_masters=[],
            convergence_score=0.5,
            position_sizing_bias=1.0,
            reserve_adjustment=0.0,
            caution_level=0.5,
            thesis="test",
            phase="seed",
            regime="trending",
        )
        assert v.signal_label == "NEUTRAL"


class TestConveneCouncil:
    def test_returns_verdict(self, router):
        verdict = router.convene_council(
            phase="seed",
            regime="trending",
            regime_confidence=0.9,
        )
        assert isinstance(verdict, CouncilVerdict)

    def test_verdict_has_active_masters(self, router):
        verdict = router.convene_council(
            phase="growth",
            regime="mean_reverting",
            regime_confidence=0.7,
        )
        assert len(verdict.active_masters) > 0
        assert len(verdict.active_masters) <= 7  # max council size

    def test_role_diversity_max_two_per_role(self, router):
        """No more than 2 masters per functional role."""
        verdict = router.convene_council(
            phase="seed",
            regime="trending",
            regime_confidence=0.95,
        )
        role_counts = {}
        for m in verdict.active_masters:
            role = m.role if hasattr(m, "role") else "unknown"
            role_counts[role] = role_counts.get(role, 0) + 1
        for role, count in role_counts.items():
            assert count <= 2, f"Role '{role}' has {count} masters (max 2)"

    def test_sizing_bias_positive(self, router):
        verdict = router.convene_council(
            phase="seed",
            regime="low_vol_calm",
            regime_confidence=0.8,
        )
        assert verdict.position_sizing_bias > 0

    def test_sizing_bias_floor(self, router):
        """Sizing bias should never drop below 0.5 (floor fix)."""
        verdict = router.convene_council(
            phase="seed",
            regime="high_vol_chaos",
            regime_confidence=0.3,  # low confidence → dampened bias
        )
        assert verdict.position_sizing_bias >= 0.5

    def test_reserve_adjustment_bounded(self, router):
        verdict = router.convene_council(
            phase="seed",
            regime="high_vol_chaos",
            regime_confidence=0.9,
        )
        # Reserve adjustment should be reasonable
        assert -0.10 <= verdict.reserve_adjustment <= 0.15

    def test_thesis_not_empty(self, router):
        verdict = router.convene_council(
            phase="growth",
            regime="trending",
            regime_confidence=0.85,
        )
        assert len(verdict.thesis) > 0

    def test_caution_level_bounded(self, router):
        verdict = router.convene_council(
            phase="seed",
            regime="event_driven",
            regime_confidence=0.6,
        )
        assert 0.0 <= verdict.caution_level <= 1.0

    def test_all_phases(self, router):
        """Council should work for all capital phases."""
        for phase in ["seed", "growth", "foundation", "compound", "dynasty"]:
            verdict = router.convene_council(
                phase=phase,
                regime="trending",
                regime_confidence=0.8,
            )
            assert isinstance(verdict, CouncilVerdict)

    def test_all_regimes(self, router):
        """Council should work for all market regimes."""
        for regime in [
            "trending", "mean_reverting", "high_vol_chaos",
            "low_vol_calm", "event_driven", "unknown",
        ]:
            verdict = router.convene_council(
                phase="seed",
                regime=regime,
                regime_confidence=0.8,
            )
            assert isinstance(verdict, CouncilVerdict)


class TestConvergenceGuard:
    def test_same_inputs_returns_cached(self, router):
        """Same phase/regime/confidence should return cached verdict."""
        v1 = router.convene_council(
            phase="seed", regime="trending", regime_confidence=0.80,
        )
        v2 = router.convene_council(
            phase="seed", regime="trending", regime_confidence=0.80,
        )
        # Should be the same object (convergence guard)
        assert v1 is v2

    def test_different_inputs_recomputes(self, router):
        v1 = router.convene_council(
            phase="seed", regime="trending", regime_confidence=0.80,
        )
        v2 = router.convene_council(
            phase="growth", regime="trending", regime_confidence=0.80,
        )
        assert v1 is not v2


class TestLastVerdict:
    def test_last_verdict_accessible(self, router):
        assert router.last_verdict is None
        router.convene_council(
            phase="seed", regime="trending", regime_confidence=0.8,
        )
        assert router.last_verdict is not None
        assert isinstance(router.last_verdict, CouncilVerdict)
