"use client";

import { EChartsLineChart } from "@/components/evilcharts/charts/echarts-line-chart";

import { CHART_CLASS, type SeriesChartAdapterProps } from "./shared";

/** Line engine adapter — see the note in `area.tsx`. */
export default function LineChartAdapter({ rows, config, seriesNames }: SeriesChartAdapterProps) {
  return (
    <EChartsLineChart
      animation
      className={CHART_CLASS}
      config={config}
      curveType="smooth"
      data={rows}
      xDataKey="category"
    >
      {seriesNames.map((name) => (
        <EChartsLineChart.Line dataKey={name} key={name} />
      ))}
      <EChartsLineChart.XAxis />
      <EChartsLineChart.YAxis />
      <EChartsLineChart.Grid />
      <EChartsLineChart.Tooltip />
      <EChartsLineChart.Legend isClickable />
    </EChartsLineChart>
  );
}
