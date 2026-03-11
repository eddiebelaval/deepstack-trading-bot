'use client';

import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import * as d3Scale from 'd3-scale';
import * as d3Interpolate from 'd3-interpolate';
import { formatStrategyName } from '@/lib/format';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MarketReading {
  source: string;
  regime: string;
  confidence: number;
  volatility: number;
  trend_strength: number;
  mean_reversion_score: number;
  volume_ratio: number;
  num_markets_sampled: number;
  timestamp: string;
}

interface RegimePoint {
  id: number;
  regime: string;
  confidence: number;
  timestamp: string;
  volatility: number;
  trend_strength: number;
  source: string;
}

// ---------------------------------------------------------------------------
// Weather Mapping Constants
// ---------------------------------------------------------------------------

const BEAUFORT_SCALE: { max: number; label: string; description: string; seaState: string }[] = [
  { max: 0.05, label: '0', description: 'CALM', seaState: 'Glassy' },
  { max: 0.1,  label: '1', description: 'LIGHT AIR', seaState: 'Rippled' },
  { max: 0.15, label: '2', description: 'LIGHT BREEZE', seaState: 'Small wavelets' },
  { max: 0.25, label: '3', description: 'GENTLE BREEZE', seaState: 'Large wavelets' },
  { max: 0.35, label: '4', description: 'MODERATE', seaState: 'Small waves' },
  { max: 0.45, label: '5', description: 'FRESH BREEZE', seaState: 'Moderate waves' },
  { max: 0.55, label: '6', description: 'STRONG BREEZE', seaState: 'Large waves' },
  { max: 0.65, label: '7', description: 'HIGH WIND', seaState: 'Sea heaps up' },
  { max: 0.75, label: '8', description: 'GALE', seaState: 'Mod. high waves' },
  { max: 0.85, label: '9', description: 'STRONG GALE', seaState: 'High waves' },
  { max: 0.92, label: '10', description: 'STORM', seaState: 'Very high waves' },
  { max: 0.97, label: '11', description: 'VIOLENT STORM', seaState: 'Exceptionally high' },
  { max: 1.01, label: '12', description: 'HURRICANE', seaState: 'Catastrophic' },
];

type AdvisoryLevel = 'ALL_CLEAR' | 'SMALL_CRAFT' | 'GALE_WARNING' | 'STORM_WARNING';

interface Advisory {
  level: AdvisoryLevel;
  label: string;
  color: string;
  glow: string;
  borderColor: string;
  bgColor: string;
}

const ADVISORIES: Record<AdvisoryLevel, Advisory> = {
  ALL_CLEAR: {
    level: 'ALL_CLEAR', label: 'ALL CLEAR',
    color: '#00FF41', glow: '0 0 8px rgba(0,255,65,0.4)',
    borderColor: 'rgba(0,255,65,0.3)', bgColor: 'rgba(0,255,65,0.05)',
  },
  SMALL_CRAFT: {
    level: 'SMALL_CRAFT', label: 'SMALL CRAFT ADVISORY',
    color: '#FFBF00', glow: '0 0 8px rgba(255,191,0,0.4)',
    borderColor: 'rgba(255,191,0,0.3)', bgColor: 'rgba(255,191,0,0.05)',
  },
  GALE_WARNING: {
    level: 'GALE_WARNING', label: 'GALE WARNING',
    color: '#FF0000', glow: '0 0 8px rgba(255,0,0,0.4)',
    borderColor: 'rgba(255,0,0,0.3)', bgColor: 'rgba(255,0,0,0.05)',
  },
  STORM_WARNING: {
    level: 'STORM_WARNING', label: 'STORM WARNING',
    color: '#FF3333', glow: '0 0 12px rgba(255,0,0,0.6)',
    borderColor: 'rgba(255,0,0,0.5)', bgColor: 'rgba(255,0,0,0.1)',
  },
};

