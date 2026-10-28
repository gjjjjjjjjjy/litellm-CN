import { describe, expect, it } from "vitest";
import { compareBars, headlines, seriesLabel, trendChart, type QosOverall, type QosTrends } from "./dashboardData";

const percentiles = (p95: number | null) => ({ p50: p95, p95, p99: p95 });

const point = (bucket_start: string, ttft: number | null, requests = 10, failed_requests = 0) => ({
  bucket_start,
  requests,
  failed_requests,
  output_tokens: 1000,
  ttft_ms: percentiles(ttft),
  tpot_ms: percentiles(20),
});

const overall = (requests: number, ttft: number | null, tokensPerSecond: number): QosOverall => ({
  requests,
  failed_requests: 0,
  output_tokens: 0,
  output_tokens_per_second: tokensPerSecond,
  ttft_ms: percentiles(ttft),
  tpot_ms: percentiles(20),
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
});

const trends = (series: QosTrends["series"]): QosTrends => ({
  start_time: "2026-10-26T10:00:00Z",
  end_time: "2026-10-26T11:00:00Z",
  bucket_seconds: 60,
  group_by: "model",
  current: overall(0, null, 0),
  previous: overall(0, null, 0),
  series,
});

describe("trendChart", () => {
  it("puts each series in its own column and leaves a gap where it had no traffic", () => {
    const chart = trendChart(
      trends([
        {
          model_group: "GLM-5.3",
          model_id: "",
          vendor: "",
          api_base: "",
          points: [point("2026-10-26T10:00:00Z", 300), point("2026-10-26T10:01:00Z", 500)],
        },
        { model_group: "Qwen3", model_id: "", vendor: "", api_base: "", points: [point("2026-10-26T10:01:00Z", 200)] },
      ]),
      "ttft",
    );

    expect(chart.categories).toEqual(["GLM-5.3", "Qwen3"]);
    expect(chart.rows.map(({ time: _time, ...values }) => values)).toEqual([
      { "GLM-5.3": 300, Qwen3: null },
      { "GLM-5.3": 500, Qwen3: 200 },
    ]);
  });

  it("reports the success rate as a percentage of each bucket's requests", () => {
    const chart = trendChart(
      trends([
        {
          model_group: "GLM-5.3",
          model_id: "",
          vendor: "",
          api_base: "",
          points: [point("2026-10-26T10:00:00Z", 300, 20, 5)],
        },
      ]),
      "success",
    );
    expect(chart.rows[0]["GLM-5.3"]).toBe(75);
  });

  it("names a provider series after its model and vendor", () => {
    const providerSeries = { model_group: "GLM-5.3", model_id: "node-a", vendor: "moark", api_base: "", points: [] };
    expect(seriesLabel(providerSeries)).toBe("GLM-5.3 · Moark (Gitee AI)");
  });

  it("includes the year when all history spans the same calendar date in different years", () => {
    const history = {
      ...trends([
        {
          model_group: "GLM-5.3",
          model_id: "",
          vendor: "",
          api_base: "",
          points: [point("2025-10-26T12:00:00Z", 300), point("2026-10-26T12:00:00Z", 500)],
        },
      ]),
      start_time: "2025-10-01T12:00:00Z",
      end_time: "2026-10-27T12:00:00Z",
      bucket_seconds: 86400,
    };
    expect(trendChart(history, "ttft").rows.map((row) => row.time)).toEqual(["2025-10-26", "2026-10-26"]);
  });
});

describe("headlines", () => {
  it("marks a slower TTFT as worse and more throughput as better than the previous period", () => {
    const byKey = Object.fromEntries(headlines(overall(120, 900, 12), overall(100, 600, 10)).map((h) => [h.key, h]));

    expect(byKey.requests.change).toEqual({ percent: 20, better: true });
    expect(byKey.ttft.change).toEqual({ percent: 50, better: false });
    expect(byKey.throughput.change?.better).toBe(true);
  });

  it("has nothing to compare with when the previous period was empty", () => {
    const byKey = Object.fromEntries(headlines(overall(120, 900, 12), overall(0, null, 0)).map((h) => [h.key, h]));
    expect(byKey.requests.change).toBeNull();
    expect(byKey.ttft.change).toBeNull();
  });
});

describe("compareBars", () => {
  const metrics = (model_group: string, ttft: number | null, tokensPerSecond: number) => ({
    model_group,
    requests: 10,
    failed_requests: 0,
    streamed_requests: 10,
    output_tokens: 100,
    peak_concurrency: 1,
    first_request_at: "2026-10-26T10:00:00Z",
    last_response_at: "2026-10-26T10:01:00Z",
    requests_per_second: 1,
    output_tokens_per_second: tokensPerSecond,
    ttft_ms: percentiles(ttft),
    tpot_ms: percentiles(20),
    e2e_latency_ms: percentiles(1000),
    response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
  });

  it("ranks latency lowest first and throughput highest first, leaving out models without data", () => {
    const rows = [metrics("slow", 900, 50), metrics("fast", 300, 10), metrics("silent", null, 0)];
    expect(compareBars(rows, "ttft").map((bar) => bar.name)).toEqual(["fast", "slow"]);
    expect(compareBars(rows, "throughput").map((bar) => bar.name)).toEqual(["slow", "fast", "silent"]);
  });

  it("labels each provider of a model with its vendor", () => {
    const deployment = {
      ...metrics("GLM-5.3", 300, 10),
      model_id: "node-a",
      model: "GLM-5.3",
      api_base: "",
      vendor: "ai.gitee.com",
    };
    expect(compareBars([deployment], "ttft")[0].name).toBe("GLM-5.3 · ai.gitee.com");
  });
});
