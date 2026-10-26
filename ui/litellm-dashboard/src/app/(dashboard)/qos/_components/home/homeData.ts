import type { QosActivityEvent } from "@/app/(dashboard)/hooks/qos/useQosHome";
import type { QosTrends } from "../dashboardData";
import { vendorName, type QosHealthNode, type QosModelGroupMetrics } from "../qosData";

export type ServiceStatus = "ok" | "degraded" | "down" | "idle";

const DEGRADED_SUCCESS_RATE = 0.95;

const successRateOf = (metrics: QosModelGroupMetrics | undefined): number | null =>
  metrics === undefined || metrics.requests === 0
    ? null
    : (metrics.requests - metrics.failed_requests) / metrics.requests;

/** A model is down when every node failed its latest health check, degraded when some did or it fails requests. */
export const modelStatus = (
  nodes: readonly QosHealthNode[],
  metrics: QosModelGroupMetrics | undefined,
): ServiceStatus => {
  const unhealthy = nodes.filter((node) => node.latest_status === "unhealthy").length;
  if (nodes.length > 0 && unhealthy === nodes.length) return "down";
  const success = successRateOf(metrics);
  if (unhealthy > 0 || (success !== null && success < DEGRADED_SUCCESS_RATE)) return "degraded";
  if (nodes.length === 0 && success === null) return "idle";
  return "ok";
};

export const overallStatus = (statuses: readonly ServiceStatus[]): ServiceStatus => {
  if (statuses.some((status) => status === "down")) return "down";
  if (statuses.some((status) => status === "degraded")) return "degraded";
  return statuses.every((status) => status === "idle") ? "idle" : "ok";
};

const STATUS_LABELS: Readonly<Record<ServiceStatus, string>> = {
  ok: "All services operational",
  degraded: "Some services degraded",
  down: "Service outage",
  idle: "No traffic yet",
};

export const statusLabel = (status: ServiceStatus): string => STATUS_LABELS[status];

export interface ModelCard {
  readonly model: string;
  readonly status: ServiceStatus;
  readonly vendors: readonly string[];
  readonly metrics: QosModelGroupMetrics | undefined;
  readonly ttftTrend: readonly { readonly time: string; readonly ttft: number | null }[];
}

/** One card per model that has traffic or health checks, outages first. */
export const modelCards = (
  models: readonly QosModelGroupMetrics[],
  nodes: readonly QosHealthNode[],
  trends: QosTrends | undefined,
): readonly ModelCard[] => {
  const names = [...new Set([...models.map((model) => model.model_group), ...nodes.map((node) => node.model_name)])]
    .filter((name) => name !== "")
    .sort();
  const rank: Readonly<Record<ServiceStatus, number>> = { down: 0, degraded: 1, ok: 2, idle: 3 };
  const cards = names.map((name) => {
    const modelNodes = nodes.filter((node) => node.model_name === name);
    const metrics = models.find((model) => model.model_group === name);
    const series = trends?.series.find((item) => item.model_group === name);
    return {
      model: name,
      status: modelStatus(modelNodes, metrics),
      vendors: [...new Set(modelNodes.map((node) => vendorName(node.vendor)))],
      metrics,
      ttftTrend: (series?.points ?? []).map((point) => ({ time: point.bucket_start, ttft: point.ttft_ms.p95 })),
    };
  });
  return [...cards].sort((left, right) => rank[left.status] - rank[right.status]);
};

/** Requests of every model added up per time bucket. */
const clockLabel = (value: string): string => {
  const at = new Date(value);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
};

export const requestVolume = (trends: QosTrends): readonly { readonly time: string; readonly requests: number }[] => {
  const points = trends.series.flatMap((series) => series.points);
  const buckets = [...new Set(points.map((point) => point.bucket_start))].sort();
  return buckets.map((bucket) => ({
    time: clockLabel(bucket),
    requests: points
      .filter((point) => point.bucket_start === bucket)
      .reduce((total, point) => total + point.requests, 0),
  }));
};

export const relativeTimeLabel = (value: string, now: Date): string => {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(value).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
};

export type ActivityTone = "success" | "warning" | "error" | "info";

export interface ActivityLine {
  readonly tone: ActivityTone;
  readonly title: string;
  readonly description: string;
}

export const activityLine = (event: QosActivityEvent): ActivityLine => {
  switch (event.kind) {
    case "node_down":
      return {
        tone: "error",
        title: `${event.model} node unhealthy`,
        description: event.error === null ? vendorName(event.vendor) : event.error,
      };
    case "node_recovered":
      return { tone: "success", title: `${event.model} node recovered`, description: vendorName(event.vendor) };
    case "benchmark":
      return {
        tone: event.crosstalk_responses > 0 ? "error" : "info",
        title: `${event.model} benchmark, ${event.requests} requests`,
        description:
          event.crosstalk_responses > 0
            ? `${event.crosstalk_responses} responses crossed with other requests`
            : `${event.failed_requests} failed`,
      };
    case "model_added":
      return { tone: "info", title: `${event.model} added`, description: event.created_by };
  }
};
