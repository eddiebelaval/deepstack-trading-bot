// Types for TradingView indicator research & backtesting scoreboard

export interface TvIndicator {
  id: string;
  script_name: string;
  category: string;
  composite_score: number | null;
  avg_sharpe: number | null;
  avg_roi: number | null;
  avg_win_rate: number | null;
  avg_profit_factor: number | null;
  num_tickers_tested: number;
  best_ticker: string | null;
  worst_ticker: string | null;
  rank: number | null;
  created_at: string;
  updated_at: string;
}

export interface TvBacktest {
  id: string;
  indicator_id: string;
  script_name: string;
  ticker: string;
  roi_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  win_rate_pct: number | null;
  profit_factor: number | null;
  num_trades: number | null;
  expectancy_pct: number | null;
  error: string | null;
}

export interface BacktestResult {
  script_name: string;
  category: string;
  composite_score: number | null;
  tickers: {
    ticker: string;
    roi_pct: number | null;
    sharpe_ratio: number | null;
    win_rate_pct: number | null;
    max_drawdown_pct: number | null;
    profit_factor: number | null;
    num_trades: number | null;
    error: string | null;
  }[];
  scoreboard_avg: number | null;
  saved_to_scoreboard: boolean;
}

export interface BacktestHistoryEntry {
  script_name: string;
  composite_score: number | null;
  timestamp: string;
  url: string;
}
