import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomeBoard from "./HomeBoard";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const authorized = vi.hoisted(() => ({ userRole: "Admin", isViewOnly: false }));
vi.mock("@/app/(dashboard)/hooks/useAuthorized", () => ({ default: () => authorized }));

const percentiles = (p95: number) => ({ p50: p95 / 2, p95, p99: p95 });

const overall = (requests: number) => ({
  requests,
  failed_requests: 0,
  output_tokens: 1000,
  output_tokens_per_second: 12,
  ttft_ms: percentiles(900),
  tpot_ms: percentiles(40),
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
});

const group = (model_group: string) => ({
  model_group,
  requests: 50,
  failed_requests: 0,
  streamed_requests: 50,
  output_tokens: 1000,
  peak_concurrency: 4,
  first_request_at: "2026-10-26T00:00:00Z",
  last_response_at: "2026-10-26T01:00:00Z",
  requests_per_second: 1,
  output_tokens_per_second: 12,
  ttft_ms: percentiles(900),
  tpot_ms: percentiles(40),
  e2e_latency_ms: percentiles(2000),
  response_checks: { checked: 0, crosstalk: 0, marker_missing: 0 },
});

const node = (model_name: string, latest_status: string) => ({
  model_name,
  model_id: `node-${model_name}`,
  vendor: "moark",
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

const responses: Record<string, unknown> = {
  "/qos/summary": {
    start_time: "",
    end_time: "",
    tag: null,
    model_groups: [group("GLM-5.3"), group("Qwen3")],
    deployments: [],
  },
  "/qos/trends": {
    start_time: "2026-10-25T12:00:00Z",
    end_time: "2026-10-26T12:00:00Z",
    bucket_seconds: 1800,
    group_by: "model",
    current: overall(150),
    previous: overall(100),
    series: [],
  },
  "/qos/health": {
    start_time: "",
    end_time: "",
    nodes: [node("GLM-5.3", "healthy"), node("Qwen3", "unhealthy")],
    probes: [],
  },
  "/qos/home/news": {
    items: [
      {
        source: "量子位",
        title: "New open model tops the leaderboard",
        link: "https://news.example/a",
        summary: "",
        published_at: null,
      },
    ],
    sources: [
      { name: "量子位", url: "https://news.example/rss", items: 1, error: null, fetched_at: "2026-10-26T12:00:00Z" },
      {
        name: "OpenAI",
        url: "https://openai.example/rss",
        items: 0,
        error: "ConnectTimeout",
        fetched_at: "2026-10-26T12:00:00Z",
      },
    ],
  },
  "/qos/announcements": {
    announcements: [
      {
        id: "a1",
        title: "Maintenance on Saturday",
        body: "02:00-04:00",
        author: "admin@example.com",
        created_at: "2026-10-26T11:00:00Z",
      },
    ],
  },
  "/qos/home/activity": {
    events: [
      {
        kind: "node_down",
        at: "2026-10-26T11:30:00Z",
        model: "Qwen3",
        model_id: "node-Qwen3",
        vendor: "moark",
        error: "Connection error.",
      },
    ],
  },
};

describe("HomeBoard", () => {
  beforeEach(() => {
    testQueryClient.clear();
    authorized.userRole = "Admin";
    authorized.isViewOnly = false;
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.delete).mockReset();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => responses[path]);
  });

  it("puts the outage in the banner, the headline figures up top and the broken model first", async () => {
    renderWithProviders(<HomeBoard accessToken="token" />);

    expect(await screen.findByText("Service outage")).toBeInTheDocument();
    expect(await screen.findByText("150")).toBeInTheDocument();
    expect(screen.getByText("+50.0% vs previous 24 h")).toBeInTheDocument();
    const models = screen
      .getAllByRole("article")
      .map((card) => within(card).getAllByText(/GLM-5.3|Qwen3/)[0].textContent);
    expect(models).toEqual(["Qwen3", "GLM-5.3"]);
  });

  it("shows announcements, news with the feeds that failed, and recent activity", async () => {
    renderWithProviders(<HomeBoard accessToken="token" />);

    expect(await screen.findByText("Maintenance on Saturday")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /New open model tops the leaderboard/ })).toHaveAttribute(
      "href",
      "https://news.example/a",
    );
    expect(screen.getByText("Could not reach OpenAI")).toBeInTheDocument();
    expect(await screen.findByText("Qwen3 node unhealthy")).toBeInTheDocument();
  });

  it("lets an admin post an announcement", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({ announcements: [] });
    renderWithProviders(<HomeBoard accessToken="token" />);

    await user.click(await screen.findByRole("button", { name: "Post" }));
    await user.type(screen.getByLabelText("Title"), "Benchmarks paused");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Post" }));

    expect(apiClient.post).toHaveBeenCalledWith("/qos/announcements", {
      accessToken: "token",
      body: { title: "Benchmarks paused", body: "" },
    });
  });

  it("deletes an announcement only after the admin confirms", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockResolvedValue({ announcements: [] });
    renderWithProviders(<HomeBoard accessToken="token" />);

    await user.click(await screen.findByRole("button", { name: "Delete announcement" }));
    expect(apiClient.delete).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));

    expect(apiClient.delete).toHaveBeenCalledWith("/qos/announcements/a1", { accessToken: "token" });
    await waitFor(() => expect(screen.queryByText("Maintenance on Saturday")).not.toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("keeps the confirmation open with the reason when deleting fails", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Announcement a1 not found"));
    renderWithProviders(<HomeBoard accessToken="token" />);

    await user.click(await screen.findByRole("button", { name: "Delete announcement" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));

    expect(await within(screen.getByRole("alertdialog")).findByText("Announcement a1 not found")).toBeInTheDocument();
  });

  it("shows no update time before the summary has ever loaded", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/qos/summary") throw new Error("down");
      return responses[path];
    });
    renderWithProviders(<HomeBoard accessToken="token" />);

    await screen.findByText("Maintenance on Saturday");
    await waitFor(() => expect(screen.queryByText("Refreshing")).not.toBeInTheDocument());
    expect(screen.queryByText(/^Updated /)).not.toBeInTheDocument();
  });

  it("offers no posting or deleting to other users", async () => {
    authorized.userRole = "Internal User";
    renderWithProviders(<HomeBoard accessToken="token" />);

    await screen.findByText("Maintenance on Saturday");
    expect(screen.queryByRole("button", { name: "Post" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete announcement" })).not.toBeInTheDocument();
  });
});
