import { describe, expect, it } from "vitest";
import {
  deploymentsFor,
  formatMs,
  formatPercentiles,
  isQosRange,
  nodeLabel,
  qosWindow,
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
  });
});
