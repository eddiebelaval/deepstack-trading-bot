'use client';

import { useState, useEffect } from 'react';
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts';
import { Candlestick } from '@/lib/types';

interface CandlestickChartProps {
  ticker: string;
  series: string;
}

interface ChartCandle {
  time: string;
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  // For bar chart rendering: [low, high] as the bar range
  range: [number, number];
  body: [number, number];
  bullish: boolean;
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Custom candlestick shape — renders the wick (high-low line) and body (open-close rectangle)
function CandleShape(props: Record<string, unknown>) {
  const { x, y, width, height, payload } = props as {
    x: number;
    y: number;
    width: number;
    height: number;
    payload: ChartCandle;
  };
  if (!payload) return null;

  const bullish = payload.bullish;
  const color = bullish ? '#22c55e' : '#ef4444';
  const midX = x + width / 2;

  // The bar already represents the body (open-close range)
  // We need to draw the wick (high-low) as a thin line extending beyond
  const bodyTop = y;
  const bodyBottom = y + height;

  return (
    <g>
      {/* Wick line — from high to low */}
      <line
        x1={midX}
        y1={bodyTop - 2}
        x2={midX}
        y2={bodyBottom + 2}
        stroke={color}
        strokeWidth={1}
      />
      {/* Body rectangle */}
      <rect
        x={x + 1}
        y={y}
        width={Math.max(width - 2, 2)}
        height={Math.max(height, 1)}
        fill={bullish ? color : color}
        fillOpacity={bullish ? 0.8 : 0.6}
        stroke={color}
        strokeWidth={0.5}
      />
    </g>
  );
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: ChartCandle }> }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-black/90 border border-terminal-green/40 rounded px-3 py-2 text-[10px] font-mono">
      <div className="text-terminal-dim mb-1">{d.time}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <span className="text-terminal-dim">O:</span><span className="text-terminal-green">{d.open}c</span>
        <span className="text-terminal-dim">H:</span><span className="text-terminal-green">{d.high}c</span>
        <span className="text-terminal-dim">L:</span><span className="text-terminal-green">{d.low}c</span>
        <span className="text-terminal-dim">C:</span><span className={d.bullish ? 'text-green-400' : 'text-red-400'}>{d.close}c</span>
        <span className="text-terminal-dim">VOL:</span><span className="text-terminal-green">{d.volume.toLocaleString()}</span>
      </div>
    </div>
  );
}

export default function CandlestickChart({ ticker, series }: CandlestickChartProps) {
  const [candles, setCandles] = useState<ChartCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<number>(60);

  useEffect(() => {
    if (!ticker || !series) return;

    setLoading(true);
    const hours = period === 1 ? 4 : period === 60 ? 48 : 168;

    fetch(`/api/candlesticks?ticker=${ticker}&series=${series}&period=${period}&hours=${hours}`)
      .then(r => r.json())
      .then(data => {
        const raw: Candlestick[] = data.candlesticks || [];
        setCandles(
          raw.map(c => {
            const bullish = c.close >= c.open;
            return {
              time: formatTime(c.end_period_ts),
              ts: c.end_period_ts,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
              volume: c.volume,
              range: [c.low, c.high],
              body: bullish ? [c.open, c.close] : [c.close, c.open],
              bullish,
            };
          })
        );
      })
      .catch(() => setCandles([]))
      .finally(() => setLoading(false));
  }, [ticker, series, period]);

  if (loading) {
    return (
      <div className="h-48 flex items-center justify-center text-terminal-dim text-xs font-mono">
        LOADING CHART DATA...
      </div>
    );
  }

  if (candles.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center text-terminal-dim text-xs font-mono">
        NO CHART DATA AVAILABLE
      </div>
    );
  }

  const minPrice = Math.max(0, Math.min(...candles.map(c => c.low)) - 2);
  const maxPrice = Math.min(100, Math.max(...candles.map(c => c.high)) + 2);

  return (
    <div>
      {/* Period selector */}
      <div className="flex gap-2 mb-2">
        {[
          { value: 1, label: '1M' },
          { value: 60, label: '1H' },
          { value: 1440, label: '1D' },
        ].map(p => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`px-2 py-0.5 text-[10px] font-mono rounded border transition-colors ${
              period === p.value
                ? 'border-terminal-green text-terminal-green bg-terminal-green/10'
                : 'border-terminal-green/20 text-terminal-dim hover:text-terminal-green'
            }`}
          >
            {p.label}
          </button>
        ))}
        <span className="text-[10px] text-terminal-dim ml-auto font-mono">
          {candles.length} CANDLES
        </span>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={candles} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
          <XAxis
            dataKey="time"
            tick={{ fontSize: 9, fill: '#666' }}
            interval="preserveStartEnd"
            tickLine={false}
            axisLine={{ stroke: '#333' }}
          />
          <YAxis
            domain={[minPrice, maxPrice]}
            tick={{ fontSize: 9, fill: '#666' }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `${v}c`}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={50} stroke="#333" strokeDasharray="3 3" />
          <Bar
            dataKey="body"
            shape={<CandleShape />}
            isAnimationActive={false}
          >
            {candles.map((c, i) => (
              <Cell key={i} fill={c.bullish ? '#22c55e' : '#ef4444'} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
