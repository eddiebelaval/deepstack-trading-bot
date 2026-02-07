'use client';

import { useState, useEffect } from 'react';
import { BotConfig } from '@/lib/types';

interface RiskControlsProps {
  botConfig: BotConfig | null;
  onApply: (params: Record<string, unknown>) => void;
}

export default function RiskControls({ botConfig, onApply }: RiskControlsProps) {
  const [kellyFraction, setKellyFraction] = useState(0.5);
  const [maxPositionSize, setMaxPositionSize] = useState(50);
  const [dailyLossLimit, setDailyLossLimit] = useState(100);
  const [isDirty, setIsDirty] = useState(false);

  // Sync from bot config
  useEffect(() => {
    if (botConfig) {
      setKellyFraction(Number(botConfig.kelly_fraction));
      setMaxPositionSize(botConfig.max_position_size_cents / 100);
      setDailyLossLimit(botConfig.daily_loss_limit_cents / 100);
      setIsDirty(false);
    }
  }, [botConfig]);

  function handleApply() {
    onApply({
      kelly_fraction: kellyFraction,
      max_position_size: maxPositionSize,
      daily_loss_limit: dailyLossLimit,
    });
    setIsDirty(false);
  }

  function markDirty() {
    setIsDirty(true);
  }

  return (
    <div className="space-y-4">
      {/* Kelly Fraction */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase">
            Kelly Fraction
          </span>
          <span className="text-xs text-terminal-cyan font-mono tabular-nums">
            {(kellyFraction * 100).toFixed(0)}%
          </span>
        </div>
        <input
          type="range"
          min="10"
          max="100"
          value={kellyFraction * 100}
          onChange={(e) => { setKellyFraction(parseInt(e.target.value) / 100); markDirty(); }}
          className="w-full h-1.5 rounded-full appearance-none cursor-pointer
            bg-terminal-bg-panel border border-terminal-green/20
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:bg-terminal-cyan
            [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(0,255,255,0.5)]"
        />
        <div className="flex justify-between text-[9px] text-terminal-dim/40 mt-0.5">
          <span>10%</span>
          <span>100%</span>
        </div>
      </div>

      {/* Max Position Size */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase">
            Max Position
          </span>
          <span className="text-xs text-terminal-green font-mono tabular-nums">
            ${maxPositionSize}
          </span>
        </div>
        <input
          type="range"
          min="1"
          max="500"
          step="1"
          value={maxPositionSize}
          onChange={(e) => { setMaxPositionSize(parseInt(e.target.value)); markDirty(); }}
          className="w-full h-1.5 rounded-full appearance-none cursor-pointer
            bg-terminal-bg-panel border border-terminal-green/20
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:bg-terminal-green
            [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(0,255,65,0.5)]"
        />
        <div className="flex justify-between text-[9px] text-terminal-dim/40 mt-0.5">
          <span>$1</span>
          <span>$500</span>
        </div>
      </div>

      {/* Daily Loss Limit */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase">
            Daily Loss Limit
          </span>
          <span className="text-xs text-terminal-red font-mono tabular-nums">
            ${dailyLossLimit}
          </span>
        </div>
        <input
          type="range"
          min="10"
          max="1000"
          step="10"
          value={dailyLossLimit}
          onChange={(e) => { setDailyLossLimit(parseInt(e.target.value)); markDirty(); }}
          className="w-full h-1.5 rounded-full appearance-none cursor-pointer
            bg-terminal-bg-panel border border-terminal-green/20
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:bg-terminal-red
            [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(255,50,50,0.5)]"
        />
        <div className="flex justify-between text-[9px] text-terminal-dim/40 mt-0.5">
          <span>$10</span>
          <span>$1000</span>
        </div>
      </div>

      {/* Apply Button */}
      <button
        onClick={handleApply}
        disabled={!isDirty}
        className={`w-full py-2 px-3 text-xs font-bold border rounded-md transition-all duration-200 ${
          isDirty
            ? 'border-terminal-amber text-terminal-amber hover:bg-terminal-amber/15 hover:shadow-[0_0_12px_rgba(255,191,0,0.2)]'
            : 'border-terminal-dim/20 text-terminal-dim/40 cursor-not-allowed'
        }`}
      >
        {isDirty ? 'APPLY CHANGES' : 'NO CHANGES'}
      </button>
    </div>
  );
}
