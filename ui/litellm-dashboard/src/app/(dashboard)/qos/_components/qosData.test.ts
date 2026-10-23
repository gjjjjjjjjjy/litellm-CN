import { describe, expect, it } from "vitest";
import {
  checkBenchmarkPlan,
  deploymentsFor,
  formatMs,
  formatPercentiles,
  isQosRange,
  nodeLabel,
  parseConcurrency,
  qosWindow,
  recordedRequests,
  successRate,
  type QosDeploymentMetrics,
  type QosSummary,
} from "./qosData";

const metrics = {
  model_group: "qwen3-max",
  requests: 40,
  failed_requests: 2,
  streamed_requests: 38,
  output_tokens: 8000,
  peak_concurrency: 16,
  first_request_at: "2026-10-22T11:00:00",
  last_response_at: "2026-10-22T11:00:20",
  requests_per_second: 2,
  output_tokens_per_second: 400,
  ttft_ms: { p50: 210, p95: 1480.5, p99: null },
  tpot_ms: { p50: 22, p95: 35, p99: 41 },
  e2e_latency_ms: { p50: 4600, p95: 7900, p99: 9100 },
};

const deployment = (model_group: string, model_id: string, api_base: string): QosDeploymentMetrics => ({
  ...metrics,
  model_group,
  model_id,
  model: "moark/qwen3.8-max",
  api_base,
});

describe("qosData", () => {
  it("builds a window that ends now and spans the selected range", () => {
    const now = new Date("2026-10-22T12:00:00Z");
    expect(qosWindow("15m", now)).toEqual({ start_time: "2026-10-22T11:45:00.000Z", end_time: "2026-10-22T12:00:00.000Z" });
    expect(qosWindow("7d", now).start_time).toBe("2026-10-15T12:00:00.000Z");
  });

  it("only accepts known range values", () => {
    expect(isQosRange("1h")).toBe(true);
    expect(isQosRange("2h")).toBe(false);
  });

  it("computes success rate from failures and leaves an empty window undefined", () => {
    expect(successRate(metrics)).toBeCloseTo(0.95);
    expect(successRate({ ...metrics, requests: 0, failed_requests: 0 })).toBeNull();
  });

  it("formats latencies in ms below a second and seconds above, with a dash for missing values", () => {
    expect(formatMs(210)).toBe("210 ms");
    expect(formatMs(4.25)).toBe("4.3 ms");
    expect(formatMs(1480.5)).toBe("1.48 s");
    expect(formatMs(null)).toBe("-");
    expect(formatPercentiles(metrics.ttft_ms)).toBe("210 ms / 1.48 s");
  });

  it("lists a model's nodes and labels each by its API base, or its model id when the base is unknown", () => {
    const summary: QosSummary = {
      start_time: "2026-10-22T11:00:00",
      end_time: "2026-10-22T12:00:00",
      tag: null,
      model_groups: [metrics],
      deployments: [deployment("qwen3-max", "a", "https://node-a/v1"), deployment("other", "b", ""), deployment("qwen3-max", "c", "")],
    };
    expect(deploymentsFor(summary, "qwen3-max").map(nodeLabel)).toEqual(["https://node-a/v1", "c"]);
    expect(nodeLabel(deployment("", "", ""))).toBe("Unknown node");
  });
});

describe("benchmark plan", () => {
  const valid = { model: "qwen3-max", concurrency: "1, 4，16", requestsPerWorker: "8", maxTokens: "512" };

  it("parses concurrency levels separated by commas, Chinese commas or spaces", () => {
    expect(parseConcurrency(" 1, 4，16  32")).toEqual({ ok: true, levels: [1, 4, 16, 32] });
  });

  it("rejects empty, fractional, out-of-range or too many concurrency levels", () => {
    expect(parseConcurrency(" ").ok).toBe(false);
    expect(parseConcurrency("1.5").ok).toBe(false);
    expect(parseConcurrency("0").ok).toBe(false);
    expect(parseConcurrency("257").ok).toBe(false);
    expect(parseConcurrency("1 2 3 4 5 6 7 8 9").ok).toBe(false);
  });

  it("builds the request plan and counts every request it will send", () => {
    expect(checkBenchmarkPlan(valid)).toEqual({
      ok: true,
      total: (1 + 4 + 16) * 8,
      plan: { model_group: "qwen3-max", concurrency: [1, 4, 16], requests_per_worker: 8, max_tokens: 512 },
    });
  });

  it("explains which field blocks the plan", () => {
    expect(checkBenchmarkPlan({ ...valid, model: "" })).toEqual({ ok: false, message: "Choose a model to test" });
    expect(checkBenchmarkPlan({ ...valid, requestsPerWorker: "51" })).toEqual({
      ok: false,
      message: "Requests per worker must be from 1 to 50",
    });
    expect(checkBenchmarkPlan({ ...valid, maxTokens: "" })).toEqual({
      ok: false,
      message: "Max output tokens must be from 1 to 8192",
    });
    expect(checkBenchmarkPlan({ ...valid, concurrency: "256 256", requestsPerWorker: "10" })).toEqual({
      ok: false,
      message: "This plan sends 5120 requests; the limit is 5000",
    });
  });

  it("sums recorded requests across levels for progress", () => {
    const level = { ...metrics, concurrency: 1 };
    expect(recordedRequests({ run_id: "qos-x", levels: [level, { ...level, concurrency: 4, requests: 10 }], deployments: [] })).toBe(50);
  });
});
