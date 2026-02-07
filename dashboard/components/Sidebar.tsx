'use client';

import { useState } from 'react';
import { DashboardState, Strategy, BotConfig } from '@/lib/types';
import { getStrategyMeta, CATEGORY_LABELS, CATEGORY_ICONS, StrategyCategory } from '@/lib/strategy-meta';
import RiskControls from './RiskControls';

interface SidebarProps {
  dashboardState: DashboardState | null;
  botConfig: BotConfig | null;
  onCommand: (command: string, params?: Record<string, unknown>) => void;
  onStrategyToggle?: (strategyName: string, enabled: boolean) => void;
  isOpen?: boolean;
  onClose?: () => void;
}

type BotRunState = 'running' | 'paused' | 'stopped' | 'dry_run';

const RUN_STATE_CONFIG: Record<BotRunState, { color: string; bgColor: string; label: string }> = {
  running: { color: 'text-terminal-green', bgColor: 'bg-terminal-green', label: 'RUNNING' },
  paused: { color: 'text-terminal-cyan', bgColor: 'bg-terminal-cyan', label: 'PAUSED' },
  stopped: { color: 'text-terminal-red', bgColor: 'bg-terminal-red', label: 'STOPPED' },
  dry_run: { color: 'text-terminal-amber', bgColor: 'bg-terminal-amber', label: 'DRY RUN' },
};

const POLL_INTERVALS = [
  { label: '15s', value: 15 },
  { label: '30s', value: 30 },
  { label: '60s', value: 60 },
  { label: '120s', value: 120 },
];

