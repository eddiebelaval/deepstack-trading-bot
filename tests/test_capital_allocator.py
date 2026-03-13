"""
Tests for CapitalAllocator — master strategist layer.

Covers phase detection, plan computation, and PrincipleRouter integration.
"""

import pytest

from kalshi_trader.capital_allocator import AllocationPlan, CapitalAllocator, CapitalPhase
from kalshi_trader.principle_router import PrincipleRouter


@pytest.fixture
def allocator():
    """Allocator without router."""
    return CapitalAllocator()


@pytest.fixture
def allocator_with_router():
    """Allocator with PrincipleRouter."""
    router = PrincipleRouter()
    return CapitalAllocator(principle_router=router)


class TestPhaseDetection:
    def test_seed_phase(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=100.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert plan.phase == CapitalPhase.SEED

    def test_growth_phase(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=1000.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert plan.phase == CapitalPhase.GROWTH

    def test_foundation_phase(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=10000.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert plan.phase == CapitalPhase.FOUNDATION

    def test_compound_phase(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=100000.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert plan.phase == CapitalPhase.COMPOUND

    def test_dynasty_phase(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=1000000.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert plan.phase == CapitalPhase.DYNASTY


class TestComputePlan:
    def test_returns_allocation_plan(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=150.0,
            regime="low_vol_calm",
            regime_confidence=0.7,
        )
        assert isinstance(plan, AllocationPlan)

    def test_plan_has_weights(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=150.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert "calibration_edge" in plan.weights
        assert plan.weights["calibration_edge"] > 0

    def test_weights_sum_to_one_or_less(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=500.0,
            regime="trending",
            regime_confidence=0.8,
        )
        total = sum(plan.weights.values())
        assert total <= 1.01  # small float tolerance

    def test_deployed_plus_reserve_equals_one(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=200.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert abs(plan.deployed_pct + plan.reserve_pct - 1.0) < 0.01

    def test_thesis_not_empty(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=150.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert len(plan.thesis) > 0

    def test_position_scale_positive(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=150.0,
            regime="low_vol_calm",
            regime_confidence=0.9,
        )
        assert plan.position_scale > 0


class TestRouterIntegration:
    def test_router_modulates_plan(self, allocator_with_router):
        plan = allocator_with_router.compute_plan(
            balance_dollars=150.0,
            regime="trending",
            regime_confidence=0.8,
        )
        # With router, thesis should mention Council
        assert "Council" in plan.thesis

    def test_principle_router_property(self, allocator_with_router):
        assert allocator_with_router.principle_router is not None

    def test_no_router_still_works(self, allocator):
        plan = allocator.compute_plan(
            balance_dollars=150.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert isinstance(plan, AllocationPlan)
        assert "Council" not in plan.thesis


class TestCurrentPlan:
    def test_none_before_compute(self, allocator):
        assert allocator.current_plan is None

    def test_stored_after_compute(self, allocator):
        allocator.compute_plan(
            balance_dollars=150.0,
            regime="trending",
            regime_confidence=0.8,
        )
        assert allocator.current_plan is not None
