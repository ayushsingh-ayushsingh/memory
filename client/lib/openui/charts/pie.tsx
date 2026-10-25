"use client";

import { EChartsPieChart } from "@/components/evilcharts/charts/echarts-pie-chart";

import { CHART_CLASS, type PieChartAdapterProps } from "./shared";

/** Pie engine adapter — see the note in `area.tsx`. */
export default function PieChartAdapter({ rows, config }: PieChartAdapterProps) {
  return (
    <EChartsPieChart
      animation
      className={CHART_CLASS}
      config={config}
      data={rows}
      dataKey="value"
      nameKey="name"
    >
      <EChartsPieChart.Pie />
      <EChartsPieChart.Tooltip />
      <EChartsPieChart.Legend isClickable />
    </EChartsPieChart>
  );
}
