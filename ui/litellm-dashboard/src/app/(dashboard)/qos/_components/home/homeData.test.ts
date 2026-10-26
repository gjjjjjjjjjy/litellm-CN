import { describe, expect, it } from "vitest";
import { activityLine, modelCards, modelStatus, overallStatus, relativeTimeLabel, requestVolume } from "./homeData";

const percentiles = (p95: number | null) => ({ p50: p95, p95, p99: p95 });

const metrics = (model_group: string, requests: number, failed_requests: number) => ({
  model_group,
  requests,
  failed_requests,
  streamed_requests: requests,
  output_tokens: 0,
  peak_concurrency: 1,
  first_request_at: "2026-10-26T00:00:00Z",
  last_response_at: "2026-10-26T01:00:00Z",
  requests_per_second: 0,
  output_tokens_per_second: 0,
  ttft_ms: percentiles(500),
  tpot_ms: percentiles(20),
  e2e_latency_ms: percentiles(1000),
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
});

const node = (model_name: string, latest_status: string, vendor = "moark") => ({
  model_name,
  model_id: `${model_name}-${vendor}`,
  vendor,
  api_base: "https://api.moark.com/v1",
  upstream_model: model_name,
  checks: 10,
  failures: 0,
  availability: 1,
  latest_status,
  last_error: null,
  last_failure_at: null,
  last_checked_at: "2026-10-26T00:00:00Z",
});

describe("model status", () => {
  it("is down only when every node failed, and degraded when some did or requests fail", () => {
    expect(modelStatus([node("a", "unhealthy"), node("a", "unhealthy", "openai")], metrics("a", 10, 0))).toBe("down");
    expect(modelStatus([node("a", "unhealthy"), node("a", "healthy", "openai")], metrics("a", 10, 0))).toBe("degraded");
    expect(modelStatus([node("a", "healthy")], metrics("a", 100, 6))).toBe("degraded");
    expect(modelStatus([node("a", "healthy")], metrics("a", 100, 4))).toBe("ok");
    expect(modelStatus([], undefined)).toBe("idle");
  });

  it("summarises the gateway by its worst model", () => {
    expect(overallStatus(["ok", "degraded", "ok"])).toBe("degraded");
    expect(overallStatus(["ok", "down"])).toBe("down");
    expect(overallStatus(["idle", "ok"])).toBe("ok");
    expect(overallStatus([])).toBe("idle");
  });
});

describe("model cards", () => {
  it("covers models seen in traffic or health checks and puts outages first", () => {
    const cards = modelCards(
      [metrics("busy", 10, 0), metrics("", 3, 0)],
      [node("broken", "unhealthy"), node("busy", "healthy", "ai.gitee.com")],
      undefined,
    );

    expect(cards.map((card) => [card.model, card.status])).toEqual([
      ["broken", "down"],
      ["busy", "ok"],
    ]);
    expect(cards[1].vendors).toEqual(["ai.gitee.com"]);
  });
});

describe("request volume", () => {
  it("adds every model's requests up per bucket in time order", () => {
    const point = (bucket_start: string, requests: number) => ({
      bucket_start,
      requests,
      failed_requests: 0,
      output_tokens: 0,
      ttft_ms: percentiles(null),
      tpot_ms: percentiles(null),
    });
    const trends = {
      start_time: "2026-10-26T00:00:00Z",
      end_time: "2026-10-27T00:00:00Z",
      bucket_seconds: 1800,
      group_by: "model" as const,
      current: { ...metrics("x", 0, 0), output_tokens_per_second: 0 },
      previous: { ...metrics("x", 0, 0), output_tokens_per_second: 0 },
      series: [
        {
          model_group: "a",
          model_id: "",
          vendor: "",
          api_base: "",
          points: [point("2026-10-26T01:00:00Z", 4), point("2026-10-26T00:30:00Z", 1)],
        },
        { model_group: "b", model_id: "", vendor: "", api_base: "", points: [point("2026-10-26T01:00:00Z", 6)] },
      ],
    };

    expect(requestVolume(trends).map((row) => row.requests)).toEqual([1, 10]);
  });
});

describe("feed text", () => {
  const now = new Date("2026-10-26T12:00:00Z");

  it("says how long ago something happened", () => {
    expect(relativeTimeLabel("2026-10-26T11:59:40Z", now)).toBe("just now");
    expect(relativeTimeLabel("2026-10-26T11:15:00Z", now)).toBe("45 min ago");
    expect(relativeTimeLabel("2026-10-26T07:00:00Z", now)).toBe("5 h ago");
    expect(relativeTimeLabel("2026-10-23T12:00:00Z", now)).toBe("3 d ago");
  });

  it("flags a benchmark with cross-talk as an error and a recovered node as good news", () => {
    const benchmark = {
      kind: "benchmark" as const,
      at: "2026-10-26T10:00:00Z",
      model: "GLM-5.3",
      run_id: "qos-1",
      requests: 40,
      failed_requests: 0,
      crosstalk_responses: 2,
    };
    expect(activityLine(benchmark)).toEqual({
      tone: "error",
      title: "GLM-5.3 benchmark, 40 requests",
      description: "2 responses crossed with other requests",
    });
    const recovered = {
      kind: "node_recovered" as const,
      at: "2026-10-26T10:00:00Z",
      model: "GLM-5.3",
      model_id: "a",
      vendor: "moark",
      error: null,
    };
    expect(activityLine(recovered).tone).toBe("success");
  });
});
