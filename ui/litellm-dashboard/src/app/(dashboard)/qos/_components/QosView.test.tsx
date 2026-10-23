import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosView from "./QosView";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn() } }));

const metrics = {
  requests: 40,
  failed_requests: 2,
  streamed_requests: 38,
  output_tokens: 8000,
  peak_concurrency: 16,
  first_request_at: "2026-10-22T11:00:00",
  last_response_at: "2026-10-22T11:00:20",
  requests_per_second: 2,
  output_tokens_per_second: 400,
  ttft_ms: { p50: 210, p95: 480, p99: 610 },
  tpot_ms: { p50: 22, p95: 35, p99: 41 },
  e2e_latency_ms: { p50: 4600, p95: 7900, p99: 9100 },
};

const summary = {
  start_time: "2026-10-22T11:00:00",
  end_time: "2026-10-22T12:00:00",
  tag: null,
  model_groups: [{ ...metrics, model_group: "qwen3-max" }],
  deployments: [
    { ...metrics, model_group: "qwen3-max", model_id: "node-a", model: "moark/qwen3.8-max", api_base: "https://node-a/v1" },
    { ...metrics, model_group: "qwen3-max", model_id: "node-b", model: "moark/qwen3.8-max", api_base: "https://node-b/v1", peak_concurrency: 9 },
  ],
};

describe("QosView", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(summary);
  });

  it("shows per-model service quality and reveals each node's metrics on expand", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosView accessToken="token" />);

    expect(await screen.findByText("qwen3-max")).toBeInTheDocument();
    expect(screen.getByLabelText("Time range")).toHaveTextContent("Last hour");
    expect(screen.getByText("95.0%")).toBeInTheDocument();
    expect(screen.getAllByText("210 ms / 480 ms")).toHaveLength(1);
    expect(screen.queryByText("https://node-a/v1")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show nodes" }));

    expect(screen.getByText("https://node-a/v1")).toBeInTheDocument();
    expect(screen.getByText("https://node-b/v1")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("queries the last hour by default and adds the request tag on refresh", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosView accessToken="token" />);
    await screen.findByText("qwen3-max");

    const firstQuery = vi.mocked(apiClient.get).mock.calls[0][1]?.query;
    const span = Date.parse(String(firstQuery?.end_time)) - Date.parse(String(firstQuery?.start_time));
    expect(span).toBe(60 * 60 * 1000);
    expect(firstQuery?.tag).toBeUndefined();

    await user.type(screen.getByLabelText("Request tag"), " qos-run-1 ");
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.get).mock.calls[1][1]?.query?.tag).toBe("qos-run-1");
  });

  it("shows the server's error message when loading fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Only proxy admins can view service quality metrics"));
    renderWithProviders(<QosView accessToken="token" />);
    expect(await screen.findByText("Only proxy admins can view service quality metrics")).toBeInTheDocument();
  });
});
