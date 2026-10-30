import { describe, expect, it } from "vitest";
import { activityLine, channelCards, modelStatus, overallStatus, relativeTimeLabel } from "./homeData";

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
  last_ttft_ms: null,
  last_latency_ms: null,
  last_streamed_at: null,
});

describe("model status", () => {
  it("summarises the latest health checks of the model's nodes", () => {
    expect(modelStatus([node("a", "unhealthy"), node("a", "unhealthy", "openai")])).toBe("down");
    expect(modelStatus([node("a", "unhealthy"), node("a", "healthy", "openai")])).toBe("degraded");
    expect(modelStatus([node("a", "healthy")])).toBe("ok");
    expect(modelStatus([])).toBe("idle");
  });

  it("summarises the gateway by its worst model", () => {
    expect(overallStatus(["ok", "degraded", "ok"])).toBe("degraded");
    expect(overallStatus(["ok", "down"])).toBe("down");
    expect(overallStatus(["idle", "ok"])).toBe("idle");
    expect(overallStatus([])).toBe("idle");
  });
});

describe("channel cards", () => {
  it("keeps two endpoints of the same provider separate, puts failures first and includes unchecked deployments", () => {
    const deployment = (model_id: string, api_base: string) => ({
      model_id,
      api_base,
      provider: "openai",
      vendor: "moark",
      upstream_model: "shared-upstream",
    });
    const old = deployment("old", "https://ai.gitee.com/v1");
    const current = deployment("current", "https://api.moark.com/v1");
    const unchecked = deployment("unchecked", "https://pending.example/v1");
    const cards = channelCards(
      [{ model_group: "chat", deployments: [current, unchecked, old] }],
      [
        { ...node("chat", "healthy"), model_id: "current" },
        { ...node("chat", "unhealthy"), model_id: "old" },
        { ...node("retired", "unhealthy"), model_id: "retired" },
      ],
    );

    expect(cards.map((card) => [card.deployment.model_id, card.status])).toEqual([
      ["old", "down"],
      ["current", "ok"],
      ["unchecked", "idle"],
    ]);
    expect(cards[0].deployment.api_base).toBe(old.api_base);
    expect(cards[1].deployment.api_base).toBe(current.api_base);
    expect(cards[2].health).toBeUndefined();
  });

  it("matches health to both the configured model name and deployment id", () => {
    const deployment = {
      model_id: "shared",
      api_base: "https://endpoint.example/v1",
      provider: "openai",
      vendor: "moark",
      upstream_model: "upstream",
    };
    const cards = channelCards(
      [{ model_group: "beta", deployments: [deployment] }],
      [{ ...node("alpha", "unhealthy"), model_id: "shared" }],
    );
    expect(cards[0].status).toBe("idle");
    expect(cards[0].health).toBeUndefined();
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