const FRONT_TYPES: Record<string, { label: string; color: string; symbol: string }> = {
  trending_up:    { label: 'WARM FRONT', color: '#FF4444', symbol: 'W' },
  trending_down:  { label: 'COLD FRONT', color: '#00FFFF', symbol: 'C' },
  mean_reverting: { label: 'STATIONARY', color: '#FFBF00', symbol: 'S' },
  high_vol_choppy:{ label: 'OCCLUDED', color: '#a855f7', symbol: 'O' },
  low_vol_calm:   { label: 'HIGH PRESSURE', color: '#00FF41', symbol: 'H' },
};

const SOURCE_LABELS: Record<string, string> = {
  prediction_market: 'PREDICTION MKTS',
  stock: 'EQUITIES',
};

// D3 color scales for NOAA-style weather coloring
const pressureColorScale = d3Scale.scaleLinear<string>()
  .domain([0, 0.25, 0.5, 0.75, 1.0])
  .range(['#00FF41', '#39FF14', '#FFBF00', '#FF6600', '#FF0000'])
  .interpolate(d3Interpolate.interpolateRgb);

const temperatureColorScale = d3Scale.scaleLinear<string>()
  .domain([-1, -0.5, 0, 0.5, 1])
  .range(['#00FFFF', '#0088FF', '#888888', '#FF8800', '#FF0000'])
  .interpolate(d3Interpolate.interpolateRgb);

// ---------------------------------------------------------------------------
// Derived computations
// ---------------------------------------------------------------------------

function computeBeaufort(volatility: number, trendStrength: number, mrScore: number): number {
  const composite = volatility * 0.5 + Math.abs(trendStrength) * 0.25 + Math.abs(mrScore) * 0.25;
  const idx = BEAUFORT_SCALE.findIndex((b) => composite <= b.max);
  return idx >= 0 ? idx : 12;
}

function computeAdvisory(readings: MarketReading[]): AdvisoryLevel {
  if (readings.length === 0) return 'ALL_CLEAR';
  const maxVol = Math.max(...readings.map((r) => r.volatility));
  const maxTrend = Math.max(...readings.map((r) => Math.abs(r.trend_strength)));
  const avgConfidence = readings.reduce((s, r) => s + r.confidence, 0) / readings.length;
  if (maxVol > 0.85 || (maxVol > 0.7 && avgConfidence < 0.3)) return 'STORM_WARNING';
  if (maxVol > 0.65 || (maxTrend > 0.4 && maxVol > 0.4)) return 'GALE_WARNING';
  if (maxVol > 0.35 || maxTrend > 0.25) return 'SMALL_CRAFT';
  return 'ALL_CLEAR';
}

// ---------------------------------------------------------------------------
// Canvas-based Radar Display (animated sweep + contour rings)
// ---------------------------------------------------------------------------

