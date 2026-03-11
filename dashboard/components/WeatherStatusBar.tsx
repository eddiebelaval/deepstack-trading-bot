'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatStrategyName } from '@/lib/format';
import type { MarketReading, RegimePoint, Anomaly } from '@/lib/weather-types';
import {
  FRONT_TYPES, SOURCE_LABELS, ADVISORIES,
  computeBeaufort, computeAdvisory, isBootstrapReading,
  BEAUFORT_SCALE, detectAnomalies,
} from '@/lib/weather-types';
import WeatherMap from './WeatherMap';

// ---------------------------------------------------------------------------
// Anomaly Alert Bar — renders only when anomalies exist
// ---------------------------------------------------------------------------

function AnomalyAlertBar({ anomalies }: { anomalies: Anomaly[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const visible = anomalies.filter((a) => !dismissed.has(a.id));
  if (visible.length === 0) return null;

  return (
    <div className="px-3 py-2 space-y-1.5 border-t border-terminal-amber/15 bg-terminal-amber/[0.02]">
      {visible.map((a) => (
        <div
          key={a.id}
          className="flex items-center gap-2 text-[9px]"
          style={{ borderLeft: `2px solid ${a.severity === 'red' ? '#FF0000' : '#FFBF00'}` }}
        >
          <span className="pl-2 flex-1" style={{ color: a.severity === 'red' ? '#FF3333' : '#FFBF00' }}>
            {a.message}
          </span>
          <button
            onClick={() => setDismissed((prev) => new Set(prev).add(a.id))}
            className="text-terminal-dim/30 hover:text-terminal-dim px-1"
          >
            x
          </button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Source Indicator — compact dot + label for the status bar
// ---------------------------------------------------------------------------

function SourceIndicator({ reading }: { reading: MarketReading }) {
  const front = FRONT_TYPES[reading.regime] ?? FRONT_TYPES.low_vol_calm;
  const bootstrap = isBootstrapReading(reading);
  const color = bootstrap ? '#FFBF00' : front.color;
  const label = SOURCE_LABELS[reading.source] ?? reading.source.toUpperCase();

  return (
    <div className="flex items-center gap-1.5">
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: color, boxShadow: `0 0 4px ${color}60` }}
        title={`${label}: ${formatStrategyName(reading.regime)} (${(reading.confidence * 100).toFixed(0)}% conf)`}
      />
      <span className="text-[9px] text-terminal-dim/60 tracking-wider hidden sm:inline">{label}</span>
      <span className="text-[9px] font-bold tracking-wider" style={{ color }}>
        {bootstrap ? 'WARMUP' : formatStrategyName(reading.regime)}
      </span>
      <span className="text-[9px] tabular-nums text-terminal-dim/40">
        {bootstrap ? '' : `${(reading.confidence * 100).toFixed(0)}%`}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WeatherStatusBar — the compact compound component
// ---------------------------------------------------------------------------

export default function WeatherStatusBar() {
  const [readings, setReadings] = useState<MarketReading[]>([]);
  const [recentRegimes, setRecentRegimes] = useState<RegimePoint[]>([]);
  const [expanded, setExpanded] = useState(false);
  const prevReadingsRef = useRef('');
  const prevRegimesRef = useRef('');

  const fetchData = useCallback(async () => {
    try {
      const [stateRes, regimeRes] = await Promise.all([
        fetch('/api/analytics?view=market_state'),
        fetch('/api/analytics?view=regime_timeline&days=1'),
      ]);
      if (stateRes.ok) {
        const d = await stateRes.json();
        const json = JSON.stringify(d.data || []);
        if (json !== prevReadingsRef.current) {
          prevReadingsRef.current = json;
          setReadings(d.data || []);
        }
      }
      if (regimeRes.ok) {
        const d = await regimeRes.json();
        const json = JSON.stringify(d.data || []);
        if (json !== prevRegimesRef.current) {
          prevRegimesRef.current = json;
          setRecentRegimes(d.data || []);
        }
      }
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const advisory = useMemo(() => computeAdvisory(readings), [readings]);
  const advisoryInfo = ADVISORIES[advisory];
  const anomalies = useMemo(() => detectAnomalies(readings, recentRegimes), [readings, recentRegimes]);
  const allBootstrap = useMemo(
    () => readings.length > 0 && readings.every((r) => isBootstrapReading(r)),
    [readings],
  );

  // Agreement summary
  const agreementSummary = useMemo(() => {
    const active = readings.filter((r) => !isBootstrapReading(r));
    if (active.length === 0) return null;
    if (active.length === 1) {
      return { text: 'Single source', color: 'text-terminal-dim/60' };
    }
    const regimes = new Set(active.map((r) => r.regime));
    if (regimes.size === 1) {
      return { text: 'SOURCES AGREE', color: 'text-terminal-green/70' };
    }
    return { text: 'SOURCES DIVERGE', color: 'text-terminal-red' };
  }, [readings]);

  // Beaufort from first active reading
  const beaufortInfo = useMemo(() => {
    const active = readings.filter((r) => !isBootstrapReading(r));
    if (active.length === 0) return null;
    const b = computeBeaufort(active[0].volatility, active[0].trend_strength, active[0].mean_reversion_score);
    return { scale: b, info: BEAUFORT_SCALE[b] };
  }, [readings]);

  if (readings.length === 0) {
    return (
      <div className="panel px-3 py-2">
        <div className="text-[10px] text-terminal-dim text-center">
          WEATHER SYSTEM INITIALIZING...
        </div>
      </div>
    );
  }

  return (
    <div className="panel overflow-visible">
      {/* Compact Status Bar */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-white/[0.01] transition-colors text-left"
      >
        {/* Source indicators */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3 flex-1 min-w-0">
          {readings.map((r, idx) => (
            <SourceIndicator key={`${r.source}-${idx}`} reading={r} />
          ))}
        </div>

        {/* Advisory badge */}
        <span
          className={`text-[9px] font-bold tracking-[0.15em] px-2 py-0.5 rounded border shrink-0 ${
            advisory !== 'ALL_CLEAR' && !allBootstrap ? 'animate-pulse' : ''
          }`}
          style={{
            color: allBootstrap ? '#FFBF00' : advisoryInfo.color,
            borderColor: allBootstrap ? 'rgba(255,191,0,0.3)' : advisoryInfo.borderColor,
            background: allBootstrap ? 'rgba(255,191,0,0.05)' : advisoryInfo.bgColor,
          }}
        >
          {allBootstrap ? 'WARMING UP' : advisoryInfo.label}
        </span>

        {/* Agreement + Beaufort */}
        <div className="flex items-center gap-2 shrink-0">
          {agreementSummary && (
            <span className={`text-[9px] tracking-wider ${agreementSummary.color}`}>
              {agreementSummary.text}
            </span>
          )}
          {beaufortInfo && (
            <span className="text-[9px] tabular-nums text-terminal-dim/40" title={`${beaufortInfo.info.description} — ${beaufortInfo.info.seaState}`}>
              F{beaufortInfo.scale}
            </span>
          )}
        </div>

        {/* Expand indicator */}
        <span
          className="text-[9px] text-terminal-dim/40 transition-transform duration-200 shrink-0"
          style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
        >
          v
        </span>
      </button>

      {/* Anomaly alerts */}
      <AnomalyAlertBar anomalies={anomalies} />

      {/* Expandable deep view */}
      {expanded && (
        <WeatherMap readings={readings} recentRegimes={recentRegimes} />
      )}
    </div>
  );
}
