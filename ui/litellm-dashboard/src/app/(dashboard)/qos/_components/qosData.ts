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

export const formatFactor = (value: number | null | undefined): string =>
  value === null || value === undefined ? "-" : value.toFixed(2);

export const formatFactorPercentiles = (percentiles: QosPercentiles): string =>
  `${formatFactor(percentiles.p50)} / ${formatFactor(percentiles.p95)}`;

export const formatPrice = (value: number | null): string => (value === null ? "-" : value.toFixed(2));

export const videosWithoutResult = (metrics: QosVideoMetrics): number =>
  metrics.submitted - metrics.failed_submissions - metrics.succeeded - metrics.failed - metrics.cancelled;

export type QosVideoReviewsResponse = components["schemas"]["QosVideoReviewsResponse"];
export type QosReviewVideo = components["schemas"]["QosReviewVideo"];
export type QosVideoReview = components["schemas"]["QosVideoReview"];
export type QosVideoReviewInput = components["schemas"]["QosVideoReviewInput"];
export type QosVideoReviewSummary = components["schemas"]["QosVideoReviewSummary"];

export type ReviewDimension = "overall" | "visual" | "detail" | "motion" | "alignment" | "physics" | "audio";

export const REVIEW_DIMENSIONS: readonly ReviewDimension[] = [
  "overall",
  "visual",
  "detail",
  "motion",
  "alignment",
  "physics",
  "audio",
];

export const REVIEW_DIMENSION_LABELS: Readonly<Record<ReviewDimension, string>> = {
  overall: "Overall",
  visual: "Visual quality",
  detail: "Video detail",
  motion: "Motion",
  alignment: "Prompt alignment",
  physics: "Physics and common sense",
  audio: "Sound",
};

export const formatScore = (value: number | null | undefined): string =>
  value === null || value === undefined ? "-" : value.toFixed(1);

export type ReviewScores = Readonly<Partial<Record<ReviewDimension, number>>>;

export const reviewScores = (review: QosVideoReview | null | undefined): ReviewScores =>
  review === null || review === undefined
    ? {}
    : Object.fromEntries(
        REVIEW_DIMENSIONS.flatMap((dimension) => {
          const score = review[dimension];
          return score === null || score === undefined ? [] : [[dimension, score] as const];
        }),
      );

export const reviewInput = (scores: ReviewScores, comment: string): QosVideoReviewInput | null => {
  const overall = scores.overall;
  if (overall === undefined) return null;
  const trimmed = comment.trim();
  return { ...scores, overall, comment: trimmed === "" ? null : trimmed };
};

export type QosVideoAiReview = components["schemas"]["QosVideoAiReview"];
export type QosVideoAiSummary = components["schemas"]["QosVideoAiSummary"];
export type QosVideoEvaluationOptions = components["schemas"]["QosVideoEvaluationOptions"];
export type QosVideoEvaluationStarted = components["schemas"]["QosVideoEvaluationStarted"];
export type QosVideoEvaluationPrompt = components["schemas"]["QosVideoEvaluationPrompt"];
export type QosProbeModel = components["schemas"]["QosProbeModel"];

export type AiDimension = Exclude<ReviewDimension, "audio">;

export const AI_DIMENSIONS: readonly AiDimension[] = ["overall", "visual", "detail", "motion", "alignment", "physics"];

export const VIDEO_REVIEW_POLL_MS = 30_000;
export const EVALUATION_START_POLL_MS = 10 * 60_000;

export const reviewPollMs = (
  videos: readonly QosReviewVideo[],
  evaluationStartedAt: number | null,
  now: number,
): number | false =>
  videos.some((video) => video.status === "generating") ||
  (evaluationStartedAt !== null && now - evaluationStartedAt < EVALUATION_START_POLL_MS)
    ? VIDEO_REVIEW_POLL_MS
    : false;

export type EvaluationCost = {
  readonly total: number;
  readonly currency: string;
  readonly unpriced: readonly string[];
};

