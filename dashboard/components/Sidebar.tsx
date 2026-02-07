'use client';

import { useState } from 'react';
import { DashboardState, Strategy, BotConfig } from '@/lib/types';
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
    return name
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
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
      <div className="p-4 border-b border-terminal-green/30">
        <div className="text-[10px] text-terminal-dim mb-3 tracking-[0.15em] uppercase">Strategies</div>
        <div className="space-y-2">
          {strategies.map((strategy) => (
            <div
              key={strategy.name}
              className={`w-full p-3 border text-left transition-all duration-200 rounded-lg ${
                strategy.enabled
                  ? 'border-terminal-amber/40 bg-terminal-amber/[0.06] hover:bg-terminal-amber/[0.10]'
                  : 'border-terminal-dim/15 bg-terminal-bg-panel/50 hover:bg-terminal-bg-panel hover:border-terminal-dim/25'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className={`text-[11px] font-bold tracking-wide transition-colors ${strategy.enabled ? 'text-terminal-amber' : 'text-terminal-dim/60'}`}>
                  {getStrategyDisplayName(strategy.name).slice(0, 14)}
                </span>
                <button
                  onClick={() => handleStrategyToggle(strategy.name, strategy.enabled)}
                  className={`w-10 h-5 rounded-full relative transition-all duration-200 border ${
                    strategy.enabled
                      ? 'bg-terminal-amber/25 border-terminal-amber/40 shadow-[0_0_8px_rgba(255,191,0,0.2)]'
                      : 'bg-terminal-bg border-terminal-dim/60 shadow-[inset_0_1px_3px_rgba(0,0,0,0.4)]'
                  }`}
                >
                  <div className={`absolute top-0.5 w-4 h-4 rounded-full transition-all duration-200 ${
                    strategy.enabled
                      ? 'right-0.5 bg-terminal-amber shadow-[0_0_6px_rgba(255,191,0,0.5)]'
                      : 'left-0.5 bg-terminal-dim/80 border-2 border-terminal-dim'
                  }`} />
                </button>
              </div>
              <div className="flex items-center gap-3 text-[10px]">
                {(() => {
                  const status = getStrategyStatus(strategy);
                  return (
                    <div className="flex items-center gap-1.5">
                      <div className={`w-1.5 h-1.5 rounded-full ${status.dotColor}`} />
                      <span className={`font-mono ${strategy.enabled ? status.color : 'text-terminal-dim/40'}`}>
                        {status.icon}
                      </span>
                    </div>
                  );
                })()}
                <span className="text-terminal-dim/30">|</span>
                <span className={strategy.enabled ? 'text-terminal-cyan' : 'text-terminal-dim/40'}>
                  {strategy.active_positions} pos
                </span>
                <span className="text-terminal-dim/30">|</span>
                <span className={strategy.enabled ? 'text-terminal-amber' : 'text-terminal-dim/40'}>
                  {strategy.opportunities_found} opp
                </span>
              </div>
            </div>
          ))}
        </div>
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
