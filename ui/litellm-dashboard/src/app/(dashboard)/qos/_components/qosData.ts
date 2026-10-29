import { getProviderLogoAndName } from "@/components/provider_info_helpers";
import type { components } from "@/lib/http/schema";

export type QosSummary = components["schemas"]["QosSummaryResponse"];
export type QosModelGroupMetrics = components["schemas"]["QosModelGroupMetrics"];
export type QosDeploymentMetrics = components["schemas"]["QosDeploymentMetrics"];
export type QosPercentiles = components["schemas"]["QosPercentiles"];

export const QOS_BENCHMARK_MODEL_PARAM = "benchmark";

export type QosRange = "15m" | "1h" | "6h" | "24h" | "7d" | "all";

const RANGE_MINUTES: Readonly<Record<Exclude<QosRange, "all">, number>> = {
  "15m": 15,
  "1h": 60,
  "6h": 360,
  "24h": 1440,
  "7d": 10080,
};

export const QOS_RANGES: readonly { readonly value: QosRange; readonly label: string }[] = [
  { value: "15m", label: "Last 15 minutes" },
  { value: "1h", label: "Last hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "all", label: "All" },
];

export const isQosRange = (value: string): value is QosRange => QOS_RANGES.some((range) => range.value === value);

export const qosRefreshOptions = (
  range: QosRange,
  refreshMs: number | false,
): { readonly refetchInterval: number | false; readonly staleTime?: number } =>
  range === "all" ? { refetchInterval: false, staleTime: Infinity } : { refetchInterval: refreshMs };

export const qosWindow = (
  range: QosRange,
  now: Date,
): { readonly start_time?: string; readonly end_time: string; readonly all_time?: boolean } =>
  range === "all"
    ? { all_time: true, end_time: now.toISOString() }
    : {
        start_time: new Date(now.getTime() - RANGE_MINUTES[range] * 60_000).toISOString(),
        end_time: now.toISOString(),
      };

export const successRate = (metrics: Pick<QosModelGroupMetrics, "requests" | "failed_requests">): number | null =>
  metrics.requests === 0 ? null : (metrics.requests - metrics.failed_requests) / metrics.requests;

export const formatMs = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "-";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(value < 10 ? 1 : 0)} ms`;
};

export const formatPercentiles = (percentiles: QosPercentiles): string =>
  `${formatMs(percentiles.p50)} / ${formatMs(percentiles.p95)}`;

export const formatRatio = (value: number | null): string => (value === null ? "-" : `${(value * 100).toFixed(1)}%`);

export const formatRate = (value: number | null): string => {
  if (value === null) return "-";
  return value >= 100 ? value.toFixed(0) : value.toFixed(2);
};

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
export type QosBenchmarkRequests = components["schemas"]["QosBenchmarkRequests"];
export type QosBenchmarkRequestLog = components["schemas"]["QosBenchmarkRequestLog"];
export type QosBenchmarkExchange = components["schemas"]["QosBenchmarkExchange"];
export type QosBenchmarkDeploymentLevel = components["schemas"]["QosBenchmarkDeploymentLevel"];
export type QosTargetModel = components["schemas"]["QosTargetModel"];
export type QosTargetDeployment = components["schemas"]["QosTargetDeployment"];

export const vendorName = (vendor: string): string => getProviderLogoAndName(vendor).displayName;

export const providerLabel = (deployment: QosTargetDeployment): string =>
  deployment.api_base === deployment.provider
    ? vendorName(deployment.vendor)
    : `${vendorName(deployment.vendor)} · ${deployment.api_base}`;

export type TargetChoice =
  | { readonly kind: "balanced" }
  | { readonly kind: "compare" }
  | { readonly kind: "deployment"; readonly modelId: string };

const DEPLOYMENT_CHOICE_PREFIX = "deployment:";

export const targetChoiceValue = (choice: TargetChoice): string => {
  switch (choice.kind) {
    case "balanced":
    case "compare":
      return choice.kind;
    case "deployment":
      return `${DEPLOYMENT_CHOICE_PREFIX}${choice.modelId}`;
  }
};

export const parseTargetChoice = (value: string): TargetChoice => {
  if (value === "balanced" || value === "compare") return { kind: value };
  if (value.startsWith(DEPLOYMENT_CHOICE_PREFIX)) {
    return { kind: "deployment", modelId: value.slice(DEPLOYMENT_CHOICE_PREFIX.length) };
  }
  throw new Error(`Unknown benchmark target ${value}`);
};

export const deploymentIdsFor = (choice: TargetChoice, deployments: readonly QosTargetDeployment[]): string[] => {
  switch (choice.kind) {
    case "balanced":
      return [];
    case "compare":
      return deployments.map((deployment) => deployment.model_id);
    case "deployment":
      return [choice.modelId];
  }
};

export type QosResponseChecks = components["schemas"]["QosResponseChecks"];
export type QosInterference = components["schemas"]["QosInterference"];

export interface CheckBadge {
  readonly tone: "success" | "warning" | "error";
  readonly label: string;
  readonly tooltip: string;
}

export const responseCheckBadge = (checks: QosResponseChecks): CheckBadge | null => {
  if (checks.checked === 0) return null;
  if (checks.crosstalk > 0) {
    return {
      tone: "error",
      label: `${checks.crosstalk} cross-talk`,
      tooltip: `${checks.crosstalk} of ${checks.checked} responses carried the code of another request`,
    };
  }
  if (checks.marker_missing > 0) {
    return {
      tone: "warning",
      label: `${checks.marker_missing} without code`,
      tooltip: `${checks.marker_missing} of ${checks.checked} responses did not repeat their code, so cross-talk cannot be ruled out for them`,
    };
  }
  return {
    tone: "success",
    label: `${checks.checked} passed`,
    tooltip: "Every checked response repeated its own code and no other",
  };
};

export const otherTraffic = (interference: QosInterference): number =>
  interference.same_deployment + interference.same_endpoint;

export const interferenceLabel = (interference: QosInterference): string =>
  `${interference.same_deployment} on this deployment · ${interference.same_endpoint} on its endpoint`;

export const comparesProviders = (detail: QosBenchmarkDetail): boolean =>
  new Set(detail.deployment_levels.map((level) => level.model_id)).size > 1;

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
  readonly deploymentIds: readonly string[];
  readonly concurrency: string;
  readonly requestsPerWorker: string;
  readonly maxTokens: string;
  readonly saveResponses: boolean;
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
  const targets = input.deploymentIds.length === 0 ? 1 : input.deploymentIds.length;
  const total = plannedRequests(concurrency.levels, requestsPerWorker) * targets;
  if (total > MAX_BENCHMARK_REQUESTS)
    return { ok: false, message: `This plan sends ${total} requests; the limit is ${MAX_BENCHMARK_REQUESTS}` };
  return {
    ok: true,
    total,
    plan: {
      model_group: input.model,
      deployment_ids: [...input.deploymentIds],
      concurrency: [...concurrency.levels],
      requests_per_worker: requestsPerWorker,
      max_tokens: maxTokens,
      save_responses: input.saveResponses,
    },
  };
};

export type QosHealthResponse = components["schemas"]["QosHealthResponse"];
export type QosHealthNode = components["schemas"]["QosHealthNode"];
export type QosHealthProbe = components["schemas"]["QosHealthProbe"];

export type QosMediaResponse = components["schemas"]["QosMediaResponse"];
export type QosAudioMetrics = components["schemas"]["QosAudioMetrics"];
export type QosVideoMetrics = components["schemas"]["QosVideoMetrics"];

export const AUDIO_MODALITY_LABELS: Readonly<Record<QosAudioMetrics["modality"], string>> = {
  speech: "Speech synthesis",
  transcription: "Transcription",
};

export const formatAudioLength = (seconds: number): string => {
  if (seconds <= 0) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
};

const formatFactor = (value: number | null | undefined): string =>
  value === null || value === undefined ? "-" : value.toFixed(2);

export const formatFactorPercentiles = (percentiles: QosPercentiles): string =>
  `${formatFactor(percentiles.p50)} / ${formatFactor(percentiles.p95)}`;

export const formatPrice = (value: number | null): string => (value === null ? "-" : value.toFixed(2));

export const videosWithoutResult = (metrics: QosVideoMetrics): number =>
  metrics.submitted - metrics.failed_submissions - metrics.succeeded - metrics.failed - metrics.cancelled;
