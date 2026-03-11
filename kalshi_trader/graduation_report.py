"""
Graduation Report Generator — HTML report for sector graduation events.

When a sector (KALSHI, STOCKS, FUTURES, OPTIONS) passes all gate checks,
this generates a full HTML report with:
  - Gate check results (pass/fail per criterion)
  - Paper trading metrics (trades, win rate, drawdown, streaks)
  - Backtest confidence (arena scores, if available)
  - Daily P&L chart (SVG sparkline)
  - Blended readiness score

Saved to ~/Development/artifacts/deepstack/ and Telegram-notified.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .graduation_gate import AssetClassReport, GraduationReport

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = os.path.expanduser("~/Development/artifacts/deepstack")


def _ensure_artifacts_dir() -> Path:
    """Create artifacts directory if it doesn't exist."""
    path = Path(ARTIFACTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fetch_backtest_confidence(sector: str) -> Optional[Dict[str, Any]]:
    """Fetch backtest confidence data from Supabase for a sector."""
    try:
        import httpx

        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            return None

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
        }
        resp = httpx.get(
            f"{url}/rest/v1/deepstack_backtest_results"
            f"?gate=eq.{sector}"
            f"&select=strategy,total_trades,win_rate,max_drawdown_pct,sharpe_ratio,profit_factor,avg_pnl_cents,composite_score,created_at"
            f"&order=created_at.desc",
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None

        rows = resp.json()
        if not rows:
            return None

        # Deduplicate: latest per strategy
        latest: Dict[str, Dict] = {}
        for r in rows:
            s = r["strategy"]
            if s not in latest:
                latest[s] = r

        results = list(latest.values())
        avg_score = sum(r["composite_score"] for r in results) / len(results)
        avg_wr = sum(r["win_rate"] for r in results) / len(results)
        avg_sharpe = sum(r["sharpe_ratio"] for r in results) / len(results)
        total_bt_trades = sum(r["total_trades"] for r in results)

        return {
            "score": avg_score,
            "strategies_tested": len(results),
            "total_bt_trades": total_bt_trades,
            "avg_win_rate": avg_wr,
            "avg_sharpe": avg_sharpe,
            "strategies": results,
            "last_run": results[0]["created_at"],
        }
    except Exception as e:
        logger.warning(f"Failed to fetch backtest confidence for {sector}: {e}")
        return None


def _fetch_daily_pnl(
    db_path: str,
    sector: str,
    strategies: List[str],
) -> List[Dict[str, Any]]:
    """Fetch daily P&L from trade journal SQLite."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row

        if sector == "KALSHI":
            placeholders = ",".join("?" * len(strategies))
            rows = conn.execute(
                f"SELECT date(updated_at) AS day, SUM(pnl_cents) AS pnl, COUNT(*) AS trades "
                f"FROM trades WHERE is_paper = 1 AND status = 'closed' AND pnl_cents IS NOT NULL "
                f"AND strategy IN ({placeholders}) "
                f"GROUP BY date(updated_at) ORDER BY day",
                strategies,
            ).fetchall()
        else:
            placeholders = ",".join("?" * len(strategies))
            rows = conn.execute(
                f"SELECT session_date AS day, SUM(pnl_cents) AS pnl, COUNT(*) AS trades "
                f"FROM stock_trades WHERE status = 'filled' AND pnl_cents IS NOT NULL "
                f"AND strategy IN ({placeholders}) "
                f"GROUP BY session_date ORDER BY day",
                strategies,
            ).fetchall()

        conn.close()
        return [{"day": r["day"], "pnl": r["pnl"], "trades": r["trades"]} for r in rows if r["day"]]
    except Exception as e:
        logger.warning(f"Failed to fetch daily P&L for {sector}: {e}")
        return []


def _svg_sparkline(daily_pnl: List[Dict[str, Any]], width: int = 600, height: int = 120) -> str:
    """Generate an SVG equity curve sparkline from daily P&L data."""
    if len(daily_pnl) < 2:
        return '<text x="50%" y="50%" text-anchor="middle" fill="#666" font-size="12">Insufficient data for chart</text>'

    # Cumulative P&L
    cumulative = []
    total = 0
    for d in daily_pnl:
        total += d["pnl"]
        cumulative.append(total)

    min_val = min(cumulative)
    max_val = max(cumulative)
    val_range = max_val - min_val if max_val != min_val else 1
    padding = 10

    points = []
    for i, val in enumerate(cumulative):
        x = padding + (i / (len(cumulative) - 1)) * (width - 2 * padding)
        y = padding + (1 - (val - min_val) / val_range) * (height - 2 * padding)
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)

    # Fill area under curve
    fill_points = f"{padding},{height - padding} " + polyline + f" {width - padding},{height - padding}"

    # Zero line
    zero_y = padding + (1 - (0 - min_val) / val_range) * (height - 2 * padding)

    return f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="fillGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#00ff41" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="#00ff41" stop-opacity="0.05"/>
    </linearGradient>
  </defs>
  <line x1="{padding}" y1="{zero_y:.1f}" x2="{width - padding}" y2="{zero_y:.1f}"
        stroke="#333" stroke-width="1" stroke-dasharray="4,4"/>
  <polygon points="{fill_points}" fill="url(#fillGrad)"/>
  <polyline points="{polyline}" fill="none" stroke="#00ff41" stroke-width="2"/>
  <circle cx="{points[-1].split(',')[0]}" cy="{points[-1].split(',')[1]}" r="3" fill="#00ff41"/>
  <text x="{width - padding}" y="{height - 2}" text-anchor="end" fill="#666" font-size="10">
    ${cumulative[-1] / 100:.2f}
  </text>
</svg>"""


def _gate_check_row(name: str, current: Any, target: Any, passed: bool, fmt: str = "", invert: bool = False) -> str:
    """Generate an HTML row for a gate check."""
    status_class = "passed" if passed else "failed"
    status_icon = "PASS" if passed else "FAIL"

    if fmt == "percent":
        current_str = f"{current:.1%}"
        target_str = f"{target:.0%}"
    elif fmt == "pct":
        current_str = f"{current:.1f}%"
        target_str = f"{target:.0f}%"
        comparison = "<=" if invert else ">="
    elif fmt == "cents":
        current_str = f"{current:.0f}c"
        target_str = f"{target}c"
    else:
        current_str = str(int(current))
        target_str = str(int(target))

    comparison = "<=" if invert else ">="

    return f"""<tr class="{status_class}">
  <td class="check-name">{name}</td>
  <td class="check-current">{current_str}</td>
  <td class="check-comparison">{comparison}</td>
  <td class="check-target">{target_str}</td>
  <td class="check-status"><span class="badge {status_class}">{status_icon}</span></td>
</tr>"""


def generate_graduation_report(
    sector: str,
    report: Union[GraduationReport, AssetClassReport],
    db_path: str,
    strategies: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Generate a full HTML graduation report for a sector.

    Args:
        sector: Gate label (KALSHI, STOCKS, FUTURES, OPTIONS)
        report: The graduation report with metrics and pass/fail flags
        db_path: Path to trade_journal.db for daily P&L data
        strategies: List of strategy names in this sector

    Returns:
        File path of the generated HTML report, or None on failure.
    """
    try:
        artifacts_dir = _ensure_artifacts_dir()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"graduation-{sector.lower()}-{timestamp}.html"
        filepath = artifacts_dir / filename

        # Determine strategies list
        if strategies is None:
            if isinstance(report, AssetClassReport):
                strategies = report.strategies
            else:
                from backtest.persist import GATE_STRATEGIES
                strategies = list(GATE_STRATEGIES.get(sector, []))

        # Fetch supplementary data
        backtest = _fetch_backtest_confidence(sector)
        daily_pnl = _fetch_daily_pnl(db_path, sector, strategies)

        # Build gate checks
        gate_checks_html = ""
        if isinstance(report, GraduationReport):
            gate_checks_html = "\n".join([
                _gate_check_row("Trades", report.paper_trades_closed, report.min_trades, report.trades_passed),
                _gate_check_row("Win Rate", report.win_rate, report.min_win_rate, report.win_rate_passed, fmt="percent"),
                _gate_check_row("Max Drawdown", report.max_drawdown_pct, report.max_drawdown, report.drawdown_passed, fmt="pct", invert=True),
                _gate_check_row("Profitable Regimes", len(report.profitable_regimes), report.min_regimes, report.regimes_passed),
            ])
        elif isinstance(report, AssetClassReport):
            gate_checks_html = "\n".join([
                _gate_check_row("Trades", report.paper_trades_closed, report.min_trades, report.trades_passed),
                _gate_check_row("Win Rate", report.win_rate, report.min_win_rate, report.win_rate_passed, fmt="percent"),
                _gate_check_row("Max Drawdown", report.max_drawdown_pct, report.max_drawdown, report.drawdown_passed, fmt="pct", invert=True),
                _gate_check_row("Profitable Days", report.profitable_days, report.min_profitable_days, report.profitable_days_passed),
                _gate_check_row("Avg P&L", report.avg_pnl_per_trade_cents, report.min_avg_pnl_per_trade_cents, report.avg_pnl_passed, fmt="cents"),
            ])

        # Sparkline
        sparkline_svg = _svg_sparkline(daily_pnl)

        # Backtest confidence section
        backtest_section = ""
        if backtest:
            bt_rows = ""
            for s in backtest["strategies"]:
                bt_rows += f"""<tr>
  <td>{s['strategy']}</td>
  <td>{s['win_rate']:.1%}</td>
  <td>{s['sharpe_ratio']:.2f}</td>
  <td>{s['max_drawdown_pct']:.1f}%</td>
  <td>{s['composite_score']:.1f}</td>
</tr>"""

            backtest_section = f"""
<section class="panel">
  <h2>Backtest Confidence (Arena)</h2>
  <div class="metrics-row">
    <div class="metric">
      <span class="metric-label">Score</span>
      <span class="metric-value">{backtest['score']:.1f}/100</span>
    </div>
    <div class="metric">
      <span class="metric-label">Strategies Tested</span>
      <span class="metric-value">{backtest['strategies_tested']}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Total BT Trades</span>
      <span class="metric-value">{backtest['total_bt_trades']:,}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Avg Win Rate</span>
      <span class="metric-value">{backtest['avg_win_rate']:.1%}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Avg Sharpe</span>
      <span class="metric-value">{backtest['avg_sharpe']:.2f}</span>
    </div>
  </div>
  <table class="bt-table">
    <thead><tr><th>Strategy</th><th>Win Rate</th><th>Sharpe</th><th>Max DD</th><th>Score</th></tr></thead>
    <tbody>{bt_rows}</tbody>
  </table>
</section>"""

        # Regime section (Kalshi only)
        regime_section = ""
        if isinstance(report, GraduationReport) and report.total_regimes_traded:
            regime_items = ""
            for regime in report.total_regimes_traded:
                is_profitable = regime in report.profitable_regimes
                cls = "profitable" if is_profitable else "unprofitable"
                tag = "PROFITABLE" if is_profitable else "LOSS"
                regime_items += f'<div class="regime-item {cls}"><span class="regime-name">{regime}</span><span class="badge {cls}">{tag}</span></div>'

            regime_section = f"""
<section class="panel">
  <h2>Regime Performance</h2>
  <div class="regime-grid">{regime_items}</div>
</section>"""

        # Daily P&L table
        daily_table = ""
        if daily_pnl:
            daily_rows = ""
            for d in daily_pnl[-14:]:  # Last 14 days
                pnl_class = "positive" if d["pnl"] > 0 else "negative" if d["pnl"] < 0 else ""
                daily_rows += f'<tr class="{pnl_class}"><td>{d["day"]}</td><td>{d["trades"]}</td><td>${d["pnl"] / 100:.2f}</td></tr>'

            daily_table = f"""
<section class="panel">
  <h2>Daily P&L (Last 14 Days)</h2>
  <table class="daily-table">
    <thead><tr><th>Date</th><th>Trades</th><th>P&L</th></tr></thead>
    <tbody>{daily_rows}</tbody>
  </table>
</section>"""

        # Summary metrics
        if isinstance(report, GraduationReport):
            total_trades = report.paper_trades_closed
            win_rate = report.win_rate
            drawdown = report.max_drawdown_pct
        else:
            total_trades = report.paper_trades_closed
            win_rate = report.win_rate
            drawdown = report.max_drawdown_pct

        total_pnl = sum(d["pnl"] for d in daily_pnl) if daily_pnl else 0

        # Blended readiness
        paper_readiness = 1.0  # All checks passed if we're generating this report
        bt_score = backtest["score"] / 100 if backtest else 0
        blended = paper_readiness * 0.35 + bt_score * 0.65 if backtest else paper_readiness

        now = datetime.now()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DeepStack Graduation Report — {sector}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');

  :root {{
    --bg: #0a0a0a;
    --surface: #111;
    --border: #222;
    --text: #c8c8c8;
    --text-dim: #666;
    --green: #00ff41;
    --green-dim: #00802080;
    --red: #ff4444;
    --red-dim: #80222280;
    --amber: #ffaa00;
    --cyan: #00d4ff;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'JetBrains Mono', monospace;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 900px;
    margin: 0 auto;
  }}

  .header {{
    text-align: center;
    padding: 3rem 0 2rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 2rem;
  }}

  .header h1 {{
    font-size: 1.4rem;
    font-weight: 600;
    color: var(--green);
    letter-spacing: 0.15em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }}

  .header .sector {{
    font-size: 2.5rem;
    font-weight: 700;
    color: #fff;
    margin-bottom: 0.5rem;
  }}

  .header .timestamp {{
    font-size: 0.75rem;
    color: var(--text-dim);
  }}

  .status-badge {{
    display: inline-block;
    padding: 0.5rem 1.5rem;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.1em;
    margin-top: 1rem;
  }}

  .status-badge.graduated {{
    background: var(--green-dim);
    color: var(--green);
    border: 1px solid var(--green);
  }}

  .readiness-bar {{
    margin: 2rem auto;
    max-width: 400px;
  }}

  .readiness-bar .bar-track {{
    height: 8px;
    background: var(--surface);
    border-radius: 4px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}

  .readiness-bar .bar-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }}

  .readiness-bar .bar-fill.paper {{
    background: var(--cyan);
  }}

  .readiness-bar .bar-fill.blended {{
    background: linear-gradient(90deg, var(--cyan) 35%, var(--green) 65%);
  }}

  .readiness-bar .bar-label {{
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: var(--text-dim);
    margin-top: 0.3rem;
  }}

  .panel {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
  }}

  .panel h2 {{
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--text-dim);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
  }}

  .metrics-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1rem;
  }}

  .metric {{
    flex: 1;
    min-width: 100px;
    text-align: center;
    padding: 0.75rem;
    background: var(--bg);
    border-radius: 4px;
    border: 1px solid var(--border);
  }}

  .metric-label {{
    display: block;
    font-size: 0.65rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.3rem;
  }}

  .metric-value {{
    display: block;
    font-size: 1.1rem;
    font-weight: 600;
    color: #fff;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
  }}

  th, td {{
    padding: 0.5rem 0.75rem;
    text-align: left;
    font-size: 0.8rem;
    border-bottom: 1px solid var(--border);
  }}

  th {{
    color: var(--text-dim);
    font-weight: 400;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
  }}

  tr.passed .check-status .badge {{
    background: var(--green-dim);
    color: var(--green);
  }}

  tr.failed .check-status .badge {{
    background: var(--red-dim);
    color: var(--red);
  }}

  .badge {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.05em;
  }}

  .badge.passed, .badge.profitable {{
    background: var(--green-dim);
    color: var(--green);
  }}

  .badge.failed, .badge.unprofitable {{
    background: var(--red-dim);
    color: var(--red);
  }}

  .check-name {{ font-weight: 500; color: #fff; }}
  .check-current {{ font-weight: 600; }}
  .check-comparison {{ color: var(--text-dim); text-align: center; }}
  .check-target {{ color: var(--text-dim); }}
  .check-status {{ text-align: right; }}

  .sparkline-container {{
    margin: 1rem 0;
  }}

  .regime-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }}

  .regime-item {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.75rem;
    background: var(--bg);
    border-radius: 4px;
    border: 1px solid var(--border);
    font-size: 0.8rem;
  }}

  .regime-name {{
    color: #fff;
    font-weight: 500;
  }}

  tr.positive td:last-child {{ color: var(--green); }}
  tr.negative td:last-child {{ color: var(--red); }}

  .bt-table td, .daily-table td {{
    font-size: 0.8rem;
  }}

  .footer {{
    text-align: center;
    padding: 2rem 0;
    color: var(--text-dim);
    font-size: 0.7rem;
    border-top: 1px solid var(--border);
    margin-top: 2rem;
  }}

  @media (max-width: 600px) {{
    body {{ padding: 1rem; }}
    .header .sector {{ font-size: 1.8rem; }}
    .metrics-row {{ gap: 0.5rem; }}
    .metric {{ min-width: 80px; padding: 0.5rem; }}
    .metric-value {{ font-size: 0.9rem; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>DeepStack Graduation Report</h1>
  <div class="sector">{sector}</div>
  <div class="timestamp">Generated {now.strftime('%B %d, %Y at %I:%M %p ET')}</div>
  <div class="status-badge graduated">ALL GATES PASSED</div>
  <div class="readiness-bar">
    <div class="bar-track">
      <div class="bar-fill {'blended' if backtest else 'paper'}" style="width: {blended * 100:.0f}%"></div>
    </div>
    <div class="bar-label">
      <span>{'Blended' if backtest else 'Paper'} Readiness</span>
      <span>{blended * 100:.0f}%</span>
    </div>
  </div>
</div>

<section class="panel">
  <h2>Summary</h2>
  <div class="metrics-row">
    <div class="metric">
      <span class="metric-label">Total Trades</span>
      <span class="metric-value">{total_trades}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Win Rate</span>
      <span class="metric-value">{win_rate:.1%}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Max Drawdown</span>
      <span class="metric-value">{drawdown:.1f}%</span>
    </div>
    <div class="metric">
      <span class="metric-label">Total P&L</span>
      <span class="metric-value" style="color: {'var(--green)' if total_pnl >= 0 else 'var(--red)'}">${total_pnl / 100:.2f}</span>
    </div>
    <div class="metric">
      <span class="metric-label">Strategies</span>
      <span class="metric-value">{len(strategies)}</span>
    </div>
  </div>
</section>

<section class="panel">
  <h2>Gate Checks</h2>
  <table>
    <thead>
      <tr><th>Check</th><th>Current</th><th></th><th>Target</th><th style="text-align:right">Status</th></tr>
    </thead>
    <tbody>
      {gate_checks_html}
    </tbody>
  </table>
</section>

<section class="panel">
  <h2>Equity Curve</h2>
  <div class="sparkline-container">
    {sparkline_svg}
  </div>
</section>

{backtest_section}
{regime_section}
{daily_table}

<div class="footer">
  DeepStack Autonomous Engine (Dae) | id8Labs LLC<br>
  Paper trading evaluation complete. Ready for go-live review.
</div>

</body>
</html>"""

        filepath.write_text(html)
        logger.info(f"Graduation report saved: {filepath}")
        return str(filepath)

    except Exception as e:
        logger.error(f"Failed to generate graduation report for {sector}: {e}")
        return None
