import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosDashboard from "./QosDashboard";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn() } }));

const percentiles = (p95: number) => ({ p50: p95 / 2, p95, p99: p95 });

const overall = (requests: number, ttft: number) => ({
  requests,
  failed_requests: 0,
  output_tokens: 36000,
  output_tokens_per_second: 10,
  ttft_ms: percentiles(ttft),
  tpot_ms: percentiles(40),
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
});

const node = (model_name: string, latest_status: string, availability: number) => ({
  model_name,
  model_id: `node-${model_name}`,
  vendor: "moark",
  api_base: "https://api.moark.com/v1",
  upstream_model: model_name,
  checks: 10,
  failures: 0,
  availability,
  latest_status,
  last_error: null,
  last_failure_at: null,
  last_checked_at: "2026-10-26T10:00:00Z",
});

const respond = async (path: string) => {
  if (path === "/qos/trends") {
    return {
      start_time: "2026-10-26T10:00:00Z",
      end_time: "2026-10-26T11:00:00Z",
      bucket_seconds: 60,
      group_by: "model",
      current: overall(120, 900),
      previous: overall(100, 600),
      series: [],
    };
  }
  return {
    start_time: "2026-10-26T10:00:00Z",
    end_time: "2026-10-26T11:00:00Z",
    nodes: [node("steady", "healthy", 1), node("flaky", "unhealthy", 0.5)],
    probes: [],
  };
};

describe("QosDashboard", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockImplementation(respond);
  });

  it("shows the headline figures against the previous period and counts unhealthy nodes", async () => {
    renderWithProviders(<QosDashboard accessToken="token" range="1h" tag="" summary={undefined} refreshMs={false} />);

    expect(await screen.findByText("120")).toBeInTheDocument();
    expect(screen.getByText("20.0% vs previous period")).toBeInTheDocument();
    expect(screen.getByText("50.0% vs previous period")).toBeInTheDocument();
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();
  });

  it("lists nodes needing attention first", async () => {
    renderWithProviders(<QosDashboard accessToken="token" range="1h" tag="" summary={undefined} refreshMs={false} />);

    const rows = await screen.findAllByRole("listitem");
    expect(rows.map((row) => within(row).queryByText("flaky") !== null)).toEqual([true, false]);
    expect(within(rows[0]).getByText("Unhealthy")).toBeInTheDocument();
  });

  it("asks for one series per provider once the charts are grouped by provider", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosDashboard accessToken="token" range="1h" tag="" summary={undefined} refreshMs={false} />);
    await screen.findByText("120");

    await user.click(screen.getByRole("radio", { name: "By provider" }));

    const trendCalls = vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/qos/trends");
    expect(trendCalls.at(-1)?.[1]?.query?.group_by).toBe("deployment");
  });
});
