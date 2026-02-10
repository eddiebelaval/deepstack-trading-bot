'use client';

import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer,
} from 'recharts';
import { CHART_COLORS } from '@/lib/research-utils';

interface RadarDataPoint {
  axis: string;
  value: number;
}

interface IndicatorRadarProps {
  data: RadarDataPoint[];
}

export default function IndicatorRadar({ data }: IndicatorRadarProps) {
  return (
    <div className="h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} cx="50%" cy="50%" outerRadius="75%">
          <PolarGrid stroke={CHART_COLORS.greenDim} strokeOpacity={0.15} />
          <PolarAngleAxis
            dataKey="axis"
            tick={{ fill: CHART_COLORS.greenDim, fontSize: 9 }}
          />
          <PolarRadiusAxis
            domain={[0, 100]}
            tick={false}
            axisLine={false}
          />
          <Radar
            dataKey="value"
            stroke={CHART_COLORS.green}
            fill={CHART_COLORS.green}
            fillOpacity={0.15}
            strokeWidth={1.5}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
