"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { Text } from "@cloudflare/kumo";

import {
  buildPieConfig,
  buildPieRows,
  buildSeriesConfig,
  buildSeriesRows,
  CHART_CLASS,
  type ChartSeries,
} from "./charts/shared";

/**
 * The patch of interface behind the generated-UI `Chart` component.
 *
 * Every engine lives in its own `next/dynamic` chunk: a chart only ever
 * appears when the model generates one, and the transcript route should not
 * pay for four ECharts renderers on first load. The `charts/*` adapter modules
 * import their engine eagerly so the compound parts (`EChartsAreaChart.Area`,
 * …) survive the lazy boundary.
 */
const ChartLoading = () => (
  <div
    className={`${CHART_CLASS} flex items-center justify-center rounded-lg border border-kumo-hairline bg-kumo-base`}
  >
    <Text size="sm" variant="secondary">
      Rendering chart…
    </Text>
  </div>
);

const AreaChart = dynamic(() => import("./charts/area"), {
  loading: ChartLoading,
  ssr: false,
});

const BarChart = dynamic(() => import("./charts/bar"), {
  loading: ChartLoading,
  ssr: false,
});

const LineChart = dynamic(() => import("./charts/line"), {
  loading: ChartLoading,
  ssr: false,
});

const PieChart = dynamic(() => import("./charts/pie"), {
  loading: ChartLoading,
  ssr: false,
});

export type GeneratedChartProps = {
  kind: "area" | "bar" | "line" | "pie";
  categories: string[];
  series: ChartSeries[];
  title?: string;
};

export function GeneratedChart({ kind, categories, series, title }: GeneratedChartProps) {
  const seriesNames = useMemo(() => series.map((item) => item.name), [series]);

  const seriesRows = useMemo(() => buildSeriesRows(categories, series), [categories, series]);
  const seriesConfig = useMemo(() => buildSeriesConfig(seriesNames), [seriesNames]);

  const pieRows = useMemo(() => buildPieRows(categories, series), [categories, series]);
  const pieConfig = useMemo(() => buildPieConfig(categories), [categories]);

  if (!categories.length || !series.length) {
    return (
      <Text size="sm" variant="secondary">
        No chart data.
      </Text>
    );
  }

  const chart =
    kind === "pie" ? (
      <PieChart config={pieConfig} rows={pieRows} />
    ) : kind === "bar" ? (
      <BarChart config={seriesConfig} rows={seriesRows} seriesNames={seriesNames} />
    ) : kind === "line" ? (
      <LineChart config={seriesConfig} rows={seriesRows} seriesNames={seriesNames} />
    ) : (
      <AreaChart config={seriesConfig} rows={seriesRows} seriesNames={seriesNames} />
    );

  return (
    <figure className="w-full min-w-0">
      {title ? (
        <figcaption className="mb-2">
          <Text size="sm" variant="secondary">
            {title}
          </Text>
        </figcaption>
      ) : null}
      {chart}
    </figure>
  );
}
