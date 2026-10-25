"use client";

import { EChartsBarChart } from "@/components/evilcharts/charts/echarts-bar-chart";

import { CHART_CLASS, type SeriesChartAdapterProps } from "./shared";

/** Bar engine adapter — see the note in `area.tsx`. */
export default function BarChartAdapter({ rows, config, seriesNames }: SeriesChartAdapterProps) {
  return (
    <EChartsBarChart
      animation
      className={CHART_CLASS}
      config={config}
      data={rows}
      xDataKey="category"
    >
      {seriesNames.map((name) => (
        <EChartsBarChart.Bar dataKey={name} key={name} />
      ))}
      <EChartsBarChart.XAxis />
      <EChartsBarChart.YAxis />
      <EChartsBarChart.Grid />
      <EChartsBarChart.Tooltip />
      <EChartsBarChart.Legend isClickable />
    </EChartsBarChart>
  );
}
