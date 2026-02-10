# Strategy Toggles + Mode Selection

**Priority:** P0 — Must have before next live session
**Owner:** Claude + Eddie
**Status:** Pending

---

## What?

Simple CLI command to control strategies:

```bash
python trading_bot.py --strategy mean_reversion momentum --mode paper
```

Config file (`strategies.yaml` or section in `config.yaml`) with enable/disable flags per strategy:

```yaml
strategies:
  mean_reversion:
    enabled: true
    mode: paper  # paper | live
  momentum:
    enabled: true
    mode: live
  combinatorial_arbitrage:
    enabled: false
    mode: paper
  cross_platform_arbitrage:
    enabled: false
    mode: paper
  market_making:
    enabled: false  # killed after post-mortem
    mode: paper
```

Web dashboard toggle panel if time allows — but CLI + config file is the minimum viable.

## Why?

Right now all strategies run or none run. No granular control. Market making died slowly because we couldn't turn it off independently. We watched it bleed $10.83 with no kill switch.

## Done When?

- [ ] I can start the bot with only Momentum enabled
- [ ] Config persists across restarts
- [ ] Dashboard shows which strategies are active
- [ ] Paper mode runs strategy logic but skips order execution