function colorToRGBA(color: string, alpha: number): string {
  // Handle both hex (#RRGGBB) and D3's rgb(R, G, B) format
  const rgbMatch = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (rgbMatch) {
    return `rgba(${rgbMatch[1]},${rgbMatch[2]},${rgbMatch[3]},${alpha})`;
  }
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function RadarCanvas({ reading, size = 160 }: { reading: MarketReading; size?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const angleRef = useRef(0);
  const front = FRONT_TYPES[reading.regime] ?? FRONT_TYPES.low_vol_calm;
  const beaufort = computeBeaufort(reading.volatility, reading.trend_strength, reading.mean_reversion_score);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const maxR = size / 2 - 6;

    // Precompute precipitation particle positions (golden angle spiral)
    const precipCount = Math.round(Math.abs(reading.volume_ratio - 1) * 300);
    const particles = Array.from({ length: Math.min(precipCount, 60) }, (_, i) => {
      const angle = (i * 137.508 * Math.PI) / 180;
      const dist = maxR * 0.2 + (i / 60) * maxR * 0.7;
      return { x: cx + Math.cos(angle) * dist, y: cy + Math.sin(angle) * dist };
    });

    // Number of isobar rings — more = higher pressure gradient (stormier)
    const ringCount = Math.max(3, Math.min(8, beaufort + 2));

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, size, size);

      // Background: radial pressure gradient
      const bgGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, maxR);
      bgGrad.addColorStop(0, colorToRGBA(front.color, 0.08));
      bgGrad.addColorStop(0.5, colorToRGBA(front.color, 0.03));
      bgGrad.addColorStop(1, 'rgba(10,10,15,0.9)');
      ctx.beginPath();
      ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
      ctx.fillStyle = bgGrad;
      ctx.fill();

      // Isobar contour rings with pressure coloring
      for (let i = 1; i <= ringCount; i++) {
        const t = i / ringCount;
        const r = maxR * t * 0.95;
        const ringColor = pressureColorScale(reading.volatility * t);
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.strokeStyle = colorToRGBA(ringColor, 0.12 + t * 0.08);
        ctx.lineWidth = i === ringCount ? 1.2 : 0.6;
        ctx.setLineDash(i % 2 === 0 ? [3, 4] : []);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Crosshairs
      ctx.strokeStyle = colorToRGBA(front.color, 0.07);
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy - maxR);
      ctx.lineTo(cx, cy + maxR);
      ctx.moveTo(cx - maxR, cy);
      ctx.lineTo(cx + maxR, cy);
      ctx.stroke();

      // Precipitation scatter
      for (const p of particles) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1, 0, Math.PI * 2);
        ctx.fillStyle = colorToRGBA(front.color, 0.1 + Math.random() * 0.1);
        ctx.fill();
      }

      // Animated radar sweep — cone/wedge
      const sweepAngle = angleRef.current;
      const sweepWidth = Math.PI / 4; // 45 degree cone

      const sweepGrad = ctx.createConicGradient(sweepAngle - sweepWidth, cx, cy);
      sweepGrad.addColorStop(0, 'rgba(0,0,0,0)');
      sweepGrad.addColorStop(0.5, colorToRGBA(front.color, 0.12));
      sweepGrad.addColorStop(1, 'rgba(0,0,0,0)');

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, maxR * 0.95, sweepAngle - sweepWidth, sweepAngle);
      ctx.closePath();
      ctx.fillStyle = sweepGrad;
      ctx.fill();

      // Sweep leading edge line
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(
        cx + Math.cos(sweepAngle) * maxR * 0.9,
        cy + Math.sin(sweepAngle) * maxR * 0.9,
      );
      ctx.strokeStyle = colorToRGBA(front.color, 0.3);
      ctx.lineWidth = 1;
      ctx.stroke();

      // Wind barb / trend arrow
      if (Math.abs(reading.trend_strength) > 0.005) {
        const windAngle = reading.trend_strength > 0
          ? -Math.PI / 4 - reading.trend_strength * Math.PI / 4
          : Math.PI / 4 + Math.abs(reading.trend_strength) * Math.PI / 4;
        const windLen = Math.min(Math.abs(reading.trend_strength) * maxR * 2, maxR * 0.65);

        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(windAngle);

        // Arrow shaft
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(windLen, 0);
        ctx.strokeStyle = 'rgba(0,255,255,0.5)';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Arrow head
        ctx.beginPath();
        ctx.moveTo(windLen, 0);
        ctx.lineTo(windLen - 6, -4);
        ctx.lineTo(windLen - 6, 4);
        ctx.closePath();
        ctx.fillStyle = 'rgba(0,255,255,0.5)';
        ctx.fill();

        // Wind barbs for strong trends
        if (Math.abs(reading.trend_strength) > 0.1) {
          ctx.beginPath();
          ctx.moveTo(windLen - 10, 0);
          ctx.lineTo(windLen - 16, reading.trend_strength > 0 ? -8 : 8);
          ctx.strokeStyle = 'rgba(0,255,255,0.4)';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        if (Math.abs(reading.trend_strength) > 0.3) {
          ctx.beginPath();
          ctx.moveTo(windLen - 18, 0);
          ctx.lineTo(windLen - 24, reading.trend_strength > 0 ? -8 : 8);
          ctx.stroke();
        }

        ctx.restore();
      }

      // Center station model
      ctx.beginPath();
      ctx.arc(cx, cy, 16, 0, Math.PI * 2);
      ctx.fillStyle = '#0a0a0f';
      ctx.fill();
      ctx.strokeStyle = front.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Station symbol
      ctx.font = 'bold 13px "JetBrains Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = front.color;
      ctx.fillText(front.symbol, cx, cy + 1);

      // Beaufort label — top right
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'top';
      ctx.fillStyle = colorToRGBA(front.color, 0.5);
      ctx.fillText(`F${beaufort}`, size - 8, 6);

      // Advance sweep angle
      angleRef.current += 0.025; // ~4s full rotation
      animRef.current = requestAnimationFrame(draw);
    }

    draw();
    return () => cancelAnimationFrame(animRef.current);
  }, [reading, size, front, beaufort]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      style={{ width: size, height: size }}
      className="shrink-0"
    />
  );
}

