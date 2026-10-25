"use client";

import { EChartsAreaChart } from "@/components/evilcharts/charts/echarts-area-chart";

import { CHART_CLASS, type SeriesChartAdapterProps } from "./shared";

/**
 * Area engine adapter. Imports `EChartsAreaChart` eagerly (its `Area`, `XAxis`
 * and friends are statics on the module) so the component itself can be
 * lazy-loaded by `next/dynamic` without losing the compound parts.
 */
export default function AreaChartAdapter({ rows, config, seriesNames }: SeriesChartAdapterProps) {
  return (
    <EChartsAreaChart
      animation
      className={CHART_CLASS}
      config={config}
      curveType="smooth"
      data={rows}
      xDataKey="category"
    >
      {seriesNames.map((name) => (
        <EChartsAreaChart.Area dataKey={name} key={name} variant="gradient" />
      ))}
      <EChartsAreaChart.XAxis />
      <EChartsAreaChart.YAxis />
      <EChartsAreaChart.Grid />
      <EChartsAreaChart.Tooltip />
      <EChartsAreaChart.Legend isClickable />
    </EChartsAreaChart>
  );
}
