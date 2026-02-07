'use client';

import { useEffect, useState, useCallback } from 'react';
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
import { DashboardState, Trade, Strategy, BotConfig } from '@/lib/types';

export default function Dashboard() {
  const [dashboardState, setDashboardState] = useState<DashboardState | null>(null);
  const [botConfig, setBotConfig] = useState<BotConfig | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [showHelp, setShowHelp] = useState(false);
  const [prevTradeCount, setPrevTradeCount] = useState(0);

  // Mobile sidebar state
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Modal states
  const [showOpportunities, setShowOpportunities] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);

  // Toast notifications
  const { toasts, addToast, dismissToast } = useToasts();

  // Sound effects
  const sound = useSoundEffects();

  // Fetch dashboard state
  const fetchStatus = async () => {
    try {
      const response = await fetch('/api/status');
      if (response.ok) {
        const data = await response.json();
        setDashboardState(data);
      }
    } catch (error) {
      console.error('Failed to fetch status:', error);
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

  // Send a command to the bot via the command queue
  const sendCommand = useCallback(async (command: string, params?: Record<string, unknown>) => {
    try {
      const response = await fetch('/api/commands', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, params }),
      });
      if (response.ok) {
        addToast('info', `Command sent: ${command}`);
        // Refresh config after a short delay to reflect the change
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
      await Promise.all([fetchStatus(), fetchTrades(), fetchConfig()]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Auto-refresh every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchStatus();
      fetchTrades();
      fetchConfig();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // Detect new trades and notify
  useEffect(() => {
    if (trades.length > prevTradeCount && prevTradeCount > 0) {
      const newTrade = trades[0];
      const pnl = newTrade?.pnl_cents ?? 0;
      if (pnl > 0) {
        addToast('success', `Trade closed: +$${(pnl / 100).toFixed(2)}`);
        sound.playSuccess();
      } else if (pnl < 0) {
        addToast('warning', `Trade closed: -$${(Math.abs(pnl) / 100).toFixed(2)}`);
        sound.playError();
      } else {
        addToast('info', 'New trade executed');
        sound.playTrade();
      }
    }
    setPrevTradeCount(trades.length);
  }, [trades.length]);

  // Manual refresh handler
  const handleRefresh = useCallback(() => {
    fetchStatus();
    fetchTrades();
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
              <div className="flex items-center gap-2">
                <span className={`inline-block w-2 h-2 rounded-full ${botConfig?.last_heartbeat && (Date.now() - new Date(botConfig.last_heartbeat).getTime()) < 120_000 ? 'bg-terminal-green animate-pulse' : 'bg-terminal-red'}`} />
                <span className="text-[10px] text-terminal-dim uppercase">
                  {(botConfig?.mode as string) || 'stopped'}
                </span>
              </div>
            </div>
          </div>

          {/* Header (hidden on mobile — replaced by compact bar above) */}
          <div className="hidden md:block">
            <Header />
          </div>

        {/* Hero Performance Panel */}
        <div className="mb-4 md:mb-6">
          <PerformanceHero />
        </div>

        {/* Strategy Status Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 md:gap-4 mb-4 md:mb-6">
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
            winRate={trades.length > 0 ? (trades.filter(t => (t.pnl_cents ?? 0) > 0).length / trades.length) * 100 : 0}
            totalTrades={trades.length}
            wins={trades.filter(t => (t.pnl_cents ?? 0) > 0).length}
            losses={trades.filter(t => (t.pnl_cents ?? 0) < 0).length}
          />
          <TradeActivity onOpportunitiesClick={() => setShowOpportunities(true)} />
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 md:gap-4 mb-4 md:mb-6">
          <PnLChart />
          <LiveFeed />
        </div>

        {/* Trade Journal - Full Width */}
        <div className="mb-4 md:mb-6">
          <TradeJournal trades={trades} onTradeClick={(trade) => setSelectedTrade(trade)} />
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
      />
    </div>
  );
}