export const evaluationCost = (models: readonly QosProbeModel[]): EvaluationCost | null => {
  const priced = models.filter((model) => model.last_price !== null);
  if (priced.length === 0) return null;
  return {
    total: priced.reduce((sum, model) => sum + (model.last_price ?? 0), 0),
    currency: [...new Set(priced.map((model) => model.currency ?? ""))].join(" / "),
    unpriced: models.filter((model) => model.last_price === null).map((model) => model.model_group),
  };
};

export type QosSpeechEvaluationsResponse = components["schemas"]["QosSpeechEvaluationsResponse"];
export type QosSpeechResult = components["schemas"]["QosSpeechResult"];
export type QosSpeechReview = components["schemas"]["QosSpeechReview"];
export type QosSpeechEvaluationOptions = components["schemas"]["QosSpeechEvaluationOptions"];
export type QosSpeechEvaluationStarted = components["schemas"]["QosSpeechEvaluationStarted"];

export interface RunMember {
  readonly created_at: string;
  readonly scheduled: boolean;
  readonly model_group: string;
}

export interface ProbeRun<T extends RunMember> {
  readonly key: string;
  readonly scheduled: boolean;
  readonly startedAt: string;
  readonly items: readonly T[];
}

/** The probe's runs, newest first, each with its items ordered by model so runs line up side by side. */
export const probeRuns = <T extends RunMember>(
  items: readonly T[],
  runOf: (item: T) => string,
): readonly ProbeRun<T>[] =>
  [...new Set(items.map(runOf))]
    .map((key) => {
      const members = items.filter((item) => runOf(item) === key);
      const startedAt = members
        .map((member) => member.created_at)
        .reduce((earliest, created) => (Date.parse(created) < Date.parse(earliest) ? created : earliest));
      return {
        key,
        scheduled: members.some((member) => member.scheduled),
        startedAt,
        items: [...members].sort((left, right) => left.model_group.localeCompare(right.model_group)),
      };
    })
    .sort((left, right) => Date.parse(right.startedAt) - Date.parse(left.startedAt));

export const videoRunKey = (video: QosReviewVideo): string => video.run ?? `prompt:${video.prompt}`;

export const SCHEDULED_RUNS_SHOWN = 3;
export const VIDEO_KEPT_MS = 24 * 60 * 60_000;

/** Whether the provider has likely deleted a video's file; it keeps them about a day. */
export const isExpired = (video: QosReviewVideo, now: number): boolean =>
  now - Date.parse(video.created_at) > VIDEO_KEPT_MS;

const average = (values: readonly number[]): number | null =>
  values.length === 0 ? null : values.reduce((sum, value) => sum + value, 0) / values.length;

export interface VideoRunSummary {
  readonly videos: number;
  readonly aiAverage: number | null;
  readonly rated: number;
}

export const videoRunSummary = (videos: readonly QosReviewVideo[]): VideoRunSummary => ({
  videos: videos.length,
  aiAverage: average(videos.flatMap((video) => (video.ai_review === null ? [] : [video.ai_review.overall]))),
  rated: videos.filter((video) => video.reviews > 0).length,
});

export const realTimeFactor = (result: QosSpeechResult): number | null =>
  result.succeeded && result.audio_seconds !== null && result.audio_seconds > 0
    ? result.latency_ms / (result.audio_seconds * 1000)
    : null;

export type TranscriptMark = {
  readonly char: string;
  readonly kind: "same" | "wrong" | "missing" | "unspoken";
};

export interface CharacterErrors {
  readonly rate: number;
  readonly marks: readonly TranscriptMark[];
}

const SPOKEN = /[\p{L}\p{N}\p{M}]/u;
const isSpoken = (char: string): boolean => SPOKEN.test(char);

