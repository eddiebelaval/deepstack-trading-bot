'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import Sidebar from '@/components/Sidebar';
import Header from '@/components/Header';
import StrategyCard from '@/components/StrategyCard';
import LiveFeed from '@/components/LiveFeed';
import RiskMetricsCard from '@/components/RiskMetrics';
import TradeJournal from '@/components/TradeJournal';
import PnLChart from '@/components/PnLChart';
import PerformanceHero from '@/components/PerformanceHero';
import TradeActivity from '@/components/TradeActivity';
import WinRateGauge from '@/components/WinRateGauge';
import ConnectionStatus from '@/components/ConnectionStatus';
import ToastContainer, { useToasts } from '@/components/Toast';
import ShortcutsHelp from '@/components/ShortcutsHelp';
import OpportunitiesModal from '@/components/OpportunitiesModal';
import TradeDetailModal from '@/components/TradeDetailModal';
import StrategyDetailModal from '@/components/StrategyDetailModal';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useSoundEffects } from '@/hooks/useSoundEffects';
import { useSessionTimeout } from '@/hooks/useSessionTimeout';
import MarketStatus from '@/components/MarketStatus';
import PositionsTable from '@/components/PositionsTable';
import OrdersTable from '@/components/OrdersTable';
import FillsHistory from '@/components/FillsHistory';
import SettlementsHistory from '@/components/SettlementsHistory';
import { DashboardState, Trade, Strategy, BotConfig, Position, Order, Fill, Settlement } from '@/lib/types';

interface BalanceSnapshot {
  timestamp: string;
  balance_cents: number;
  available_balance_cents: number;
}

