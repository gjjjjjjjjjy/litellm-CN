import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosHealthPanel from "./QosHealthPanel";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn() } }));

const health = {
  start_time: "2026-10-22T05:00:00Z",
  end_time: "2026-10-23T05:00:00Z",
  nodes: [
    {
      model_name: "GLM-5.3",
      model_id: "node-a",
      api_base: "https://ai.gitee.com/v1",
      upstream_model: "openai/GLM-5.3",
      checks: 9,
      failures: 1,
      availability: 8 / 9,
      latest_status: "unhealthy",
      last_error: "Timeout exceeded",
      last_failure_at: "2026-10-23T01:58:49Z",
      last_checked_at: "2026-10-23T05:14:25Z",
    },
    {
      model_name: "removed-model",
      model_id: "node-gone",
      api_base: "",
      upstream_model: "",
      checks: 2,
      failures: 0,
      availability: 1,
      latest_status: "healthy",
      last_error: null,
      last_failure_at: null,
      last_checked_at: "2026-10-23T03:00:00Z",
    },
  ],
  probes: [
    {
      model: "GLM-5.3",
      api_base: "https://ai.gitee.com/v1/",
      probes: 53,
      latency_ms: { p50: 1275, p95: 2075.2, p99: 4598.8 },
      last_probe_at: "2026-10-23T05:28:41Z",
    },
  ],
};

const rowContaining = (text: string): HTMLElement => {
  const row = screen.getAllByRole("row").find((candidate) => within(candidate).queryByText(text) !== null);
  if (row === undefined) throw new Error(`No table row contains ${text}`);
  return row;
};

describe("QosHealthPanel", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(health);
  });

  it("shows each node's availability, latest status and last error, and the probe latency", async () => {
    renderWithProviders(<QosHealthPanel accessToken="token" />);

    await screen.findByText("https://ai.gitee.com/v1");
    const glm = within(rowContaining("https://ai.gitee.com/v1"));
    expect(glm.getByText("Unhealthy")).toBeInTheDocument();
    expect(glm.getByText("88.9%")).toBeInTheDocument();
    expect(glm.getByText("Timeout exceeded")).toBeInTheDocument();

    const removed = within(rowContaining("node-gone"));
    expect(removed.getByText("Healthy")).toBeInTheDocument();
    expect(removed.getByText("100.0%")).toBeInTheDocument();

    expect(screen.getByText("1.27 s / 2.08 s")).toBeInTheDocument();
  });

  it("asks for the last 24 hours by default", async () => {
    renderWithProviders(<QosHealthPanel accessToken="token" />);
    await screen.findByText("https://ai.gitee.com/v1");

    const [path, options] = vi.mocked(apiClient.get).mock.calls[0];
    expect(path).toBe("/qos/health");
    const query = options?.query;
    expect(Date.parse(String(query?.end_time)) - Date.parse(String(query?.start_time))).toBe(24 * 60 * 60 * 1000);
  });
});
