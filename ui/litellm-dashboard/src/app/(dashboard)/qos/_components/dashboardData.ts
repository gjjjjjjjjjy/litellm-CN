import type { components } from "@/lib/http/schema";
import { formatMs, formatRate, vendorName, type QosDeploymentMetrics, type QosModelGroupMetrics } from "./qosData";

export type QosTrends = components["schemas"]["QosTrendsResponse"];
export type QosOverall = components["schemas"]["QosOverall"];
export type QosTrendSeries = components["schemas"]["QosTrendSeries"];
export type QosTrendPoint = components["schemas"]["QosTrendPoint"];
export type TrendGrouping = QosTrends["group_by"];
export type TrendMetric = "ttft" | "tpot" | "requests" | "success";
export type CompareMetric = "ttft" | "tpot" | "throughput" | "success";

export const TREND_GROUPINGS: readonly { readonly value: TrendGrouping; readonly label: string }[] = [
  { value: "model", label: "By model" },
  { value: "deployment", label: "By provider" },
];

export const TREND_METRICS: readonly { readonly value: TrendMetric; readonly label: string }[] = [
  { value: "ttft", label: "TTFT P95" },
  { value: "tpot", label: "TPOT P95" },
  { value: "requests", label: "Requests" },
  { value: "success", label: "Success rate" },
];

export const COMPARE_METRICS: readonly { readonly value: CompareMetric; readonly label: string }[] = [
  { value: "ttft", label: "TTFT P95" },
  { value: "tpot", label: "TPOT P95" },
  { value: "throughput", label: "Output tokens/s" },
  { value: "success", label: "Success rate" },
];

const successPercent = (requests: number, failed: number): number | null =>
  requests === 0 ? null : ((requests - failed) / requests) * 100;

export const seriesLabel = (series: QosTrendSeries): string =>
  series.model_id === "" ? series.model_group : `${series.model_group} · ${vendorName(series.vendor)}`;

const pointValue = (point: QosTrendPoint, metric: TrendMetric): number | null => {
  switch (metric) {
    case "ttft":
      return point.ttft_ms.p95;
    case "tpot":
      return point.tpot_ms.p95;
    case "requests":
      return point.requests;
    case "success":
      return successPercent(point.requests, point.failed_requests);
  }
};

const bucketLabel = (bucketStart: string, bucketSeconds: number, multiDay: boolean): string => {
  const at = new Date(bucketStart);
  const date = `${String(at.getMonth() + 1).padStart(2, "0")}-${String(at.getDate()).padStart(2, "0")}`;
  const time = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  if (bucketSeconds >= 86_400) return date;
  return multiDay ? `${date} ${time}` : time;
};

export interface TrendChart {
  readonly categories: readonly string[];
  readonly rows: readonly Record<string, string | number | null>[];
}

/** One row per time bucket and one column per series, leaving a gap where a series had no traffic. */
export const trendChart = (trends: QosTrends, metric: TrendMetric): TrendChart => {
  const buckets = [
    ...new Set(trends.series.flatMap((series) => series.points.map((point) => point.bucket_start))),
  ].sort();
  const multiDay = new Date(trends.end_time).getTime() - new Date(trends.start_time).getTime() > 86_400_000;
  const valuesBySeries = trends.series.map(
    (series) =>
      [
        seriesLabel(series),
        new Map(series.points.map((point) => [point.bucket_start, pointValue(point, metric)])),
      ] as const,
  );
  return {
    categories: valuesBySeries.map(([label]) => label),
    rows: buckets.map((bucket) =>
      Object.fromEntries([
        ["time", bucketLabel(bucket, trends.bucket_seconds, multiDay)],
        ...valuesBySeries.map(([label, values]) => [label, values.get(bucket) ?? null]),
      ]),
    ),
  };
};

export const trendValueFormatter = (metric: TrendMetric): ((value: number) => string) => {
  switch (metric) {
    case "ttft":
    case "tpot":
      return formatMs;
    case "requests":
      return (value) => String(Math.round(value));
    case "success":
      return (value) => `${value.toFixed(1)}%`;
  }
};

export type Change = { readonly percent: number; readonly better: boolean } | null;

const relativeChange = (current: number | null, previous: number | null, higherIsBetter: boolean): Change => {
  if (current === null || previous === null || previous === 0) return null;
  const percent = ((current - previous) / previous) * 100;
  return { percent, better: higherIsBetter ? percent >= 0 : percent <= 0 };
};

export interface Headline {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly change: Change;
}

export const headlines = (current: QosOverall, previous: QosOverall): readonly Headline[] => {
  const currentSuccess = successPercent(current.requests, current.failed_requests);
  const previousSuccess = successPercent(previous.requests, previous.failed_requests);
  return [
    {
      key: "requests",
      label: "Requests",
      value: String(current.requests),
      change: relativeChange(current.requests, previous.requests, true),
    },
    {
      key: "success",
      label: "Success rate",
      value: currentSuccess === null ? "-" : `${currentSuccess.toFixed(1)}%`,
      change: relativeChange(currentSuccess, previousSuccess, true),
    },
    {
      key: "ttft",
      label: "TTFT P95",
      value: formatMs(current.ttft_ms.p95),
      change: relativeChange(current.ttft_ms.p95, previous.ttft_ms.p95, false),
    },
    {
      key: "tpot",
      label: "TPOT P95",
      value: formatMs(current.tpot_ms.p95),
      change: relativeChange(current.tpot_ms.p95, previous.tpot_ms.p95, false),
    },
    {
      key: "throughput",
      label: "Output tokens/s",
      value: formatRate(current.output_tokens_per_second),
      change: relativeChange(current.output_tokens_per_second, previous.output_tokens_per_second, true),
    },
  ];
};

const compareValue = (metrics: QosModelGroupMetrics, metric: CompareMetric): number | null => {
  switch (metric) {
    case "ttft":
      return metrics.ttft_ms.p95;
    case "tpot":
      return metrics.tpot_ms.p95;
    case "throughput":
      return metrics.output_tokens_per_second;
    case "success":
      return successPercent(metrics.requests, metrics.failed_requests);
  }
};

export const compareValueFormatter = (metric: CompareMetric): ((value: number) => string) => {
  switch (metric) {
    case "ttft":
    case "tpot":
      return formatMs;
    case "throughput":
      return formatRate;
    case "success":
      return (value) => `${value.toFixed(1)}%`;
  }
};

/** Bars for each model, or each provider of a model, best first. */
export const compareBars = (
  rows: readonly (QosModelGroupMetrics | QosDeploymentMetrics)[],
  metric: CompareMetric,
): readonly { readonly name: string; readonly value: number }[] => {
  const lowerIsBetter = metric === "ttft" || metric === "tpot";
  const bars = rows.flatMap((row) => {
    const value = compareValue(row, metric);
    const name = "model_id" in row ? `${row.model_group} · ${vendorName(row.vendor)}` : row.model_group;
    return value === null ? [] : [{ name, value }];
  });
  return [...bars].sort((left, right) => (lowerIsBetter ? left.value - right.value : right.value - left.value));
};
