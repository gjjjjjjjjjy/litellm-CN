import { screen, waitFor, within } from "@testing-library/react";
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
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
};

const summary = {
  start_time: "2026-10-22T11:00:00",
  end_time: "2026-10-22T12:00:00",
  tag: null,
  model_groups: [{ ...metrics, model_group: "qwen3-max" }],
  deployments: [
    {
      ...metrics,
      model_group: "qwen3-max",
      model_id: "node-a",
      model: "moark/qwen3.8-max",
      api_base: "https://node-a/v1",
      vendor: "moark",
    },
    {
      ...metrics,
      model_group: "qwen3-max",
      model_id: "node-b",
      model: "moark/qwen3.8-max",
      api_base: "https://node-b/v1",
      vendor: "moark",
      peak_concurrency: 9,
    },
  ],
};

const overall = {
  requests: 100,
  failed_requests: 1,
  output_tokens: 36000,
  output_tokens_per_second: 10,
  ttft_ms: { p50: 300, p95: 900, p99: 1200 },
  tpot_ms: { p50: 20, p95: 40, p99: 60 },
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
};

const trends = {
  start_time: "2026-10-22T11:00:00Z",
  end_time: "2026-10-22T12:00:00Z",
  bucket_seconds: 60,
  group_by: "model",
  current: overall,
  previous: overall,
  series: [],
};

const health = { start_time: "2026-10-22T11:00:00Z", end_time: "2026-10-22T12:00:00Z", nodes: [], probes: [] };

const respondWith = (summaryBody: unknown) => async (path: string) => {
  if (path === "/qos/trends") return trends;
  if (path === "/qos/health") return health;
  return summaryBody;
};

const summaryCalls = () => vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/qos/summary");

describe("QosView", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockImplementation(respondWith(summary));
  });

  it("shows per-model service quality and reveals each node's metrics on expand", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosView accessToken="token" />);

    const details = within(await screen.findByRole("table"));
    expect(await details.findByText("qwen3-max")).toBeInTheDocument();
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
    await within(await screen.findByRole("table")).findByText("qwen3-max");

    const firstQuery = summaryCalls()[0][1]?.query;
    const span = Date.parse(String(firstQuery?.end_time)) - Date.parse(String(firstQuery?.start_time));
    expect(span).toBe(60 * 60 * 1000);
    expect(firstQuery?.tag).toBeUndefined();

    await user.type(screen.getByLabelText("Request tag"), " qos-run-1 ");
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(summaryCalls()).toHaveLength(2));
    expect(summaryCalls()[1][1]?.query?.tag).toBe("qos-run-1");
  });

  it("names traffic that has no public model name instead of leaving the model blank", async () => {
    vi.mocked(apiClient.get).mockImplementation(
      respondWith({ ...summary, model_groups: [{ ...metrics, model_group: "" }], deployments: [] }),
    );
    renderWithProviders(<QosView accessToken="token" />);
    expect(await screen.findByText("No public model name")).toBeInTheDocument();
  });

  it("switches the summary, trends and health to all retained history and back to a fixed range", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosView accessToken="token" />);
    await within(await screen.findByRole("table")).findByText("qwen3-max");

    await user.click(screen.getByLabelText("Time range"));
    await user.click(await screen.findByRole("option", { name: "All", exact: true }));

    await waitFor(() => expect(summaryCalls().at(-1)?.[1]?.query?.all_time).toBe(true));
    for (const path of ["/qos/summary", "/qos/trends", "/qos/health"]) {
      const call = vi
        .mocked(apiClient.get)
        .mock.calls.filter(([called]) => called === path)
        .at(-1);
      expect(call?.[1]?.query).toEqual(expect.objectContaining({ all_time: true }));
      expect(call?.[1]?.query?.start_time).toBeUndefined();
    }
    expect(screen.getByLabelText("Time range")).toHaveTextContent("All");

    await user.click(screen.getByLabelText("Time range"));
    await user.click(await screen.findByRole("option", { name: "Last 7 days" }));

    await waitFor(() => expect(screen.getByLabelText("Time range")).toHaveTextContent("Last 7 days"));
    const query = summaryCalls().at(-1)?.[1]?.query;
    expect(query?.all_time).toBeUndefined();
    expect(Date.parse(String(query?.end_time)) - Date.parse(String(query?.start_time))).toBe(7 * 24 * 60 * 60 * 1000);
  });

  it("shows the server's error message when loading fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Only proxy admins can view service quality metrics"));
    renderWithProviders(<QosView accessToken="token" />);
    expect(await screen.findByText("Only proxy admins can view service quality metrics")).toBeInTheDocument();
  });
});