export default function Sidebar({ dashboardState, botConfig, onCommand, onStrategyToggle, isOpen, onClose }: SidebarProps): JSX.Element {
  const [showRiskControls, setShowRiskControls] = useState(false);
  const [showForceCloseConfirm, setShowForceCloseConfirm] = useState(false);
  const [collapsedCategories, setCollapsedCategories] = useState<Record<string, boolean>>({});

  const botRunState: BotRunState = (botConfig?.mode as BotRunState) || 'stopped';
  const balance = dashboardState?.account?.balance_cents ?? 0;
  const dailyPnl = dashboardState?.account?.daily_pnl_cents ?? 0;
  const positions = dashboardState?.account?.total_positions ?? 0;
  const strategies = dashboardState?.strategies ?? [];
  const lastHeartbeat = botConfig?.last_heartbeat;
  const pollInterval = botConfig?.poll_interval_seconds ?? 60;

  // Bot is "alive" if heartbeat was within last 2 minutes
  const isAlive = lastHeartbeat
    ? (Date.now() - new Date(lastHeartbeat).getTime()) < 120_000
    : false;

  const isDryRun = botRunState === 'dry_run';

  function formatCents(cents: number): string {
    return `$${(cents / 100).toFixed(2)}`;
  }

  function handleStrategyToggle(strategyName: string, currentEnabled: boolean): void {
    onCommand('toggle_strategy', { strategy: strategyName, enabled: !currentEnabled });
    onStrategyToggle?.(strategyName, !currentEnabled);
  }

  function getStrategyDisplayName(name: string): string {
    return getStrategyMeta(name).shortName;
  }

  function groupStrategiesByCategory(strategies: Strategy[]): Record<StrategyCategory, Strategy[]> {
    const groups: Record<StrategyCategory, Strategy[]> = { original: [], prediction_market: [], crypto: [] };
    for (const s of strategies) {
      const meta = getStrategyMeta(s.name);
      groups[meta.category].push(s);
    }
    return groups;
  }

  function getStrategyStatus(strategy: Strategy): { icon: string; color: string; dotColor: string } {
    if (!strategy.enabled) {
      return { icon: 'OFF', color: 'text-terminal-dim', dotColor: 'bg-terminal-dim/30' };
    }
    switch (strategy.status) {
      case 'active':
        return { icon: 'ACT', color: 'text-terminal-green', dotColor: 'bg-terminal-green animate-pulse' };
      case 'scanning':
        return { icon: 'SCN', color: 'text-terminal-amber', dotColor: 'bg-terminal-amber animate-pulse' };
      case 'error':
        return { icon: 'ERR', color: 'text-terminal-red', dotColor: 'bg-terminal-red' };
      default:
        return { icon: 'IDL', color: 'text-terminal-cyan', dotColor: 'bg-terminal-cyan' };
    }
  }

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/70 z-40 md:hidden"
          onClick={onClose}
        />
      )}

      <div className={`
        w-72 md:w-60 border-r border-terminal-green/20 bg-[#0D0208] bg-gradient-to-b from-terminal-bg-elevated to-terminal-bg flex flex-col min-h-screen
        fixed md:relative inset-y-0 left-0 md:inset-auto z-50 md:z-auto
        transition-transform duration-300 ease-in-out overflow-y-auto
        ${isOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0
      `}>
        {/* Subtle edge glow */}
        <div className="absolute right-0 top-0 bottom-0 w-px bg-gradient-to-b from-terminal-green/30 via-terminal-green/10 to-terminal-green/30" />

        {/* Logo/Title */}
        <div className="p-5 border-b border-terminal-green/40 bg-terminal-green/[0.02]">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] text-terminal-green-dim tracking-[0.2em] mb-1 uppercase">DeepStack</div>
              <div className="text-xl font-bold terminal-glow tracking-wider flex items-center gap-2">
                TRADER
                <span className={`inline-block w-2 h-2 rounded-full ${isAlive ? 'bg-terminal-green animate-pulse' : 'bg-terminal-red'}`} />
              </div>
            </div>
            {/* Mobile close button */}
            <button
              onClick={onClose}
              className="md:hidden p-2 text-terminal-dim hover:text-terminal-green transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="text-[9px] text-terminal-dim/50 mt-1">
            {isAlive ? 'Bot online' : 'Bot offline'}
            {lastHeartbeat && ` — ${new Date(lastHeartbeat).toLocaleTimeString()}`}
          </div>
        </div>

      {/* Bot Mode & Status */}
      <div className="p-4 border-b border-terminal-green/30">
        {/* Mode Selector */}
        <div className="text-[10px] text-terminal-dim mb-2 tracking-[0.15em] uppercase">Mode</div>
        <div className="flex gap-2 mb-5">
          <button
            onClick={() => onCommand('set_mode', { dry_run: true })}
            className={`flex-1 py-2.5 px-3 text-xs font-bold border rounded-md transition-all duration-200 ${
              isDryRun
                ? 'border-terminal-amber bg-terminal-amber/15 text-terminal-amber shadow-[0_0_12px_rgba(255,191,0,0.15)]'
                : 'border-terminal-dim/20 text-terminal-dim/60 hover:border-terminal-amber/40 hover:text-terminal-amber/80'
            }`}
          >
            DRY RUN
          </button>
          <button
            onClick={() => onCommand('set_mode', { dry_run: false })}
            className={`flex-1 py-2.5 px-3 text-xs font-bold border rounded-md transition-all duration-200 ${
              !isDryRun && botRunState !== 'stopped'
                ? 'border-terminal-green bg-terminal-green/15 text-terminal-green shadow-[0_0_12px_rgba(0,255,65,0.15)]'
                : 'border-terminal-dim/20 text-terminal-dim/60 hover:border-terminal-green/40 hover:text-terminal-green/80'
            }`}
          >
            LIVE
          </button>
        </div>

        {/* Run State */}
        <div className="text-[10px] text-terminal-dim mb-2 tracking-[0.15em] uppercase">Status</div>
        <div className="flex items-center gap-3 mb-4 py-2 px-3 rounded-md bg-terminal-bg-panel/60 border border-terminal-green/10">
          <div className={`w-2.5 h-2.5 rounded-full ${RUN_STATE_CONFIG[botRunState].bgColor} ${botRunState === 'running' ? 'animate-pulse shadow-[0_0_8px_currentColor]' : ''}`} />
          <span className={`text-sm font-bold tracking-wide ${RUN_STATE_CONFIG[botRunState].color}`}>
            {RUN_STATE_CONFIG[botRunState].label}
          </span>
        </div>

        {/* Run Controls */}
        <div className="flex gap-2">
          {botRunState === 'stopped' ? (
            <button
              onClick={() => onCommand('start')}
              className="flex-1 py-2.5 px-3 text-xs font-bold border border-terminal-green text-terminal-green hover:bg-terminal-green/15 hover:shadow-[0_0_15px_rgba(0,255,65,0.2)] rounded-md transition-all duration-200"
            >
              START
            </button>
          ) : botRunState === 'running' || botRunState === 'dry_run' ? (
            <>
              <button
                onClick={() => onCommand('pause')}
                className="flex-1 py-2.5 px-3 text-xs font-bold border border-terminal-cyan text-terminal-cyan hover:bg-terminal-cyan/15 rounded-md transition-all duration-200"
              >
                PAUSE
              </button>
              <button
                onClick={() => onCommand('stop')}
                className="flex-1 py-2.5 px-3 text-xs font-bold border border-terminal-red text-terminal-red hover:bg-terminal-red/15 rounded-md transition-all duration-200"
              >
                STOP
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onCommand('resume')}
                className="flex-1 py-2.5 px-3 text-xs font-bold border border-terminal-green text-terminal-green hover:bg-terminal-green/15 hover:shadow-[0_0_15px_rgba(0,255,65,0.2)] rounded-md transition-all duration-200"
              >
                RESUME
              </button>
              <button
                onClick={() => onCommand('stop')}
                className="flex-1 py-2.5 px-3 text-xs font-bold border border-terminal-red text-terminal-red hover:bg-terminal-red/15 rounded-md transition-all duration-200"
              >
                STOP
              </button>
            </>
          )}
        </div>

        {/* Quick Actions */}
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => onCommand('scan_now')}
            className="flex-1 py-1.5 px-2 text-[10px] font-bold border border-terminal-cyan/40 text-terminal-cyan/80 hover:bg-terminal-cyan/10 rounded transition-all"
          >
            SCAN NOW
          </button>
          <button
            onClick={() => setShowForceCloseConfirm(true)}
            className="flex-1 py-1.5 px-2 text-[10px] font-bold border border-terminal-red/40 text-terminal-red/80 hover:bg-terminal-red/10 rounded transition-all"
          >
            FORCE CLOSE
          </button>
        </div>

        {/* Force Close Confirmation */}
        {showForceCloseConfirm && (
          <div className="mt-2 p-2 rounded border border-terminal-red/50 bg-terminal-red/10">
            <div className="text-[10px] text-terminal-red mb-2">Close all positions?</div>
            <div className="flex gap-2">
              <button
                onClick={() => { onCommand('force_close'); setShowForceCloseConfirm(false); }}
                className="flex-1 py-1 text-[10px] font-bold bg-terminal-red/20 border border-terminal-red text-terminal-red rounded"
              >
                CONFIRM
              </button>
              <button
                onClick={() => setShowForceCloseConfirm(false)}
                className="flex-1 py-1 text-[10px] font-bold border border-terminal-dim/30 text-terminal-dim rounded"
              >
                CANCEL
              </button>
            </div>
          </div>
        )}

        {/* Poll Interval */}
        <div className="mt-3">
          <div className="text-[10px] text-terminal-dim mb-1.5 tracking-[0.15em] uppercase">Scan Interval</div>
          <div className="flex gap-1">
            {POLL_INTERVALS.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => onCommand('set_poll_interval', { interval: value })}
                className={`flex-1 py-1 text-[10px] font-bold border rounded transition-all ${
                  pollInterval === value
                    ? 'border-terminal-cyan bg-terminal-cyan/15 text-terminal-cyan'
                    : 'border-terminal-dim/20 text-terminal-dim/50 hover:border-terminal-cyan/30'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Balance & P/L */}
      <div className="p-4 border-b border-terminal-green/30">
        <div className="text-[10px] text-terminal-dim mb-2 tracking-[0.15em] uppercase">Balance</div>
        <div className="text-3xl font-bold terminal-glow-bright tabular-nums tracking-tight">
          {formatCents(balance)}
        </div>
        <div className={`text-sm font-bold tabular-nums mt-2 flex items-center gap-2 ${dailyPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red'}`}>
          <span className={`inline-block w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent ${
            dailyPnl >= 0 ? 'border-b-[6px] border-b-terminal-green' : 'border-t-[6px] border-t-terminal-red'
          }`} />
          {dailyPnl >= 0 ? '+' : ''}{formatCents(dailyPnl)} today
        </div>
      </div>

      {/* Positions */}
      <div className="p-4 border-b border-terminal-green/30">
        <div className="text-[10px] text-terminal-dim mb-2 tracking-[0.15em] uppercase">Positions</div>
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-bold text-terminal-cyan tabular-nums">
            {positions.toString().padStart(2, '0')}
          </span>
          <span className="text-[10px] text-terminal-dim">open</span>
        </div>
      </div>

      {/* Strategy Toggles */}
      <div className="border-b border-terminal-green/30">
        {(() => {
          const grouped = groupStrategiesByCategory(strategies);
          const categories: StrategyCategory[] = ['original', 'crypto', 'prediction_market'];
          const catTheme: Record<StrategyCategory, { accent: string; accentDim: string; bg: string; border: string; glow: string; dot: string }> = {
            original: {
              accent: 'text-terminal-green',
              accentDim: 'text-terminal-green/60',
              bg: 'bg-terminal-green',
              border: 'border-terminal-green',
              glow: 'shadow-[0_0_8px_rgba(0,255,65,0.15)]',
              dot: 'bg-terminal-green',
            },
            crypto: {
              accent: 'text-terminal-amber',
              accentDim: 'text-terminal-amber/60',
              bg: 'bg-terminal-amber',
              border: 'border-terminal-amber',
              glow: 'shadow-[0_0_8px_rgba(255,191,0,0.15)]',
              dot: 'bg-terminal-amber',
            },
            prediction_market: {
              accent: 'text-terminal-cyan',
              accentDim: 'text-terminal-cyan/60',
              bg: 'bg-terminal-cyan',
              border: 'border-terminal-cyan',
              glow: 'shadow-[0_0_8px_rgba(0,255,255,0.15)]',
              dot: 'bg-terminal-cyan',
            },
          };
          return categories.map((cat) => {
            const group = grouped[cat];
            if (group.length === 0) return null;
            const theme = catTheme[cat];
            const activeCount = group.filter(s => s.enabled).length;
            const isCollapsed = collapsedCategories[cat] ?? false;
            return (
              <div key={cat}>
                {/* Category Header — clickable to collapse */}
                <button
                  onClick={() => setCollapsedCategories(prev => ({ ...prev, [cat]: !prev[cat] }))}
                  className={`w-full flex items-center gap-2 px-4 py-3 transition-all duration-200 hover:bg-white/[0.02] ${
                    cat !== 'original' ? 'border-t border-terminal-dim/20' : ''
                  }`}
                >
                  {/* Icon badge */}
                  <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${theme.bg}/15 ${theme.accent} border ${theme.border}/30`}>
                    {CATEGORY_ICONS[cat]}
                  </span>
                  {/* Label */}
                  <span className={`text-[10px] font-bold tracking-[0.15em] ${theme.accent}`}>
                    {CATEGORY_LABELS[cat]}
                  </span>
                  <div className="flex-1" />
                  {/* Active count badge */}
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                    activeCount > 0
                      ? `${theme.bg}/15 ${theme.accent}`
                      : 'bg-terminal-dim/10 text-terminal-dim/50'
                  }`}>
                    {activeCount}/{group.length} ON
                  </span>
                  {/* Collapse chevron */}
                  <svg className={`w-3 h-3 text-terminal-dim/40 transition-transform duration-200 ${isCollapsed ? '-rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {/* Strategy list */}
                {!isCollapsed && (
                  <div className="px-3 pb-3 space-y-1">
                    {group.map((strategy) => {
                      const status = getStrategyStatus(strategy);
                      return (
                        <div
                          key={strategy.name}
                          className={`w-full p-2 text-left transition-all duration-200 rounded border-l-2 ${
                            strategy.enabled
                              ? `${theme.border}/60 bg-white/[0.03] hover:bg-white/[0.05]`
                              : 'border-[#2a2a3d] bg-[#0e0e16] hover:bg-[#141420] hover:border-[#3a3a50]'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              {/* Status dot */}
                              <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${strategy.enabled ? status.dotColor : 'bg-[#4a4a65]'}`} />
                              {/* Name */}
                              <span className={`text-[11px] font-bold tracking-wide truncate transition-colors ${
                                strategy.enabled ? theme.accent : 'text-[#5a5a75]'
                              }`}>
                                {getStrategyDisplayName(strategy.name)}
                              </span>
                              {/* OFF label for disabled strategies */}
                              {!strategy.enabled && (
                                <span className="text-[8px] font-bold text-[#5a5a75] tracking-[0.1em] flex-shrink-0">OFF</span>
                              )}
                            </div>
                            {/* Toggle switch */}
                            <button
                              onClick={() => handleStrategyToggle(strategy.name, strategy.enabled)}
                              className={`w-9 h-5 rounded-full relative transition-all duration-300 border flex-shrink-0 ml-2 ${
                                strategy.enabled
                                  ? `${theme.bg}/20 ${theme.border}/50 ${theme.glow}`
                                  : 'bg-[#1a1a2e] border-[#3a3a55] shadow-[inset_0_1px_3px_rgba(0,0,0,0.3)] hover:border-[#55557a]'
                              }`}
                            >
                              <div className={`absolute top-[3px] w-3.5 h-3.5 rounded-full transition-all duration-300 ${
                                strategy.enabled
                                  ? `right-[3px] ${theme.dot} shadow-[0_0_6px_currentColor]`
                                  : 'left-[3px] bg-[#5a5a75] border border-[#6a6a88]'
                              }`} />
                            </button>
                          </div>
                          {/* Stats row — only show when enabled */}
                          {strategy.enabled && (
                            <div className="flex items-center gap-3 mt-1 ml-3.5 text-[9px]">
                              <span className={`font-mono ${status.color}`}>{status.icon}</span>
                              <span className="text-terminal-dim/30">|</span>
                              <span className="text-terminal-cyan">{strategy.active_positions} pos</span>
                              <span className="text-terminal-dim/30">|</span>
                              <span className="text-terminal-amber">{strategy.opportunities_found} opp</span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          });
        })()}
      </div>

      {/* Risk Controls (collapsible) */}
      <div className="p-4 flex-1 overflow-y-auto">
        <button
          onClick={() => setShowRiskControls(!showRiskControls)}
          className="w-full flex items-center justify-between text-[10px] text-terminal-dim tracking-[0.15em] uppercase mb-3 hover:text-terminal-green transition-colors"
        >
          <span>Risk Settings</span>
          <svg className={`w-3 h-3 transition-transform ${showRiskControls ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {showRiskControls && (
          <RiskControls
            botConfig={botConfig}
            onApply={(params) => onCommand('update_risk', params)}
          />
        )}
      </div>

      {/* Footer */}
      <div className="mt-auto border-t border-terminal-green/30 bg-terminal-bg-panel/30">
        <div className="px-4 py-3 flex items-center justify-between">
          <div className="text-[9px] text-terminal-dim/50 tracking-wider">DEEPSTACK</div>
          <div className="text-[9px] text-terminal-green/40 font-mono">v2.1.0</div>
        </div>
      </div>
    </div>
    </>
  );
}
