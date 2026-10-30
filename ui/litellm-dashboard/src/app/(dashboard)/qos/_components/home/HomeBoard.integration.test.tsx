import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomeBoard from "./HomeBoard";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

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
  last_ttft_ms: model_name === "Qwen3" ? null : 900,
  last_latency_ms: model_name === "Qwen3" ? null : 2000,
  last_streamed_at: model_name === "Qwen3" ? null : "2026-10-26T00:00:00Z",
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
  "/qos/health": {
    start_time: "",
    end_time: "",
    nodes: [node("GLM-5.3", "healthy"), node("Qwen3", "unhealthy")],
    probes: [],
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
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => responses[path]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows current service health and places the unavailable channel first", async () => {
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={false} />);

    expect(await screen.findByText("Some channels are unavailable")).toBeInTheDocument();
    const cards = within(screen.getByRole("region", { name: "Channel status" })).getAllByRole("article");
    expect(cards.map((card) => within(card).getByRole("heading").textContent)).toEqual(["Qwen3", "GLM-5.3"]);
    expect(within(cards[0]).getByText("Unavailable")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Operational")).toBeInTheDocument();
    expect(within(cards[1]).getByText("900 ms")).toBeInTheDocument();
    expect(within(cards[1]).getByText("2.00 s")).toBeInTheDocument();
    expect(within(cards[1]).getByRole("img", { name: "Moark (Gitee AI) logo" })).toHaveAttribute(
      "src",
      expect.stringContaining("gitee_ai"),
    );
  });

  it("shows recent service events without loading announcement or news feeds", async () => {
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={false} />);

    expect(await screen.findByText("Qwen3 node unhealthy")).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/qos/home/news", expect.anything());
    expect(apiClient.get).not.toHaveBeenCalledWith("/qos/announcements", expect.anything());
    expect(screen.queryByRole("heading", { name: "Announcements" })).not.toBeInTheDocument();
  });

  it("shows an unchecked channel as awaiting checks even when it has successful traffic", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/health" ? { start_time: "", end_time: "", nodes: [], probes: [] } : responses[path],
    );
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={false} />);

    await screen.findByText("Awaiting health checks");
    const cards = within(screen.getByRole("region", { name: "Channel status" })).getAllByRole("article");
    for (const card of cards) {
      expect(within(card).getByText("Awaiting checks")).toBeInTheDocument();
      expect(within(card).getByText("No health check yet")).toBeInTheDocument();
    }
  });

  it("expands every configured model on demand and restores the compact view", async () => {
    const user = userEvent.setup();
    const models = Array.from({ length: 7 }, (_, index) => target(`Model ${index + 1}`));
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/targets" ? { models } : responses[path],
    );
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={false} />);
    await screen.findByRole("heading", { name: "Model 1", exact: true });
    const channels = screen.getByRole("region", { name: "Channel status" });
    expect(within(channels).getAllByRole("article")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "View more models" }));
    expect(within(channels).getAllByRole("article")).toHaveLength(models.length);
    expect(screen.getByRole("heading", { name: "Model 7", exact: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show fewer models" })).toHaveAttribute("aria-expanded", "true");

    await user.click(screen.getByRole("button", { name: "Show fewer models" }));
    expect(within(channels).getAllByRole("article")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "View more models" })).toHaveAttribute("aria-expanded", "false");
  });

  it("refreshes the channel list, health checks and activity with one action", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={false} />);
    await screen.findByText("Qwen3 node unhealthy");
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh data" })).toBeEnabled());
    vi.mocked(apiClient.get).mockClear();

    await user.click(screen.getByRole("button", { name: "Refresh data" }));
    await waitFor(() =>
      expect(new Set(vi.mocked(apiClient.get).mock.calls.map(([path]) => path))).toEqual(
        new Set(["/qos/targets", "/qos/health", "/qos/home/activity"]),
      ),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("checks upstream endpoints before refreshing an administrator's status cards", async () => {
    const user = userEvent.setup();
    const completed = Promise.withResolvers<unknown>();
    vi.mocked(apiClient.post).mockReturnValue(completed.promise);
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={true} />);
    await screen.findByText("Some channels are unavailable");
    await waitFor(() => expect(screen.getByRole("button", { name: "Check and refresh" })).toBeEnabled());
    vi.mocked(apiClient.get).mockClear();

    await user.click(screen.getByRole("button", { name: "Check and refresh" }));
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/qos/health/refresh", { accessToken: "token" });
    expect(screen.getByRole("button", { name: "Checking endpoints" })).toBeDisabled();
    expect(apiClient.get).not.toHaveBeenCalled();

    const freshHealth = {
      start_time: "",
      end_time: "",
      nodes: [
        node("GLM-5.3", "healthy"),
        {
          ...node("Qwen3", "healthy"),
          last_ttft_ms: 1250,
          last_latency_ms: 4500,
          last_streamed_at: "2026-10-26T12:00:00Z",
        },
      ],
      probes: [],
    };
    completed.resolve(freshHealth);
    expect(await screen.findByText("All channels operational")).toBeInTheDocument();
    expect(screen.getByText("1.25 s")).toBeInTheDocument();
    expect(screen.getByText("4.50 s")).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/qos/health", expect.anything());
  });

  it("shows a failed manual check and allows another attempt", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Health results could not be saved"));
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={true} />);
    await screen.findByText("Some channels are unavailable");
    await waitFor(() => expect(screen.getByRole("button", { name: "Check and refresh" })).toBeEnabled());

    await user.click(screen.getByRole("button", { name: "Check and refresh" }));
    expect(await screen.findByText("Health results could not be saved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check and refresh" })).toBeEnabled();
    expect(screen.getByText("Some channels are unavailable")).toBeInTheDocument();
  });

  it("reads fresh data every minute without triggering upstream checks", async () => {
    vi.useFakeTimers();
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={true} />);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByText("Some channels are unavailable")).toBeInTheDocument();
    vi.mocked(apiClient.get).mockClear();

    await act(() => vi.advanceTimersByTimeAsync(59_998));
    expect(apiClient.get).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(
      vi
        .mocked(apiClient.get)
        .mock.calls.map(([path]) => path)
        .sort(),
    ).toEqual(["/qos/health", "/qos/home/activity", "/qos/targets"]);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("exposes a health-check loading failure without reporting an update time", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/qos/health") throw new Error("Health service unreachable");
      return responses[path];
    });
    renderWithProviders(<HomeBoard accessToken="token" canCheckHealth={false} />);

    expect(await screen.findByText("Service status unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Health service unreachable/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Refreshing")).not.toBeInTheDocument());
    expect(screen.queryByText(/^Updated /)).not.toBeInTheDocument();
  });
});