export default function Dashboard() {
  const [dashboardState, setDashboardState] = useState<DashboardState | null>(null);
  const [botConfig, setBotConfig] = useState<BotConfig | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [balanceHistory, setBalanceHistory] = useState<BalanceSnapshot[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [portfolioTab, setPortfolioTab] = useState<'positions' | 'orders' | 'fills' | 'settlements' | 'journal'>('positions');
  const [loading, setLoading] = useState(true);
  const [showHelp, setShowHelp] = useState(false);
  const [lastSeenTradeId, setLastSeenTradeId] = useState<string | null>(null);
  const [lastSuccessfulFetch, setLastSuccessfulFetch] = useState<number>(Date.now());
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Mobile sidebar state
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Pending local overrides — prevents polling from reverting optimistic updates.
  // Map of strategy name -> { enabled, timestamp }. Entries expire after 10 seconds
  // (by then the Supabase write has persisted and server state is correct).
  const [pendingToggles, setPendingToggles] = useState<Record<string, { enabled: boolean; at: number }>>({});

  // Modal states
  const [showOpportunities, setShowOpportunities] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);

  // Toast notifications
  const { toasts, addToast, dismissToast } = useToasts();

  // Sound effects
  const sound = useSoundEffects();

  // Session security: auto-logout after 30 minutes of inactivity
  const { logout } = useSessionTimeout(30);

  // Fetch dashboard state
  const fetchStatus = async () => {
    try {
      const response = await fetch('/api/status');
      if (response.ok) {
        const data = await response.json();

        // Merge server state with pending local overrides so polling
        // doesn't revert optimistic updates (toggles, config changes).
        const now = Date.now();
        const OVERRIDE_TTL_MS = 10_000;
        const stillPending: Record<string, { enabled: boolean; at: number }> = {};

        if (data.strategies && Object.keys(pendingToggles).length > 0) {
          data.strategies = data.strategies.map((s: Strategy) => {
            const override = pendingToggles[s.name];
            if (override && (now - override.at) < OVERRIDE_TTL_MS) {
              stillPending[s.name] = override;
              return { ...s, enabled: override.enabled };
            }
            return s;
          });
          setPendingToggles(stillPending);
        }

        setDashboardState(data);
        setLastSuccessfulFetch(Date.now());
        setFetchError(null);
      } else if (response.status === 503) {
        setFetchError('Database unavailable');
      } else {
        setFetchError(`API error (${response.status})`);
      }
    } catch (error) {
      console.error('Failed to fetch status:', error);
      setFetchError('Connection lost');
    }
  };

  // Fetch trades
  const fetchTrades = async () => {
    try {
      const response = await fetch('/api/trades');
      if (response.ok) {
        const data = await response.json();
        setTrades(data.trades);
      }
    } catch (error) {
      console.error('Failed to fetch trades:', error);
    }
  };

  // Fetch bot config (mode, risk params, heartbeat)
  const fetchConfig = async () => {
    try {
      const response = await fetch('/api/config');
      if (response.ok) {
        const data = await response.json();
        setBotConfig(data.config);
      }
    } catch (error) {
      console.error('Failed to fetch bot config:', error);
    }
  };

  // Fetch balance history for charts
  const fetchPerformance = async () => {
    try {
      // Pull enough history to support "ALL" without truncating mid-session.
      const response = await fetch('/api/performance?limit=5000');
      if (response.ok) {
        const data = await response.json();
        setBalanceHistory(data.history || []);
      }
    } catch (error) {
      console.error('Failed to fetch performance:', error);
    }
  };

  // Fetch positions, orders, fills for portfolio tabs
  const fetchPortfolio = async () => {
    try {
      const [posRes, ordRes, fillRes, settleRes] = await Promise.all([
        fetch('/api/positions'),
        fetch('/api/orders'),
        fetch('/api/fills?limit=100'),
        fetch('/api/settlements?limit=100'),
      ]);
      if (posRes.ok) {
        const data = await posRes.json();
        setPositions(data.positions || []);
      }
      if (ordRes.ok) {
        const data = await ordRes.json();
        setOrders(data.orders || []);
      }
      if (fillRes.ok) {
        const data = await fillRes.json();
        setFills(data.fills || []);
      }
      if (settleRes.ok) {
        const data = await settleRes.json();
        setSettlements(data.settlements || []);
      }
    } catch (error) {
      console.error('Failed to fetch portfolio:', error);
    }
  };

  // Send a command to the bot via the command queue, then poll for acknowledgment
  const sendCommand = useCallback(async (command: string, params?: Record<string, unknown>) => {
    try {
      const response = await fetch('/api/commands', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, params }),
      });
      if (response.ok) {
        const { command: cmd } = await response.json();
        addToast('info', `Command queued: ${command}`);

        // Poll for acknowledgment (3 checks, 2s apart)
        if (cmd?.id) {
          let acknowledged = false;
          for (let i = 0; i < 3 && !acknowledged; i++) {
            await new Promise(r => setTimeout(r, 2000));
            try {
              const statusRes = await fetch(`/api/commands?limit=5`);
              if (statusRes.ok) {
                const { commands } = await statusRes.json();
                const match = commands?.find((c: { id: string; status: string }) => c.id === cmd.id);
                if (match && match.status !== 'pending') {
                  acknowledged = true;
                  if (match.status === 'executed') {
                    addToast('success', `Bot executed: ${command}`);
                  } else if (match.status === 'failed') {
                    addToast('warning', `Bot rejected: ${command}`);
                  } else {
                    addToast('info', `Bot acknowledged: ${command}`);
                  }
                }
              }
            } catch { /* polling failure is non-critical */ }
          }
          if (!acknowledged) {
            addToast('warning', `Command pending — bot may be offline: ${command}`);
          }
        }

        setTimeout(fetchConfig, 1000);
      } else {
        const data = await response.json();
        addToast('warning', `Command failed: ${data.error || command}`);
      }
    } catch (error) {
      console.error('Failed to send command:', error);
      addToast('warning', `Failed to send command: ${command}`);
    }
  }, [addToast]);

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      await Promise.all([fetchStatus(), fetchTrades(), fetchConfig(), fetchPerformance(), fetchPortfolio()]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Auto-refresh every 5 seconds (status/trades/config), 30s for balance history
  useEffect(() => {
    const fast = setInterval(() => {
      fetchStatus();
      fetchTrades();
      fetchConfig();
    }, 5000);

    const slow = setInterval(fetchPerformance, 30000);
    const portfolio = setInterval(fetchPortfolio, 10000);

    return () => {
      clearInterval(fast);
      clearInterval(slow);
      clearInterval(portfolio);
    };
  }, []);

  // Detect new trades by comparing latest trade ID (not array length,
  // which plateaus at the API limit of 20 and stops detecting new trades).
  useEffect(() => {
    if (trades.length === 0) return;

    const latestTrade = trades[0]; // sorted desc by created_at
    if (lastSeenTradeId && latestTrade.id !== lastSeenTradeId) {
      const action = latestTrade?.action?.toLowerCase() ?? '';
      const pnl = latestTrade?.pnl_cents ?? 0;
      const ticker = latestTrade?.market_ticker ?? '';

      if (action === 'buy') {
        addToast('info', `BUY ${ticker} @ ${latestTrade.entry_price_cents}c`);
        sound.playBuy();
      } else if (action === 'sell') {
        const label = pnl > 0
          ? `SELL ${ticker}: +$${(pnl / 100).toFixed(2)}`
          : pnl < 0
            ? `SELL ${ticker}: -$${(Math.abs(pnl) / 100).toFixed(2)}`
            : `SELL ${ticker}`;
        addToast(pnl >= 0 ? 'success' : 'warning', label);
        sound.playSell();
      } else {
        addToast('info', 'New trade executed');
        sound.playTrade();
      }
    }
    setLastSeenTradeId(latestTrade.id);
  }, [trades]);

  // Manual refresh handler
  const handleRefresh = useCallback(() => {
    fetchStatus();
    fetchTrades();
    fetchPerformance();
    fetchPortfolio();
    addToast('info', 'Data refreshed');
    sound.playNotification();
  }, [addToast, sound]);

  // Keyboard shortcuts
  useKeyboardShortcuts({
    onRefresh: handleRefresh,
    onToggleSound: () => {
      sound.toggle();
      addToast('info', `Sound ${sound.enabled ? 'disabled' : 'enabled'}`);
    },
    onHelp: () => setShowHelp(true),
  });

  // Compute daily P&L from balance history (replaces bot's always-$0 daily_pnl_cents)
  const dailyChange = useMemo(() => {
    if (balanceHistory.length < 2) return { cents: 0, pct: 0 };
    const todayStr = new Date().toLocaleDateString('en-CA'); // "2026-02-09"
    const todayEntries = balanceHistory.filter(e =>
      new Date(e.timestamp).toLocaleDateString('en-CA') === todayStr
    );
    if (todayEntries.length < 2) return { cents: 0, pct: 0 };
    // balanceHistory is desc order: [0] = newest, [last] = oldest
    const earliest = todayEntries[todayEntries.length - 1].balance_cents;
    const latest = todayEntries[0].balance_cents;
    const changeCents = latest - earliest;
    const changePct = earliest > 0 ? (changeCents / earliest) * 100 : 0;
    return { cents: changeCents, pct: changePct };
  }, [balanceHistory]);

  const pnlData = useMemo(() => {
    if (balanceHistory.length < 2) return [];
    const chrono = [...balanceHistory].reverse();
    const startBalance = chrono[0].balance_cents;
    return chrono.map((entry, i) => ({
      time: new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      pnl: i > 0 ? entry.balance_cents - chrono[i - 1].balance_cents : 0,
      cumulative: entry.balance_cents - startBalance,
    }));
  }, [balanceHistory]);

  // Only count closed trades for win rate
  const closedTrades = useMemo(() => trades.filter(t => t.status === 'closed'), [trades]);

  if (loading || !dashboardState) {
    return (
      <div className="min-h-screen terminal flex items-center justify-center">
        <div className="text-2xl terminal-glow-bright">
          INITIALIZING<span className="cursor">_</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen terminal md:flex">
      {/* Control Sidebar */}
      <Sidebar
        dashboardState={dashboardState}
        botConfig={botConfig}
        onCommand={sendCommand}
        sound={sound}
        dailyChangeCents={dailyChange.cents}
        dailyChangePct={dailyChange.pct}
        onStrategyToggle={(name, enabled) => {
          // 1. Optimistic update — reflect toggle instantly in UI
          if (dashboardState) {
            setDashboardState({
              ...dashboardState,
              strategies: dashboardState.strategies.map(s =>
                s.name === name ? { ...s, enabled } : s
              ),
            });
          }
          // 2. Register pending override so polling preserves this value
          setPendingToggles(prev => ({ ...prev, [name]: { enabled, at: Date.now() } }));
          // 3. Persist to Supabase
          fetch('/api/strategies/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy: name, enabled }),
          }).catch(() => {});
        }}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main Dashboard Content */}
      <div className="md:flex-1 p-3 md:p-6 overflow-auto">
        <div className="max-w-[1800px] mx-auto">
          {/* Mobile Header Bar */}
          <div className="flex items-center gap-3 md:hidden mb-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="p-2 border border-terminal-green/40 rounded text-terminal-green hover:bg-terminal-green/10 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div className="flex-1 flex items-center justify-between">
              <span className="text-sm font-bold terminal-glow tracking-wider">DEEPSTACK</span>
              <div className="flex items-center gap-3">
                <MarketStatus compact />
                <span className={`inline-block w-2 h-2 rounded-full ${botConfig?.last_heartbeat && (Date.now() - new Date(botConfig.last_heartbeat).getTime()) < 120_000 ? 'bg-terminal-green animate-pulse' : 'bg-terminal-red'}`} />
                <span className="text-[10px] text-terminal-dim uppercase">
                  {(botConfig?.mode as string) || 'stopped'}
                </span>
              </div>
            </div>
          </div>

          {/* Header (hidden on mobile — replaced by compact bar above) */}
          <div className="hidden md:block">
            <Header onLogout={logout} lastHeartbeat={botConfig?.last_heartbeat} botMode={botConfig?.mode} />
          </div>

        {/* Staleness / Error Banner */}
        {(fetchError || Date.now() - lastSuccessfulFetch > 30_000) && (
          <div className="mb-3 px-3 py-2 border rounded text-xs font-mono border-terminal-amber/60 bg-terminal-amber/10 text-terminal-amber">
            {fetchError
              ? `DATA FEED ERROR: ${fetchError} — showing last known state`
              : `DATA STALE — last update ${Math.round((Date.now() - lastSuccessfulFetch) / 1000)}s ago`}
          </div>
        )}

        {/* Hero Performance Panel */}
        <div className="mb-4 md:mb-6">
          <PerformanceHero balanceHistory={balanceHistory} />
        </div>

        {/* Strategy Status Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 md:gap-4 mb-4 md:mb-6">
          {dashboardState.strategies.map((strategy) => (
            <StrategyCard
              key={strategy.name}
              strategy={strategy}
              onClick={() => setSelectedStrategy(strategy)}
            />
          ))}
        </div>

        {/* Metrics Row */}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-2 md:gap-4 mb-4 md:mb-6">
          <RiskMetricsCard metrics={dashboardState.risk} />
          <WinRateGauge
            winRate={closedTrades.length > 0 ? (closedTrades.filter(t => (t.pnl_cents ?? 0) > 0).length / closedTrades.length) * 100 : 0}
            totalTrades={closedTrades.length}
            wins={closedTrades.filter(t => (t.pnl_cents ?? 0) > 0).length}
            losses={closedTrades.filter(t => (t.pnl_cents ?? 0) < 0).length}
          />
          <TradeActivity onOpportunitiesClick={() => setShowOpportunities(true)} />
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 md:gap-4 mb-4 md:mb-6">
          <PnLChart data={pnlData} />
          <LiveFeed />
        </div>

        {/* Portfolio Tabs: Positions | Orders | Fills | Journal */}
        <div className="mb-4 md:mb-6">
          <div className="flex gap-1 mb-3 border-b border-terminal-green/30 pb-1">
            {(['positions', 'orders', 'fills', 'settlements', 'journal'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setPortfolioTab(tab)}
                className={`px-3 py-1.5 text-xs font-mono uppercase tracking-wider transition-colors ${
                  portfolioTab === tab
                    ? 'text-terminal-green border-b-2 border-terminal-green'
                    : 'text-terminal-dim hover:text-terminal-green/70'
                }`}
              >
                {tab}
                {tab === 'positions' && positions.length > 0 && (
                  <span className="ml-1 text-terminal-dim">({positions.length})</span>
                )}
                {tab === 'orders' && orders.filter(o => o.status === 'resting').length > 0 && (
                  <span className="ml-1 text-terminal-cyan-bright">({orders.filter(o => o.status === 'resting').length})</span>
                )}
                {tab === 'settlements' && settlements.length > 0 && (
                  <span className="ml-1 text-terminal-dim">({settlements.length})</span>
                )}
              </button>
            ))}
          </div>

          {portfolioTab === 'positions' && <PositionsTable positions={positions} />}
          {portfolioTab === 'orders' && <OrdersTable orders={orders} />}
          {portfolioTab === 'fills' && <FillsHistory fills={fills} />}
          {portfolioTab === 'settlements' && <SettlementsHistory settlements={settlements} />}
          {portfolioTab === 'journal' && <TradeJournal trades={trades} onTradeClick={(trade) => setSelectedTrade(trade)} />}
        </div>

        {/* Footer */}
        <div className="mt-4 md:mt-6 border-t border-terminal-green pt-3 md:pt-4">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 text-[10px] md:text-xs text-terminal-dim">
            <div className="flex items-center gap-4">
              <span>DEEPSTACK TRADER v2.0</span>
              <ConnectionStatus />
            </div>
            <div className="flex items-center gap-4">
              <span className="text-terminal-cyan-dim hidden md:inline">[?] for shortcuts</span>
              <span>
                LAST UPDATE: {new Date(dashboardState.timestamp).toLocaleString()}
              </span>
            </div>
          </div>
        </div>
        </div>
      </div>

      {/* Toast notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Shortcuts help modal */}
      <ShortcutsHelp
        isOpen={showHelp}
        onClose={() => setShowHelp(false)}
        soundEnabled={sound.enabled}
      />

      {/* Opportunities modal */}
      <OpportunitiesModal
        isOpen={showOpportunities}
        onClose={() => setShowOpportunities(false)}
      />

      {/* Trade detail modal */}
      <TradeDetailModal
        isOpen={selectedTrade !== null}
        onClose={() => setSelectedTrade(null)}
        trade={selectedTrade}
      />

      {/* Strategy detail modal */}
      <StrategyDetailModal
        isOpen={selectedStrategy !== null}
        onClose={() => setSelectedStrategy(null)}
        strategy={selectedStrategy}
        onToggle={(name, enabled) => {
          sendCommand('toggle_strategy', { strategy: name, enabled });
          // 1. Optimistic update — reflect toggle instantly in UI
          if (dashboardState) {
            setDashboardState({
              ...dashboardState,
              strategies: dashboardState.strategies.map(s =>
                s.name === name ? { ...s, enabled } : s
              ),
            });
          }
          // 2. Register pending override so polling preserves this value
          setPendingToggles(prev => ({ ...prev, [name]: { enabled, at: Date.now() } }));
          // 3. Persist to Supabase
          fetch('/api/strategies/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy: name, enabled }),
          }).catch(() => {});
        }}
      />
    </div>
  );
}
