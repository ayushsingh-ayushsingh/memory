/**
 * Shared plumbing for the Evil Charts adapters behind the generated-UI `Chart`
 * component. One adapter module per engine keeps each ECharts renderer in its
 * own lazily-loaded chunk (see `../chart.tsx`).
 */
import type { ChartConfig } from "@/components/evilcharts/ui/echarts-chart";

/** Evil Charts roots are flex columns: the consumer owns the height. */
export const CHART_CLASS = "h-64 w-full";

export type ChartRow = Record<string, string | number>;

export type PieRow = { name: string; value: number };

/** One value per category, in the same order. */
export type ChartSeries = { name: string; values: number[] };

export type SeriesChartAdapterProps = {
  rows: ChartRow[];
  config: ChartConfig;
  seriesNames: string[];
};

export type PieChartAdapterProps = {
  rows: PieRow[];
  config: ChartConfig;
};

/**
 * Series slots come from the app's shadcn-compatibility layer in
 * `app/globals.css`, which aliases the chart palette onto Kumo tokens. Evil
 * Charts reads its slots off the live DOM, so a `var(...)` reference follows
 * the theme on its own — no need for the `.dark` rule Evil Charts ships for
 * shadcn's class-based dark mode, which this app does not use (next-themes
 * drives `[data-mode="dark"]` instead).
 */
const SERIES_TOKENS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"] as const;

const seriesColor = (index: number): string =>
  `var(${SERIES_TOKENS[index % SERIES_TOKENS.length]})`;

const colorConfig = (names: string[]): ChartConfig =>
  Object.fromEntries(
    names.map((name, index) => [name, { colors: { light: [seriesColor(index)] }, label: name }]),
  );

/** Config for engines whose series are keyed by series name. */
export const buildSeriesConfig = colorConfig;

/** Config for the pie engine: one sector per category, keyed by sector name. */
export const buildPieConfig = colorConfig;

export const buildSeriesRows = (categories: string[], series: ChartSeries[]): ChartRow[] =>
  categories.map((category, index) => {
    const row: ChartRow = { category };
    for (const item of series) {
      row[item.name] = item.values[index] ?? 0;
    }
    return row;
  });

export const buildPieRows = (categories: string[], series: ChartSeries[]): PieRow[] => {
  const values = series[0]?.values ?? [];
  return categories.map((name, index) => ({ name, value: values[index] ?? 0 }));
};
