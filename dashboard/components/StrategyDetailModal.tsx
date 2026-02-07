'use client';

import { useEffect, useState } from 'react';
import Modal from './Modal';
import Sparkline from './Sparkline';
import { Strategy, Trade } from '@/lib/types';

interface StrategyDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  strategy: Strategy | null;
}

interface StrategyStats {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  totalPnl: number;
  avgWin: number;
  avgLoss: number;
  bestTrade: number;
  worstTrade: number;
  currentStreak: number;
  streakType: 'win' | 'loss' | 'none';
  recentTrades: Trade[];
  pnlHistory: number[];
}

export default function StrategyDetailModal({ isOpen, onClose, strategy }: StrategyDetailModalProps): JSX.Element | null {
  const [stats, setStats] = useState<StrategyStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen && strategy) {
      fetchStrategyStats(strategy.name);
    }
  }, [isOpen, strategy]);

  const fetchStrategyStats = async (strategyName: string) => {
    setLoading(true);
    try {
      const response = await fetch(`/api/strategies/${strategyName}/stats`);
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      } else {
        setStats(getEmptyStats());
      }
    } catch {
      setStats(getEmptyStats());
    }
    setLoading(false);
  };

  if (!strategy) return null;

  const formatCents = (cents: number) => {
    const sign = cents >= 0 ? '+' : '';
    return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={strategy.name}
      subtitle="STRATEGY DETAIL"
      size="lg"
    >
      {/* Status Banner */}
      <div className={`flex items-center justify-between p-3 mb-4 border ${
        strategy.enabled
          ? 'border-terminal-green bg-terminal-green bg-opacity-10'
          : 'border-terminal-red bg-terminal-red bg-opacity-10'
      }`}>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${
            strategy.enabled ? 'bg-terminal-green animate-pulse' : 'bg-terminal-red'
          }`} />
          <span className={strategy.enabled ? 'text-terminal-green' : 'text-terminal-red'}>
            {strategy.enabled ? 'ACTIVE' : 'DISABLED'}
          </span>
        </div>
        <div className="text-terminal-amber">
          {strategy.opportunities_found} OPPS FOUND
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-terminal-dim">
          LOADING STATS<span className="animate-pulse">...</span>
        </div>
      ) : stats ? (
        <>
          {/* Performance Overview */}
          <div className="grid grid-cols-3 gap-4 mb-4">
            <StatBox
              label="WIN RATE"
              value={`${stats.winRate.toFixed(1)}%`}
              color={stats.winRate >= 50 ? 'green' : 'red'}
            />
            <StatBox
              label="TOTAL P&L"
              value={formatCents(stats.totalPnl)}
              color={stats.totalPnl >= 0 ? 'amber' : 'red'}
            />
            <StatBox
              label="TOTAL TRADES"
              value={stats.totalTrades.toString()}
              color="cyan"
            />
          </div>

          {/* P&L Trend */}
          <div className="border border-terminal-green p-3 mb-4">
            <div className="text-xs text-terminal-dim mb-2">P&L TREND (LAST 20 TRADES)</div>
            <div className="h-16 flex items-center justify-center">
              <Sparkline
                data={stats.pnlHistory}
                width={400}
                height={60}
                color={stats.totalPnl >= 0 ? '#FFBF00' : '#FF4444'}
                showDot={true}
              />
            </div>
          </div>

          {/* Detailed Stats */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="border border-terminal-green p-3">
              <div className="text-xs text-terminal-dim mb-2">WIN/LOSS</div>
              <div className="flex justify-between">
                <div>
                  <span className="text-terminal-green-bright text-xl font-bold">{stats.wins}</span>
                  <span className="text-terminal-dim text-sm ml-1">W</span>
                </div>
                <div>
                  <span className="text-terminal-red text-xl font-bold">{stats.losses}</span>
                  <span className="text-terminal-dim text-sm ml-1">L</span>
                </div>
              </div>
            </div>
            <div className="border border-terminal-green p-3">
              <div className="text-xs text-terminal-dim mb-2">CURRENT STREAK</div>
              <div className={`text-xl font-bold ${
                stats.streakType === 'win' ? 'text-terminal-green-bright' :
                stats.streakType === 'loss' ? 'text-terminal-red' :
                'text-terminal-dim'
              }`}>
                {stats.currentStreak} {stats.streakType === 'win' ? 'WINS' : stats.streakType === 'loss' ? 'LOSSES' : '-'}
              </div>
            </div>
          </div>

          {/* Averages */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <MiniStat label="AVG WIN" value={formatCents(stats.avgWin)} color="green" />
            <MiniStat label="AVG LOSS" value={formatCents(stats.avgLoss)} color="red" />
            <MiniStat label="BEST" value={formatCents(stats.bestTrade)} color="green" />
            <MiniStat label="WORST" value={formatCents(stats.worstTrade)} color="red" />
          </div>

          {/* Recent Trades */}
          <div className="border-t border-terminal-green pt-4">
            <div className="text-xs text-terminal-dim mb-2">RECENT TRADES</div>
            <div className="space-y-1">
              {stats.recentTrades.slice(0, 5).map((trade, i) => (
                <div key={i} className="flex justify-between text-sm py-1 border-b border-terminal-green border-opacity-20">
                  <span className="text-terminal-cyan">{trade.market_ticker}</span>
                  <span className={trade.side === 'YES' ? 'text-terminal-green' : 'text-terminal-red'}>
                    {trade.side}
                  </span>
                  <span className={`tabular-nums ${
                    (trade.pnl_cents ?? 0) >= 0 ? 'text-terminal-amber' : 'text-terminal-red'
                  }`}>
                    {formatCents(trade.pnl_cents ?? 0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="text-center py-8 text-terminal-dim">
          NO DATA AVAILABLE
        </div>
      )}
    </Modal>
  );
}

interface StatBoxProps {
  label: string;
  value: string;
  color: 'green' | 'red' | 'amber' | 'cyan';
}

function StatBox({ label, value, color }: StatBoxProps): JSX.Element {
  const colorClass = {
    green: 'text-terminal-green-bright',
    red: 'text-terminal-red',
    amber: 'text-terminal-amber-bright',
    cyan: 'text-terminal-cyan',
  }[color];

  return (
    <div className="border border-terminal-green p-3 text-center">
      <div className="text-xs text-terminal-dim mb-1">{label}</div>
      <div className={`text-2xl font-bold ${colorClass}`}>{value}</div>
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: string; color: 'green' | 'red' }): JSX.Element {
  return (
    <div className="text-center">
      <div className="text-xs text-terminal-dim">{label}</div>
      <div className={`font-bold ${color === 'green' ? 'text-terminal-green' : 'text-terminal-red'}`}>
        {value}
      </div>
    </div>
  );
}

function getEmptyStats(): StrategyStats {
  return {
    totalTrades: 0,
    wins: 0,
    losses: 0,
    winRate: 0,
    totalPnl: 0,
    avgWin: 0,
    avgLoss: 0,
    bestTrade: 0,
    worstTrade: 0,
    currentStreak: 0,
    streakType: 'none',
    recentTrades: [],
    pnlHistory: [],
  };
}
