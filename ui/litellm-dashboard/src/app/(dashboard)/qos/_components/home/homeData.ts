import type { QosActivityEvent } from "@/app/(dashboard)/hooks/qos/useQosHome";
import {
  successRate,
  vendorName,
  type QosDeploymentMetrics,
  type QosHealthNode,
  type QosModelGroupMetrics,
  type QosTargetDeployment,
  type QosTargetModel,
} from "../qosData";

export type ServiceStatus = "ok" | "degraded" | "down" | "idle";

const DEGRADED_SUCCESS_RATE = 0.95;

/** A model is down when every node failed its latest health check, degraded when some did or it fails requests. */
export const modelStatus = (
  nodes: readonly QosHealthNode[],
  metrics: QosModelGroupMetrics | undefined,
): ServiceStatus => {
  const unhealthy = nodes.filter((node) => node.latest_status === "unhealthy").length;
  if (nodes.length > 0 && unhealthy === nodes.length) return "down";
  const success = metrics === undefined ? null : successRate(metrics);
  if (unhealthy > 0 || (success !== null && success < DEGRADED_SUCCESS_RATE)) return "degraded";
  if (nodes.length === 0 && success === null) return "idle";
  return "ok";
};

export const overallStatus = (statuses: readonly ServiceStatus[]): ServiceStatus => {
  if (statuses.some((status) => status === "down")) return "down";
  if (statuses.some((status) => status === "degraded")) return "degraded";
  if (statuses.length === 0) return "idle";
  return statuses.includes("idle") ? "idle" : "ok";
};

const STATUS_LABELS: Readonly<Record<ServiceStatus, string>> = {
  ok: "All channels operational",
  degraded: "Some channels are degraded",
  down: "Some channels are unavailable",
  idle: "Awaiting health checks",
};

export const statusLabel = (status: ServiceStatus): string => STATUS_LABELS[status];

export interface ChannelCard {
  readonly model: string;
  readonly status: ServiceStatus;
  readonly deployment: QosTargetDeployment;
  readonly health: QosHealthNode | undefined;
  readonly metrics: QosDeploymentMetrics | undefined;
}

export const channelCards = (
  models: readonly QosTargetModel[],
  nodes: readonly QosHealthNode[],
  metrics: readonly QosDeploymentMetrics[],
): readonly ChannelCard[] => {
  const rank: Readonly<Record<ServiceStatus, number>> = { down: 0, degraded: 1, ok: 2, idle: 3 };
  const cards = models.flatMap((model) =>
    model.deployments.map((deployment): ChannelCard => {
      const health = nodes.find(
        (node) => node.model_id === deployment.model_id && node.model_name === model.model_group,
      );
      const traffic = metrics.find(
        (row) => row.model_id === deployment.model_id && row.model_group === model.model_group,
      );
      return {
        model: model.model_group,
        deployment,
        health,
        metrics: traffic,
        status: health === undefined ? "idle" : modelStatus([health], traffic),
      };
    }),
  );
  return [...cards].sort((left, right) => rank[left.status] - rank[right.status]);
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
