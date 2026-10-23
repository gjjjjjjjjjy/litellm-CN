import type { components } from "@/lib/http/schema";

export type QosSummary = components["schemas"]["QosSummaryResponse"];
export type QosModelGroupMetrics = components["schemas"]["QosModelGroupMetrics"];
export type QosDeploymentMetrics = components["schemas"]["QosDeploymentMetrics"];
export type QosPercentiles = components["schemas"]["QosPercentiles"];

export type QosRange = "15m" | "1h" | "6h" | "24h" | "7d";

const RANGE_MINUTES: Readonly<Record<QosRange, number>> = { "15m": 15, "1h": 60, "6h": 360, "24h": 1440, "7d": 10080 };

export const QOS_RANGES: readonly { readonly value: QosRange; readonly label: string }[] = [
  { value: "15m", label: "Last 15 minutes" },
  { value: "1h", label: "Last hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
];

export const isQosRange = (value: string): value is QosRange => Object.hasOwn(RANGE_MINUTES, value);

export const qosWindow = (range: QosRange, now: Date): { readonly start_time: string; readonly end_time: string } => ({
  start_time: new Date(now.getTime() - RANGE_MINUTES[range] * 60_000).toISOString(),
  end_time: now.toISOString(),
});

export const successRate = (metrics: QosModelGroupMetrics): number | null =>
  metrics.requests === 0 ? null : (metrics.requests - metrics.failed_requests) / metrics.requests;

export const formatMs = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "-";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(value < 10 ? 1 : 0)} ms`;
};

export const formatPercentiles = (percentiles: QosPercentiles): string =>
  `${formatMs(percentiles.p50)} / ${formatMs(percentiles.p95)}`;

export const formatRatio = (value: number | null): string => (value === null ? "-" : `${(value * 100).toFixed(1)}%`);

export const formatRate = (value: number): string => (value >= 100 ? value.toFixed(0) : value.toFixed(2));

export const deploymentsFor = (summary: QosSummary, modelGroup: string): QosDeploymentMetrics[] =>
  summary.deployments.filter((deployment) => deployment.model_group === modelGroup);

export const nodeLabel = (deployment: QosDeploymentMetrics): string =>
  deployment.api_base !== "" ? deployment.api_base : deployment.model_id;
