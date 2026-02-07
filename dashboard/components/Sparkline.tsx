'use client';

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  showDot?: boolean;
}

function normalizeData(data: number[], width: number, height: number): { path: string; lastX: number; lastY: number } {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * width;
    const y = height - ((value - min) / range) * height;
    return { x, y };
  });

  const path = `M ${points.map((p) => `${p.x},${p.y}`).join(' L ')}`;
  const last = points[points.length - 1];

  return { path, lastX: last.x, lastY: last.y };
}

export default function Sparkline({
  data,
  width = 60,
  height = 20,
  color = '#00FF41',
  showDot = true,
}: SparklineProps): JSX.Element | null {
  if (data.length < 2) return null;

  const { path, lastX, lastY } = normalizeData(data, width, height);
  const glowStyle = { filter: `drop-shadow(0 0 2px ${color})` };

  return (
    <svg width={width} height={height} className="inline-block">
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={glowStyle}
      />
      {showDot && (
        <circle
          cx={lastX}
          cy={lastY}
          r="2"
          fill={color}
          style={{ filter: `drop-shadow(0 0 3px ${color})` }}
        />
      )}
    </svg>
  );
}
