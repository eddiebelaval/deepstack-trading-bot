'use client';

import { useMemo, useRef, useEffect } from 'react';
import * as d3Scale from 'd3-scale';
import * as d3Interpolate from 'd3-interpolate';
import { formatStrategyName } from '@/lib/format';
import type { MarketReading } from '@/lib/weather-types';
import {
  BEAUFORT_SCALE, FRONT_TYPES, SOURCE_LABELS, ADVISORIES,
  computeBeaufort, computeAdvisory, isBootstrapReading,
} from '@/lib/weather-types';
import type { RegimePoint } from '@/lib/weather-types';

// ---------------------------------------------------------------------------
// D3 color scales (kept here — only needed for deep view rendering)
// ---------------------------------------------------------------------------

const pressureColorScale = d3Scale.scaleLinear<string>()
  .domain([0, 0.25, 0.5, 0.75, 1.0])
  .range(['#00FF41', '#39FF14', '#FFBF00', '#FF6600', '#FF0000'])
  .interpolate(d3Interpolate.interpolateRgb);

const temperatureColorScale = d3Scale.scaleLinear<string>()
  .domain([-1, -0.5, 0, 0.5, 1])
  .range(['#00FFFF', '#0088FF', '#888888', '#FF8800', '#FF0000'])
  .interpolate(d3Interpolate.interpolateRgb);

