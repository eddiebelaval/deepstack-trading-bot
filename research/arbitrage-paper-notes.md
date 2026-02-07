# Arbitrage Research Notes

## Paper: "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"

**Source:** arXiv:2508.03474  
**Date:** Aug 5, 2025  
**Authors:** Oriol Saguillo, Vahid Ghafouri, Lucianna Kiffer, Guillermo Suarez-Tangil  
**Link:** https://arxiv.org/abs/2508.03474

---

## Summary

Empirical analysis of arbitrage opportunities on Polymarket prediction markets.

**Key Finding:** **$40 million in realized profit** extracted through arbitrage.

---

## Two Types of Arbitrage

### 1. Market Rebalancing Arbitrage
- **Scope:** Within a single market or condition
- **Mechanism:** Exploiting temporary price inefficiencies
- **Example:** Our mean-reversion strategy targets this

### 2. Combinatorial Arbitrage
- **Scope:** Across multiple related markets
- **Mechanism:** Related outcomes should collectively price to $1 (100% probability)
- **Opportunity:** When they don't, you can guarantee profit

**Example:**
```
Market Set: "2024 Presidential Winner"
- Outcome A: Trump wins → 52¢
- Outcome B: Biden wins → 49¢
- Total: $1.01

Action: Sell both outcomes for $1.01, buy back at resolution for $1.00
Profit: 1¢ per contract (guaranteed, risk-free)
```

---

## Technical Challenge: Scalability

**Problem:** Naive comparison across all markets = O(2^(n+m)) complexity

**Solution (from paper):**

Heuristic-driven reduction:
1. **Timeliness:** Only compare active, liquid markets
2. **Topical Similarity:** Only compare related topics (e.g., election markets)
3. **Combinatorial Relationships:** Parent/child markets, mutually exclusive outcomes

---

## Implementation Strategy

### Graph-Based Market Relationships

Build a relationship graph:
- **Nodes:** Individual markets/conditions
- **Edges:** Relationships (mutually_exclusive, parent_child, related)

### Scanning Algorithm

1. Filter markets by liquidity + activity
2. Group by topic/category (election, sports, etc.)
3. For each group, identify relationship sets
4. Calculate sum of prices for each set
5. Flag opportunities where sum ≠ $1 (with tolerance for fees)
6. Execute simultaneous orders across set

### Example Sets to Scan

**Elections:**
- All candidates in same race (mutually exclusive)
- Parent market: "Trump wins presidency"
- Child market: "Trump wins AND Republicans take Senate"

**Sports:**
- Team A wins, Team B wins, Draw (mutually exclusive)
- Player A MVP AND Team wins championship (combinatorial)

---

## Profit Potential

- $40M historical extraction proves strategy viability
- Modern implementation with:
  - Fast execution (sub-second)
  - Automated scanning
  - Low latency API access
- Could capture opportunities before manual arbitrageurs

---

## Risk Factors

1. **Execution Risk:** Prices move between placing orders
2. **Liquidity Risk:** Not enough depth to fill full arbitrage set
3. **Fee Erosion:** Transaction fees can eat thin margins
4. **Resolution Risk:** Market resolution disputes

---

## Next Steps

1. Implement `strategies/combinatorial_arbitrage.py`
2. Build market relationship graph (manual + ML-based)
3. Test on historical Kalshi data
4. Extend to Polymarket when integration ready
5. Monitor execution speed vs opportunity window

---

## Questions for Further Research

- How fast do arbitrage opportunities close? (seconds? minutes?)
- What's the optimal capital allocation across arbitrage sets?
- Can ML predict which topic clusters will have more arbitrage?
- How do fees impact minimum viable profit threshold?
