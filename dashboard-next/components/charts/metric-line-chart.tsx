"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/ui/state-blocks";
import { formatNumber, formatShortTime } from "@/lib/format";

export type ChartDatum = {
  timestamp: string;
  [key: string]: string | number | null | undefined;
};

export interface ChartSeries {
  dataKey: string;
  label: string;
  color: string;
  suffix?: string;
}

export function MetricLineChart({
  data,
  series,
  height = 280,
}: {
  data: ChartDatum[];
  series: ChartSeries[];
  height?: number;
}) {
  if (data.length === 0) {
    return <EmptyState title="No chart data" />;
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: -12, right: 18, top: 18, bottom: 0 }}>
          <CartesianGrid stroke="rgba(39,48,45,0.12)" strokeDasharray="4 8" />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatShortTime}
            stroke="rgba(39,48,45,0.45)"
            tickLine={false}
            axisLine={false}
            minTickGap={32}
          />
          <YAxis
            stroke="rgba(39,48,45,0.45)"
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => formatNumber(Number(value), 0)}
          />
          <Tooltip
            labelFormatter={(value) => formatShortTime(String(value))}
            formatter={(value, name) => {
              const found = series.find((item) => item.label === name || item.dataKey === name);
              const suffix = found?.suffix ?? "";
              return [`${formatNumber(Number(value), 2)}${suffix}`, found?.label ?? String(name)];
            }}
            contentStyle={{
              borderRadius: 18,
              border: "1px solid rgba(39,48,45,0.14)",
              background: "rgba(255,250,240,0.96)",
              boxShadow: "0 18px 50px rgba(31,37,34,0.16)",
            }}
          />
          {series.map((item) => (
            <Line
              key={item.dataKey}
              type="monotone"
              dataKey={item.dataKey}
              name={item.label}
              stroke={item.color}
              strokeWidth={3}
              dot={false}
              activeDot={{ r: 5 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