function colorToRGBA(color: string, alpha: number): string {
  const rgbMatch = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (rgbMatch) {
    return `rgba(${rgbMatch[1]},${rgbMatch[2]},${rgbMatch[3]},${alpha})`;
  }
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ---------------------------------------------------------------------------
// Canvas-based Radar Display
// ---------------------------------------------------------------------------

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

    const precipCount = Math.round(Math.abs(reading.volume_ratio - 1) * 300);
    const particles = Array.from({ length: Math.min(precipCount, 60) }, (_, i) => {
      const angle = (i * 137.508 * Math.PI) / 180;
      const dist = maxR * 0.2 + (i / 60) * maxR * 0.7;
      return { x: cx + Math.cos(angle) * dist, y: cy + Math.sin(angle) * dist };
    });

    const ringCount = Math.max(3, Math.min(8, beaufort + 2));

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, size, size);

      const bgGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, maxR);
      bgGrad.addColorStop(0, colorToRGBA(front.color, 0.08));
      bgGrad.addColorStop(0.5, colorToRGBA(front.color, 0.03));
      bgGrad.addColorStop(1, 'rgba(10,10,15,0.9)');
      ctx.beginPath();
      ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
      ctx.fillStyle = bgGrad;
      ctx.fill();

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

      ctx.strokeStyle = colorToRGBA(front.color, 0.07);
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy - maxR);
      ctx.lineTo(cx, cy + maxR);
      ctx.moveTo(cx - maxR, cy);
      ctx.lineTo(cx + maxR, cy);
      ctx.stroke();

      for (const p of particles) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1, 0, Math.PI * 2);
        ctx.fillStyle = colorToRGBA(front.color, 0.1 + Math.random() * 0.1);
        ctx.fill();
      }

      const sweepAngle = angleRef.current;
      const sweepWidth = Math.PI / 4;
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

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(
        cx + Math.cos(sweepAngle) * maxR * 0.9,
        cy + Math.sin(sweepAngle) * maxR * 0.9,
      );
      ctx.strokeStyle = colorToRGBA(front.color, 0.3);
      ctx.lineWidth = 1;
      ctx.stroke();

      if (Math.abs(reading.trend_strength) > 0.005) {
        const windAngle = reading.trend_strength > 0
          ? -Math.PI / 4 - reading.trend_strength * Math.PI / 4
          : Math.PI / 4 + Math.abs(reading.trend_strength) * Math.PI / 4;
        const windLen = Math.min(Math.abs(reading.trend_strength) * maxR * 2, maxR * 0.65);

        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(windAngle);
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(windLen, 0);
        ctx.strokeStyle = 'rgba(0,255,255,0.5)';
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(windLen, 0);
        ctx.lineTo(windLen - 6, -4);
        ctx.lineTo(windLen - 6, 4);
        ctx.closePath();
        ctx.fillStyle = 'rgba(0,255,255,0.5)';
        ctx.fill();
        if (Math.abs(reading.trend_strength) > 0.1) {
          ctx.beginPath();
          ctx.moveTo(windLen - 10, 0);
          ctx.lineTo(windLen - 16, reading.trend_strength > 0 ? -8 : 8);
          ctx.strokeStyle = 'rgba(0,255,255,0.4)';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        ctx.restore();
      }

      ctx.beginPath();
      ctx.arc(cx, cy, 16, 0, Math.PI * 2);
      ctx.fillStyle = '#0a0a0f';
      ctx.fill();
      ctx.strokeStyle = front.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.font = 'bold 13px "JetBrains Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = front.color;
      ctx.fillText(front.symbol, cx, cy + 1);

      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'top';
      ctx.fillStyle = colorToRGBA(front.color, 0.5);
      ctx.fillText(`F${beaufort}`, size - 8, 6);

      angleRef.current += 0.025;
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
// Station Readout
// ---------------------------------------------------------------------------

function StationReadout({ reading }: { reading: MarketReading }) {
  if (isBootstrapReading(reading)) {
    return (
      <div className="rounded border border-terminal-amber/15 bg-terminal-amber/5 px-2.5 py-2.5 space-y-1.5">
        <div className="text-[10px] font-bold tracking-[0.16em] text-terminal-amber">WARMING UP</div>
        <div className="text-[9px] text-terminal-dim/65 leading-relaxed">
          Awaiting enough snapshots to classify this source.
        </div>
      </div>
    );
  }

  const beaufort = computeBeaufort(reading.volatility, reading.trend_strength, reading.mean_reversion_score);
  const beaufortInfo = BEAUFORT_SCALE[beaufort];
  const pressure = (1 - reading.volatility) * 1013.25;
  const trendColor = temperatureColorScale(reading.trend_strength);

  const metrics = [
    { label: 'PRESSURE', value: pressure.toFixed(0), unit: 'hPa', tag: reading.volatility < 0.3 ? 'HIGH' : reading.volatility < 0.6 ? 'FALLING' : 'LOW', color: pressureColorScale(reading.volatility) },
    { label: 'WIND', value: (Math.abs(reading.trend_strength) * 100).toFixed(1), unit: 'kts', tag: reading.trend_strength > 0.01 ? 'N' : reading.trend_strength < -0.01 ? 'S' : 'CALM', color: trendColor },
    { label: 'SEA STATE', value: `F${beaufortInfo.label}`, unit: '', tag: beaufortInfo.seaState, color: pressureColorScale(beaufort / 12) },
    { label: 'VISIBILITY', value: (reading.confidence * 100).toFixed(0), unit: '%', tag: reading.confidence > 0.7 ? 'CLEAR' : reading.confidence > 0.4 ? 'HAZY' : 'FOG', color: reading.confidence > 0.7 ? '#00FF41' : reading.confidence > 0.4 ? '#FFBF00' : '#FF0000' },
  ];

  return (
    <div className="space-y-1.5">
      {metrics.map((m) => (
        <div key={m.label} className="flex items-center justify-between gap-2">
          <span className="text-[9px] text-terminal-dim/50 tracking-wider w-16 shrink-0">{m.label}</span>
          <span className="text-[10px] tabular-nums font-bold" style={{ color: m.color }}>{m.value}{m.unit && <span className="text-[7px] text-terminal-dim/30 ml-0.5">{m.unit}</span>}</span>
          <span className="text-[9px] text-terminal-dim/30 w-12 text-right truncate">{m.tag}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pressure Gauge
// ---------------------------------------------------------------------------

function PressureGauge({ value, label, min = 0, max = 1, title }: {
  value: number; label: string; min?: number; max?: number; title?: string;
}) {
  const normalized = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const color = pressureColorScale(normalized);

  return (
    <div className="flex items-center gap-2" title={title}>
      <span className="text-[7px] text-terminal-dim/40 w-8 shrink-0 tracking-wider">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-terminal-bg overflow-hidden relative">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${Math.max(normalized * 100, 2)}%`,
            background: `linear-gradient(90deg, ${pressureColorScale(0)}, ${color})`,
            boxShadow: `0 0 4px ${color}40`,
          }}
        />
      </div>
      <span className="text-[9px] tabular-nums w-10 text-right" style={{ color }}>{value.toFixed(3)}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WeatherMap — deep view (now prop-driven, rendered inside WeatherStatusBar)
// ---------------------------------------------------------------------------

interface WeatherMapProps {
  readings: MarketReading[];
  recentRegimes: RegimePoint[];
}

export default function WeatherMap({ readings, recentRegimes }: WeatherMapProps) {
  const advisory = useMemo(() => computeAdvisory(readings), [readings]);
  const advisoryInfo = ADVISORIES[advisory];

  const transitions = useMemo(() => {
    if (recentRegimes.length < 2) return [];
    const changes: { from: string; to: string; time: string }[] = [];
    for (let i = 1; i < recentRegimes.length; i++) {
      if (recentRegimes[i].regime !== recentRegimes[i - 1].regime) {
        changes.push({ from: recentRegimes[i - 1].regime, to: recentRegimes[i].regime, time: recentRegimes[i].timestamp });
      }
    }
    return changes.slice(-5);
  }, [recentRegimes]);

  if (readings.length === 0) return null;

  return (
    <div className="border-t border-terminal-green/10">
      {/* Advisory Banner */}
      <div
        className={`px-3 py-1.5 border-b text-center ${advisory !== 'ALL_CLEAR' ? 'animate-pulse' : ''}`}
        style={{ borderColor: advisoryInfo.borderColor, background: advisoryInfo.bgColor }}
      >
        <span className="text-[10px] font-bold tracking-[0.25em]" style={{ color: advisoryInfo.color, textShadow: advisoryInfo.glow }}>
          {advisoryInfo.label}
        </span>
      </div>

      {/* Radar Stations */}
      <div className="p-3">
        <div className={`grid gap-3 ${readings.length === 1 ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2'}`}>
          {readings.map((r, idx) => {
            const front = FRONT_TYPES[r.regime] ?? FRONT_TYPES.low_vol_calm;
            const bootstrap = isBootstrapReading(r);
            const accentColor = bootstrap ? '#FFBF00' : front.color;
            return (
              <div key={`${r.source}-${idx}`} className="bg-terminal-bg rounded-lg p-2.5 border" style={{ borderColor: `${accentColor}18` }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[9px] font-bold tracking-[0.15em]" style={{ color: accentColor }}>
                    {SOURCE_LABELS[r.source] ?? r.source.toUpperCase()}
                  </span>
                  <span className="text-[9px] text-terminal-dim/30 tabular-nums">
                    {bootstrap ? 'WARMUP' : `${r.num_markets_sampled.toLocaleString()} SRC`}
                  </span>
                </div>
                <div className="flex items-start gap-3">
                  <RadarCanvas reading={r} size={140} />
                  <div className="flex-1 min-w-0 pt-2">
                    <StationReadout reading={r} />
                  </div>
                </div>
                {!bootstrap && (
                  <div className="mt-2 pt-2 border-t space-y-1" style={{ borderColor: `${accentColor}10` }}>
                    <div className="text-[7px] text-terminal-dim/25 tracking-[0.15em] mb-0.5">RAW SIGNALS</div>
                    <PressureGauge value={r.volatility} label="VOL" title="Market volatility" />
                    <PressureGauge value={Math.abs(r.trend_strength)} label="TREND" title="Trend strength" />
                    <PressureGauge value={Math.abs(r.mean_reversion_score)} label="MR" title="Mean reversion" />
                    <PressureGauge value={Math.abs(r.volume_ratio - 1)} label="DVOL" max={0.2} title="Volume deviation" />
                  </div>
                )}
                <div className="flex items-center justify-between mt-2 pt-1.5 border-t" style={{ borderColor: `${accentColor}10` }}>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ background: accentColor, boxShadow: `0 0 4px ${accentColor}60` }} />
                    <span className="text-[9px] font-bold tracking-wider" style={{ color: accentColor }}>
                      {bootstrap ? 'INSUFFICIENT DATA' : front.label}
                    </span>
                  </div>
                  <span className="text-[9px] text-terminal-dim/25">
                    {bootstrap ? 'BOOTSTRAP' : formatStrategyName(r.regime)}
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
            <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-dim">FRONT MOVEMENT (24H)</span>
          </div>
          <div className="space-y-0.5">
            {transitions.map((t, i) => {
              const fromFront = FRONT_TYPES[t.from] ?? FRONT_TYPES.low_vol_calm;
              const toFront = FRONT_TYPES[t.to] ?? FRONT_TYPES.low_vol_calm;
              const time = new Date(t.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              return (
                <div key={i} className="flex items-center gap-2 text-[9px]">
                  <span className="text-terminal-dim/40 tabular-nums w-10">{time}</span>
                  <span className="w-3 h-3 rounded-full flex items-center justify-center text-[7px] font-bold" style={{ background: `${fromFront.color}20`, color: fromFront.color }}>{fromFront.symbol}</span>
                  <span className="text-terminal-dim/20">&rarr;</span>
                  <span className="w-3 h-3 rounded-full flex items-center justify-center text-[7px] font-bold" style={{ background: `${toFront.color}20`, color: toFront.color }}>{toFront.symbol}</span>
                  <span className="text-terminal-dim/25 truncate">{formatStrategyName(t.from)} &rarr; {formatStrategyName(t.to)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Beaufort Scale */}
      <div className="px-3 pb-2 border-t border-terminal-green/10">
        <div className="flex items-center gap-2 py-1.5">
          <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-dim">BEAUFORT SCALE</span>
        </div>
        <div className="flex gap-px">
          {BEAUFORT_SCALE.map((b, i) => {
            const isActive = readings.some((r) => computeBeaufort(r.volatility, r.trend_strength, r.mean_reversion_score) === i);
            const color = pressureColorScale(i / 12);
            return (
              <div key={i} className="flex-1 flex flex-col items-center" title={`F${b.label}: ${b.description} — ${b.seaState}`}>
                <div className="w-full h-2.5 rounded-sm transition-all duration-500" style={{ background: isActive ? color : `${color}33`, boxShadow: isActive ? `0 0 6px ${color}` : 'none', opacity: isActive ? 1 : 0.25 }} />
                <span className="text-[7px] tabular-nums mt-0.5" style={{ color: isActive ? color : 'rgba(255,255,255,0.15)' }}>{b.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
