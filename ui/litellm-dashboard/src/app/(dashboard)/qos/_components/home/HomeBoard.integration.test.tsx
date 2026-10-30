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

const target = (model: string) => ({
  model_group: model,
  deployments: [
    {
      model_id: `node-${model}`,
      provider: "openai",
      vendor: "moark",
      api_base: "https://api.moark.com/v1",
      upstream_model: model,
    },
  ],
});

const responses: Record<string, unknown> = {
  "/qos/targets": { models: [target("GLM-5.3"), target("Qwen3")] },
  "/qos/summary": {
    start_time: "",
    end_time: "",
    tag: null,
    model_groups: [group("GLM-5.3"), group("Qwen3")],
    deployments: ["GLM-5.3", "Qwen3"].map((name) => ({
      ...group(name),
      model_id: `node-${name}`,
      model: name,
      vendor: "moark",
      api_base: "https://api.moark.com/v1",
    })),
  },
  "/qos/health": {
    start_time: "",
    end_time: "",
    nodes: [node("GLM-5.3", "healthy"), node("Qwen3", "unhealthy")],
    probes: [],
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

  it("shows current service health and places the unavailable channel first", async () => {
    renderWithProviders(<HomeBoard accessToken="token" />);

    expect(await screen.findByText("Some channels are unavailable")).toBeInTheDocument();
    const cards = within(screen.getByRole("region", { name: "Channel status" })).getAllByRole("article");
    expect(cards.map((card) => within(card).getByRole("heading").textContent)).toEqual(["Qwen3", "GLM-5.3"]);
    expect(within(cards[0]).getByText("Unavailable")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Operational")).toBeInTheDocument();
    expect(within(cards[1]).getByText("900 ms")).toBeInTheDocument();
    expect(within(cards[1]).getByText("2.00 s")).toBeInTheDocument();
  });

  it("keeps announcements and recent service events without requesting news", async () => {
    renderWithProviders(<HomeBoard accessToken="token" />);

    expect(await screen.findByText("Maintenance on Saturday")).toBeInTheDocument();
    expect(await screen.findByText("Qwen3 node unhealthy")).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/qos/home/news", expect.anything());
  });

  it("shows an unchecked channel as awaiting checks even when it has successful traffic", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/health" ? { start_time: "", end_time: "", nodes: [], probes: [] } : responses[path],
    );
    renderWithProviders(<HomeBoard accessToken="token" />);

    await screen.findByText("Awaiting health checks");
    const cards = within(screen.getByRole("region", { name: "Channel status" })).getAllByRole("article");
    for (const card of cards) {
      expect(within(card).getByText("Awaiting checks")).toBeInTheDocument();
      expect(within(card).getByText("No health check yet")).toBeInTheDocument();
    }
  });

  it("refreshes the channel list, health checks and request metrics with one action", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HomeBoard accessToken="token" />);
    await screen.findByText("Maintenance on Saturday");
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled());
    vi.mocked(apiClient.get).mockClear();

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() =>
      expect(new Set(vi.mocked(apiClient.get).mock.calls.map(([path]) => path))).toEqual(
        new Set(["/qos/targets", "/qos/health", "/qos/summary"]),
      ),
    );
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

  it("exposes a health-check loading failure without reporting an update time", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/qos/health") throw new Error("Health service unreachable");
      return responses[path];
    });
    renderWithProviders(<HomeBoard accessToken="token" />);

    expect(await screen.findByText("Service status unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Health service unreachable/)).toBeInTheDocument();
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
