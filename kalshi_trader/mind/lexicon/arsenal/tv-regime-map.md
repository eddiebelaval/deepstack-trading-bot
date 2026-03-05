# TradingView Arsenal — Regime Map

Maps indicator categories to market regimes. Auto-populated from DeepStack TradingView pipeline.
Last refresh: not yet populated

## Category-Regime Mapping

| Category | Best Regime | Worst Regime | Notes |
|----------|-------------|--------------|-------|
| Momentum | TRENDING_UP, TRENDING_DOWN | MEAN_REVERTING | Trend-following indicators |
| Mean Reversion | MEAN_REVERTING | TRENDING_UP | Range-bound oscillators |
| Volatility | HIGH_VOL_CHOPPY | LOW_VOL_CALM | Vol expansion strategies |
| Volume | All regimes | — | Confirmation indicators |
| Trend | TRENDING_UP, TRENDING_DOWN | HIGH_VOL_CHOPPY | Directional strength |
| Oscillator | MEAN_REVERTING, LOW_VOL_CALM | TRENDING | Overbought/oversold signals |

## Active Indicators by Regime

Awaiting population. Run `python scripts/populate_lexicon_arsenal.py` or wait for heartbeat auto-refresh.