const editCost = (reference: readonly string[], heard: readonly string[]): readonly (readonly number[])[] => {
  const cost = Array.from({ length: reference.length + 1 }, (_, i) =>
    Array.from({ length: heard.length + 1 }, (_, j) => (i === 0 || j === 0 ? i + j : 0)),
  );
  for (let i = 1; i <= reference.length; i += 1) {
    for (let j = 1; j <= heard.length; j += 1) {
      const substitution = reference[i - 1] === heard[j - 1] ? 0 : 1;
      cost[i][j] = Math.min(cost[i - 1][j - 1] + substitution, cost[i - 1][j] + 1, cost[i][j - 1] + 1);
    }
  }
  return cost;
};

const alignment = (reference: readonly string[], heard: readonly string[]): readonly TranscriptMark[] => {
  const cost = editCost(reference, heard);
  const walk = (i: number, j: number, after: readonly TranscriptMark[]): readonly TranscriptMark[] => {
    if (i === 0 && j === 0) return after;
    if (i > 0 && j > 0 && cost[i][j] === cost[i - 1][j - 1] + (reference[i - 1] === heard[j - 1] ? 0 : 1)) {
      const kind = reference[i - 1] === heard[j - 1] ? "same" : "wrong";
      return walk(i - 1, j - 1, [{ char: heard[j - 1], kind }, ...after]);
    }
    if (j > 0 && cost[i][j] === cost[i][j - 1] + 1)
      return walk(i, j - 1, [{ char: heard[j - 1], kind: "wrong" }, ...after]);
    return walk(i - 1, j, [{ char: reference[i - 1], kind: "missing" }, ...after]);
  };
  return walk(reference.length, heard.length, []);
};

/** How a transcript differs from the sentence, counting letters and digits only, so punctuation, spaces and the
 * emoji some models add are not errors. The marks follow the transcript, with missed characters where they belong. */
export const characterErrors = (reference: string, heard: string): CharacterErrors | null => {
  const spokenReference = [...reference].filter(isSpoken);
  if (spokenReference.length === 0) return null;
  const heardChars = [...heard];
  const steps = alignment(spokenReference, heardChars.filter(isSpoken));
  const errors = steps.filter((step) => step.kind !== "same").length;
  const placed = heardChars.reduce<{ readonly marks: readonly TranscriptMark[]; readonly next: number }>(
    ({ marks, next }, char) => {
      if (!isSpoken(char)) return { marks: [...marks, { char, kind: "unspoken" }], next };
      const missed = steps.slice(next).findIndex((step) => step.kind !== "missing");
      const upTo = next + missed + 1;
      return { marks: [...marks, ...steps.slice(next, upTo)], next: upTo };
    },
    { marks: [], next: 0 },
  );
  return { rate: errors / spokenReference.length, marks: [...placed.marks, ...steps.slice(placed.next)] };
};

export interface SpeechRunSummary {
  readonly readings: number;
  readonly transcriptions: number;
  readonly rateable: number;
  readonly rated: number;
  readonly errorRate: number | null;
}

export const speechRunSummary = (results: readonly QosSpeechResult[]): SpeechRunSummary => {
  const readings = results.filter((result) => result.modality === "speech");
  const transcriptions = results.filter((result) => result.modality === "transcription");
  return {
    readings: readings.length,
    transcriptions: transcriptions.length,
    rateable: readings.filter((result) => result.succeeded).length,
    rated: readings.filter((result) => result.reviews > 0).length,
    errorRate: average(
      transcriptions.flatMap((result) => {
        const errors = result.transcript === null ? null : characterErrors(result.text, result.transcript);
        return errors === null ? [] : [errors.rate];
      }),
    ),
  };
};

export const SPEECH_POLL_MS = 10_000;
export const SPEECH_START_POLL_MS = 4 * 60_000;

export const speechPollMs = (evaluationStartedAt: number | null, now: number): number | false =>
  evaluationStartedAt !== null && now - evaluationStartedAt < SPEECH_START_POLL_MS ? SPEECH_POLL_MS : false;
