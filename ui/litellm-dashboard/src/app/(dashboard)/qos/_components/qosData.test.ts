import { describe, expect, it } from "vitest";
import {
  checkBenchmarkPlan,
  comparesProviders,
  deploymentIdsFor,
  deploymentsFor,
  formatMs,
  formatPercentiles,
  isQosRange,
  nodeLabel,
  parseConcurrency,
  parseTargetChoice,
  providerLabel,
  qosWindow,
  recordedRequests,
  successRate,
  interferenceLabel,
  otherTraffic,
  responseCheckBadge,
  targetChoiceValue,
  type QosDeploymentMetrics,
  type QosSummary,
  type TargetChoice,
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
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
};

const deployment = (model_group: string, model_id: string, api_base: string): QosDeploymentMetrics => ({
  ...metrics,
  model_group,
  model_id,
  model: "moark/qwen3.8-max",
  api_base,
  vendor: "moark",
});

describe("qosData", () => {
  it("builds a window that ends now and spans the selected range", () => {
    const now = new Date("2026-10-22T12:00:00Z");
    expect(qosWindow("15m", now)).toEqual({
      start_time: "2026-10-22T11:45:00.000Z",
      end_time: "2026-10-22T12:00:00.000Z",
    });
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
      deployments: [
        deployment("qwen3-max", "a", "https://node-a/v1"),
        deployment("other", "b", ""),
        deployment("qwen3-max", "c", ""),
      ],
    };
    expect(deploymentsFor(summary, "qwen3-max").map(nodeLabel)).toEqual(["https://node-a/v1", "c"]);
    expect(nodeLabel(deployment("", "", ""))).toBe("Unknown node");
  });
});

describe("benchmark plan", () => {
  const valid = {
    model: "qwen3-max",
    deploymentIds: [],
    concurrency: "1, 4，16",
    requestsPerWorker: "8",
    maxTokens: "512",
  };

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
      plan: {
        model_group: "qwen3-max",
        deployment_ids: [],
        concurrency: [1, 4, 16],
        requests_per_worker: 8,
        max_tokens: 512,
      },
    });
  });

  it("runs the whole plan once per compared provider and counts it toward the limit", () => {
    const comparison = checkBenchmarkPlan({ ...valid, deploymentIds: ["node-a", "node-b"] });
    expect(comparison.ok && comparison.total).toBe((1 + 4 + 16) * 8 * 2);
    expect(comparison.ok && comparison.plan.deployment_ids).toEqual(["node-a", "node-b"]);
    const tooLarge = { ...valid, concurrency: "256", requestsPerWorker: "10", deploymentIds: ["a", "b"] };
    expect(checkBenchmarkPlan(tooLarge)).toEqual({
      ok: false,
      message: "This plan sends 5120 requests; the limit is 5000",
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
    const level = { ...metrics, concurrency: 1, interference: { same_deployment: 0, same_endpoint: 0 } };
    const detail = {
      run_id: "qos-x",
      levels: [level, { ...level, concurrency: 4, requests: 10 }],
      deployments: [],
      deployment_levels: [],
    };
    expect(recordedRequests(detail)).toBe(50);
  });
});

describe("benchmark targets", () => {
  const moark = {
    model_id: "node-moark",
    provider: "moark",
    vendor: "moark",
    api_base: "https://api.moark.com/v1",
    upstream_model: "Qwen3-Max",
  };
  const gitee = {
    model_id: "node-gitee",
    provider: "openai",
    vendor: "ai.gitee.com",
    api_base: "https://ai.gitee.com/v1",
    upstream_model: "Qwen3-Max",
  };

  it("labels a deployment with its vendor and endpoint, or with its vendor alone when it has no endpoint", () => {
    expect(providerLabel(moark)).toBe("Moark (Gitee AI) · https://api.moark.com/v1");
    expect(providerLabel({ ...moark, api_base: "moark" })).toBe("Moark (Gitee AI)");
    expect(providerLabel(gitee)).toBe("ai.gitee.com · https://ai.gitee.com/v1");
  });

  it("round-trips every target choice through its select value", () => {
    const choices: TargetChoice[] = [
      { kind: "balanced" },
      { kind: "compare" },
      { kind: "deployment", modelId: "node:1" },
    ];
    expect(choices.map((choice) => parseTargetChoice(targetChoiceValue(choice)))).toEqual(choices);
    expect(() => parseTargetChoice("node-moark")).toThrow();
  });

  it("sends no deployment ids to load-balance, one to test a provider, and all of them to compare", () => {
    expect(deploymentIdsFor({ kind: "balanced" }, [moark, gitee])).toEqual([]);
    expect(deploymentIdsFor({ kind: "deployment", modelId: "node-gitee" }, [moark, gitee])).toEqual(["node-gitee"]);
    expect(deploymentIdsFor({ kind: "compare" }, [moark, gitee])).toEqual(["node-moark", "node-gitee"]);
  });

  it("treats a run as a provider comparison only when more than one provider answered", () => {
    const quiet = { same_deployment: 0, same_endpoint: 0 };
    const level = { ...metrics, concurrency: 1, model: "Qwen3-Max", api_base: "", vendor: "", interference: quiet };
    const detail = { run_id: "qos-x", levels: [], deployments: [] };
    expect(
      comparesProviders({
        ...detail,
        deployment_levels: [
          { ...level, model_id: "a" },
          { ...level, model_id: "a", concurrency: 4 },
        ],
      }),
    ).toBe(false);
    expect(
      comparesProviders({
        ...detail,
        deployment_levels: [
          { ...level, model_id: "a" },
          { ...level, model_id: "b" },
        ],
      }),
    ).toBe(true);
  });
});

describe("cross-talk and interference", () => {
  it("leaves responses that were never checked blank", () => {
    expect(responseCheckBadge({ checked: 0, crosstalk: 0, marker_missing: 0 })).toBeNull();
  });

  it("reports cross-talk before missing codes, and passes only clean levels", () => {
    expect(responseCheckBadge({ checked: 12, crosstalk: 2, marker_missing: 3 })).toMatchObject({
      tone: "error",
      label: "2 cross-talk",
    });
    expect(responseCheckBadge({ checked: 12, crosstalk: 0, marker_missing: 3 })).toMatchObject({
      tone: "warning",
      label: "3 without code",
    });
    expect(responseCheckBadge({ checked: 12, crosstalk: 0, marker_missing: 0 })).toMatchObject({
      tone: "success",
      label: "12 passed",
    });
  });

  it("adds up outside traffic on the deployment and on its endpoint", () => {
    const interference = { same_deployment: 4, same_endpoint: 2 };
    expect(otherTraffic(interference)).toBe(6);
    expect(interferenceLabel(interference)).toBe("4 on this deployment · 2 on its endpoint");
  });
});