// ---------------------------------------------------------------------------
// Station Readout — NOAA weather station style metrics
// ---------------------------------------------------------------------------

function StationReadout({ reading }: { reading: MarketReading }) {
  const beaufort = computeBeaufort(reading.volatility, reading.trend_strength, reading.mean_reversion_score);
  const beaufortInfo = BEAUFORT_SCALE[beaufort];

  // Map market data to weather metaphors
  const pressure = (1 - reading.volatility) * 1013.25; // hPa — inverted volatility
  const trendColor = temperatureColorScale(reading.trend_strength);

  const metrics = [
    {
      label: 'PRESSURE',
      subtitle: 'volatility',
      value: pressure.toFixed(0),
      unit: 'hPa',
      tag: reading.volatility < 0.3 ? 'HIGH' : reading.volatility < 0.6 ? 'FALLING' : 'LOW',
      color: pressureColorScale(reading.volatility),
    },
    {
      label: 'WIND',
      subtitle: 'trend',
      value: (Math.abs(reading.trend_strength) * 100).toFixed(1),
      unit: 'kts',
      tag: reading.trend_strength > 0.01 ? 'N' : reading.trend_strength < -0.01 ? 'S' : 'CALM',
      color: trendColor,
    },
    {
      label: 'SEA STATE',
      subtitle: 'intensity',
      value: `F${beaufortInfo.label}`,
      unit: '',
      tag: beaufortInfo.seaState,
      color: pressureColorScale(beaufort / 12),
    },
    {
      label: 'VISIBILITY',
      subtitle: 'confidence',
      value: (reading.confidence * 100).toFixed(0),
      unit: '%',
      tag: reading.confidence > 0.7 ? 'CLEAR' : reading.confidence > 0.4 ? 'HAZY' : 'FOG',
      color: reading.confidence > 0.7 ? '#00FF41' : reading.confidence > 0.4 ? '#FFBF00' : '#FF0000',
    },
  ];

  return (
    <div className="space-y-1.5">
      {metrics.map((m) => (
        <div key={m.label} className="flex items-center justify-between gap-2">
          <div className="w-16 shrink-0">
            <div className="text-[9px] text-terminal-dim/50 tracking-wider leading-tight">
              {m.label}
            </div>
            <div className="text-[6px] text-terminal-dim/25 tracking-wider leading-tight">
              {m.subtitle}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] tabular-nums font-bold" style={{ color: m.color }}>
              {m.value}
            </span>
            {m.unit && (
              <span className="text-[7px] text-terminal-dim/30">{m.unit}</span>
            )}
          </div>
          <span className="text-[9px] text-terminal-dim/30 w-12 text-right truncate">
            {m.tag}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pressure Gauge — mini horizontal bar with D3 color interpolation
// ---------------------------------------------------------------------------

function PressureGauge({ value, label, min = 0, max = 1, title }: {
  value: number;
  label: string;
  min?: number;
  max?: number;
  title?: string;
}) {
  const normalized = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const color = pressureColorScale(normalized);

  return (
    <div className="flex items-center gap-2" title={title}>
      <span className="text-[7px] text-terminal-dim/40 w-8 shrink-0 tracking-wider">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-terminal-bg overflow-hidden relative">
        {/* Gradient fill */}
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${Math.max(normalized * 100, 2)}%`,
            background: `linear-gradient(90deg, ${pressureColorScale(0)}, ${color})`,
            boxShadow: `0 0 4px ${color}40`,
          }}
        />
      </div>
      <span className="text-[9px] tabular-nums w-10 text-right" style={{ color }}>
        {value.toFixed(3)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Weather Map Component
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Legend / How to Read — collapsible explainer
// ---------------------------------------------------------------------------

function WeatherLegend() {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-terminal-green/10">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left px-3 py-1.5"
      >
        <span
          className="text-[9px] text-terminal-dim transition-transform duration-200"
          style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
        >
          &gt;
        </span>
        <span className="text-[9px] tracking-[0.2em] text-terminal-dim/60">
          HOW TO READ THIS MAP
        </span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 space-y-3">
          {/* Translation table */}
          <div className="space-y-1">
            <div className="text-[9px] font-bold tracking-[0.15em] text-terminal-green/60 mb-1.5">
              WEATHER &rarr; MARKET TRANSLATION
            </div>
            {[
              { weather: 'PRESSURE', market: 'Volatility (inverted)', detail: 'High pressure = calm markets. Low pressure = volatile/stormy.' },
              { weather: 'WIND', market: 'Trend Strength', detail: 'Wind speed = how strong the directional trend is. N = bullish, S = bearish.' },
              { weather: 'SEA STATE', market: 'Beaufort Scale (0-12)', detail: 'Composite intensity score. F0 = glassy calm, F12 = hurricane-level chaos.' },
              { weather: 'VISIBILITY', market: 'Model Confidence', detail: 'How certain the regime classifier is. Fog = low confidence, Clear = high.' },
            ].map((row) => (
              <div key={row.weather} className="flex gap-2 text-[9px]">
                <span className="text-terminal-green w-16 shrink-0 font-bold">{row.weather}</span>
                <span className="text-terminal-dim/40">=</span>
                <div className="flex-1 min-w-0">
                  <span className="text-terminal-dim/70">{row.market}</span>
                  <span className="text-terminal-dim/30 ml-1.5">
                    {row.detail}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Front types */}
          <div className="space-y-1">
            <div className="text-[9px] font-bold tracking-[0.15em] text-terminal-green/60 mb-1.5">
              FRONT TYPES (RADAR CENTER SYMBOL)
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-1">
              {Object.entries(FRONT_TYPES).map(([regime, info]) => (
                <div key={regime} className="flex items-center gap-1.5 text-[9px]">
                  <span
                    className="w-3.5 h-3.5 rounded-full flex items-center justify-center text-[7px] font-bold shrink-0"
                    style={{ background: `${info.color}20`, color: info.color }}
                  >
                    {info.symbol}
                  </span>
                  <span className="text-terminal-dim/50">{info.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Advisory levels */}
          <div className="space-y-1">
            <div className="text-[9px] font-bold tracking-[0.15em] text-terminal-green/60 mb-1.5">
              ADVISORY LEVELS
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {[
                { label: 'ALL CLEAR', color: '#00FF41', meaning: 'Low risk, full trading' },
                { label: 'SMALL CRAFT', color: '#FFBF00', meaning: 'Moderate — reduce size' },
                { label: 'GALE WARNING', color: '#FF0000', meaning: 'High vol — defensive only' },
                { label: 'STORM WARNING', color: '#FF3333', meaning: 'Extreme — halt trading' },
              ].map((adv) => (
                <div key={adv.label} className="flex items-center gap-1.5 text-[9px]">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ background: adv.color, boxShadow: `0 0 3px ${adv.color}60` }}
                  />
                  <span style={{ color: adv.color }} className="font-bold shrink-0">{adv.label}</span>
                  <span className="text-terminal-dim/30 truncate">{adv.meaning}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Radar reading guide */}
          <div className="text-[9px] text-terminal-dim/30 border-t border-terminal-green/5 pt-2">
            <span className="text-terminal-dim/50 font-bold">READING THE RADAR:</span>{' '}
            Rings = pressure contours (tighter = more volatile). Cyan arrow = trend direction &amp; strength. Scatter dots = volume deviation. Center symbol = current regime classification.
          </div>
        </div>
      )}
    </div>
  );
}

export default function WeatherMap() {
  const [readings, setReadings] = useState<MarketReading[]>([]);
  const [recentRegimes, setRecentRegimes] = useState<RegimePoint[]>([]);

  const fetchData = useCallback(async () => {
    try {
      const [stateRes, regimeRes] = await Promise.all([
        fetch('/api/analytics?view=market_state'),
        fetch('/api/analytics?view=regime_timeline&days=1'),
      ]);
      if (stateRes.ok) {
        const d = await stateRes.json();
        setReadings(d.data || []);
      }
      if (regimeRes.ok) {
        const d = await regimeRes.json();
        setRecentRegimes(d.data || []);
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

  // Regime transitions in last 24h
  const transitions = useMemo(() => {
    if (recentRegimes.length < 2) return [];
    const changes: { from: string; to: string; time: string }[] = [];
    for (let i = 1; i < recentRegimes.length; i++) {
      if (recentRegimes[i].regime !== recentRegimes[i - 1].regime) {
        changes.push({
          from: recentRegimes[i - 1].regime,
          to: recentRegimes[i].regime,
          time: recentRegimes[i].timestamp,
        });
      }
    }
    return changes.slice(-5);
  }, [recentRegimes]);

  if (readings.length === 0) {
    return (
      <div className="panel p-4">
        <div className="text-[10px] text-terminal-dim text-center">
          WEATHER SYSTEM INITIALIZING...
        </div>
      </div>
    );
  }

  return (
    <div className="panel overflow-visible">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
            MARKET WEATHER SYSTEM
          </span>
          <span className="text-[9px] text-terminal-dim/40">NWS / DAE</span>
        </div>
        <span className="text-[9px] text-terminal-dim/40 tabular-nums">
          UPD {new Date(readings[0]?.timestamp || '').toLocaleTimeString([], {
            hour: '2-digit', minute: '2-digit',
          })}
        </span>
      </div>

      {/* Advisory Banner */}
      <div
        className={`px-3 py-1.5 border-b text-center ${
          advisory !== 'ALL_CLEAR' ? 'animate-pulse' : ''
        }`}
        style={{
          borderColor: advisoryInfo.borderColor,
          background: advisoryInfo.bgColor,
        }}
      >
        <span
          className="text-[10px] font-bold tracking-[0.25em]"
          style={{ color: advisoryInfo.color, textShadow: advisoryInfo.glow }}
        >
          {advisoryInfo.label}
        </span>
      </div>

      {/* How to Read legend */}
      <WeatherLegend />

      {/* Radar Stations */}
      <div className="p-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {readings.map((r) => {
            const front = FRONT_TYPES[r.regime] ?? FRONT_TYPES.low_vol_calm;
            return (
              <div
                key={r.source}
                className="bg-terminal-bg rounded-lg p-2.5 border"
                style={{ borderColor: `${front.color}18` }}
              >
                {/* Source header */}
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[9px] font-bold tracking-[0.15em]" style={{ color: front.color }}>
                    {SOURCE_LABELS[r.source] ?? r.source.toUpperCase()}
                  </span>
                  <span className="text-[9px] text-terminal-dim/30 tabular-nums">
                    {r.num_markets_sampled.toLocaleString()} SRC
                  </span>
                </div>

                {/* Radar + Readout */}
                <div className="flex items-start gap-3">
                  <RadarCanvas reading={r} size={140} />
                  <div className="flex-1 min-w-0 pt-2">
                    <StationReadout reading={r} />
                  </div>
                </div>

                {/* Raw indicator gauges */}
                <div className="mt-2 pt-2 border-t space-y-1" style={{ borderColor: `${front.color}10` }}>
                  <div className="text-[7px] text-terminal-dim/25 tracking-[0.15em] mb-0.5">
                    RAW SIGNALS
                  </div>
                  <PressureGauge value={r.volatility} label="VOL" title="Market volatility — drives pressure reading" />
                  <PressureGauge value={Math.abs(r.trend_strength)} label="TREND" title="Directional trend strength — drives wind speed" />
                  <PressureGauge value={Math.abs(r.mean_reversion_score)} label="MR" title="Mean reversion score — tendency to snap back" />
                  <PressureGauge value={Math.abs(r.volume_ratio - 1)} label="DVOL" max={0.2} title="Volume deviation from normal — drives precipitation" />
                </div>

                {/* Front type footer */}
                <div className="flex items-center justify-between mt-2 pt-1.5 border-t" style={{ borderColor: `${front.color}10` }}>
                  <div className="flex items-center gap-1.5">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ background: front.color, boxShadow: `0 0 4px ${front.color}60` }}
                    />
                    <span className="text-[9px] font-bold tracking-wider" style={{ color: front.color }}>
                      {front.label}
                    </span>
                  </div>
                  <span className="text-[9px] text-terminal-dim/25">
                    {formatStrategyName(r.regime)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Front Movement Log */}
      {transitions.length > 0 && (
        <div className="px-3 pb-2 border-t border-terminal-green/10">
          <div className="flex items-center gap-2 py-1.5">
            <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-dim">
              FRONT MOVEMENT (24H)
            </span>
          </div>
          <div className="space-y-0.5">
            {transitions.map((t, i) => {
              const fromFront = FRONT_TYPES[t.from] ?? FRONT_TYPES.low_vol_calm;
              const toFront = FRONT_TYPES[t.to] ?? FRONT_TYPES.low_vol_calm;
              const time = new Date(t.time).toLocaleTimeString([], {
                hour: '2-digit', minute: '2-digit',
              });
              return (
                <div key={i} className="flex items-center gap-2 text-[9px]">
                  <span className="text-terminal-dim/40 tabular-nums w-10">{time}</span>
                  <span
                    className="w-3 h-3 rounded-full flex items-center justify-center text-[7px] font-bold"
                    style={{ background: `${fromFront.color}20`, color: fromFront.color }}
                  >
                    {fromFront.symbol}
                  </span>
                  <span className="text-terminal-dim/20">&rarr;</span>
                  <span
                    className="w-3 h-3 rounded-full flex items-center justify-center text-[7px] font-bold"
                    style={{ background: `${toFront.color}20`, color: toFront.color }}
                  >
                    {toFront.symbol}
                  </span>
                  <span className="text-terminal-dim/25 truncate">
                    {formatStrategyName(t.from)} &rarr; {formatStrategyName(t.to)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Beaufort Scale Legend */}
      <div className="px-3 pb-2 border-t border-terminal-green/10">
        <div className="flex items-center gap-2 py-1.5">
          <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-dim">
            BEAUFORT SCALE
          </span>
        </div>
        <div className="flex gap-px">
          {BEAUFORT_SCALE.map((b, i) => {
            const isActive = readings.some((r) => {
              return computeBeaufort(r.volatility, r.trend_strength, r.mean_reversion_score) === i;
            });
            const color = pressureColorScale(i / 12);
            return (
              <div
                key={i}
                className="flex-1 flex flex-col items-center"
                title={`F${b.label}: ${b.description} — ${b.seaState}`}
              >
                <div
                  className="w-full h-2.5 rounded-sm transition-all duration-500"
                  style={{
                    background: isActive ? color : `${color}33`,
                    boxShadow: isActive ? `0 0 6px ${color}` : 'none',
                    opacity: isActive ? 1 : 0.25,
                  }}
                />
                <span
                  className="text-[7px] tabular-nums mt-0.5"
                  style={{
                    color: isActive ? color : 'rgba(255,255,255,0.15)',
                  }}
                >
                  {b.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
