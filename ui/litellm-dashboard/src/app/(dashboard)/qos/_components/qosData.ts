import type { components } from "@/lib/http/schema";

export type QosSummary = components["schemas"]["QosSummaryResponse"];
export type QosModelGroupMetrics = components["schemas"]["QosModelGroupMetrics"];
export type QosDeploymentMetrics = components["schemas"]["QosDeploymentMetrics"];
export type QosPercentiles = components["schemas"]["QosPercentiles"];

export const QOS_BENCHMARK_MODEL_PARAM = "benchmark";

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

export const nodeLabel = (deployment: QosDeploymentMetrics): string => {
  if (deployment.api_base !== "") return deployment.api_base;
  return deployment.model_id !== "" ? deployment.model_id : "Unknown node";
};

export type QosBenchmarkRequest = components["schemas"]["QosBenchmarkRequest"];
export type QosBenchmarkStarted = components["schemas"]["QosBenchmarkStarted"];
export type QosBenchmarkRun = components["schemas"]["QosBenchmarkRun"];
export type QosBenchmarkDetail = components["schemas"]["QosBenchmarkDetail"];
export type QosBenchmarkLevel = components["schemas"]["QosBenchmarkLevel"];
export type QosBenchmarkDeleted = components["schemas"]["QosBenchmarkDeleted"];

export const MAX_CONCURRENCY = 256;
export const MAX_CONCURRENCY_LEVELS = 8;
export const MAX_BENCHMARK_REQUESTS = 5000;

export type ConcurrencyParse =
  | { readonly ok: true; readonly levels: readonly number[] }
  | { readonly ok: false; readonly message: string };

export const parseConcurrency = (text: string): ConcurrencyParse => {
  const parts = text
    .split(/[,，\s]+/)
    .map((part) => part.trim())
    .filter((part) => part !== "");
  if (parts.length === 0) return { ok: false, message: "Enter at least one concurrency level" };
  if (parts.length > MAX_CONCURRENCY_LEVELS)
    return { ok: false, message: `At most ${MAX_CONCURRENCY_LEVELS} concurrency levels` };
  const levels = parts.map(Number);
  if (!levels.every((level) => Number.isInteger(level) && level >= 1 && level <= MAX_CONCURRENCY))
    return { ok: false, message: `Concurrency levels must be whole numbers from 1 to ${MAX_CONCURRENCY}` };
  return { ok: true, levels };
};

export const plannedRequests = (levels: readonly number[], requestsPerWorker: number): number =>
  levels.reduce((total, level) => total + level, 0) * requestsPerWorker;

export const recordedRequests = (detail: QosBenchmarkDetail): number =>
  detail.levels.reduce((total, level) => total + level.requests, 0);

export interface BenchmarkFormInput {
  readonly model: string;
  readonly concurrency: string;
  readonly requestsPerWorker: string;
  readonly maxTokens: string;
}

export type BenchmarkPlanCheck =
  | { readonly ok: true; readonly plan: QosBenchmarkRequest; readonly total: number }
  | { readonly ok: false; readonly message: string };

const wholeNumberIn = (text: string, min: number, max: number): number | null => {
  const trimmed = text.trim();
  const value = Number(trimmed);
  const isWholeNumber = trimmed !== "" && Number.isInteger(value);
  return isWholeNumber && value >= min && value <= max ? value : null;
};

export const checkBenchmarkPlan = (input: BenchmarkFormInput): BenchmarkPlanCheck => {
  if (input.model === "") return { ok: false, message: "Choose a model to test" };
  const concurrency = parseConcurrency(input.concurrency);
  if (!concurrency.ok) return concurrency;
  const requestsPerWorker = wholeNumberIn(input.requestsPerWorker, 1, 50);
  if (requestsPerWorker === null) return { ok: false, message: "Requests per worker must be from 1 to 50" };
  const maxTokens = wholeNumberIn(input.maxTokens, 1, 8192);
  if (maxTokens === null) return { ok: false, message: "Max output tokens must be from 1 to 8192" };
  const total = plannedRequests(concurrency.levels, requestsPerWorker);
  if (total > MAX_BENCHMARK_REQUESTS)
    return { ok: false, message: `This plan sends ${total} requests; the limit is ${MAX_BENCHMARK_REQUESTS}` };
  return {
    ok: true,
    total,
    plan: {
      model_group: input.model,
      concurrency: [...concurrency.levels],
      requests_per_worker: requestsPerWorker,
      max_tokens: maxTokens,
    },
  };
};

export type QosHealthResponse = components["schemas"]["QosHealthResponse"];
export type QosHealthNode = components["schemas"]["QosHealthNode"];
export type QosHealthProbe = components["schemas"]["QosHealthProbe"];

export const healthNodeLabel = (node: QosHealthNode): string => (node.api_base !== "" ? node.api_base : node.model_id);
