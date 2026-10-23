import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosView from "./QosView";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/app/(dashboard)/hooks/models/useModels", () => ({
  usePlainChatModelGroups: () => new Set(["qwen3-max", "glm-5"]),
}));

const metrics = {
  model_group: "qwen3-max",
  requests: 8,
  failed_requests: 0,
  streamed_requests: 8,
  output_tokens: 800,
  peak_concurrency: 4,
  first_request_at: "2026-10-23T01:00:00Z",
  last_response_at: "2026-10-23T01:00:10Z",
  requests_per_second: 0.8,
  output_tokens_per_second: 80,
  ttft_ms: { p50: 300, p95: 610, p99: 640 },
  tpot_ms: { p50: 20, p95: 40, p99: 42 },
  e2e_latency_ms: { p50: 1500, p95: 2800, p99: 2900 },
};

const started = {
  run_id: "qos-20261023-090000-qwen3-max-ab12",
  model_group: "qwen3-max",
  concurrency: [1, 4],
  requests_per_worker: 2,
  max_tokens: 256,
  total_requests: 10,
  started_at: "2026-10-23T01:00:00Z",
};

const respond = (path: string): unknown => {
  if (path === "/qos/summary") return { start_time: "", end_time: "", tag: null, model_groups: [], deployments: [] };
  if (path === "/qos/benchmarks") return { runs: [] };
  return {
    run_id: started.run_id,
    levels: [{ ...metrics, concurrency: 4, requests: 8 }],
    deployments: [{ ...metrics, model_id: "node-a", model: "moark/qwen3.8-max", api_base: "https://node-a/v1" }],
  };
};

describe("QoS benchmarks", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => respond(path));
    vi.mocked(apiClient.post).mockResolvedValue(started);
  });

  it("opens the start dialog for the model linked from the models page and posts the chosen plan", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { benchmark: "qwen3-max" } });

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Benchmarks", hidden: true })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Model")).toHaveTextContent("qwen3-max");

    fireEvent.change(screen.getByLabelText("Concurrency levels"), { target: { value: "1, 4" } });
    fireEvent.change(screen.getByLabelText("Requests per worker"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Max output tokens"), { target: { value: "256" } });
    expect(screen.getByRole("status")).toHaveTextContent("Sends 10 streamed requests through the gateway");
    await user.click(screen.getByRole("button", { name: "Start test" }));

    expect(apiClient.post).toHaveBeenCalledWith("/qos/benchmarks", {
      accessToken: "token",
      body: { model_group: "qwen3-max", concurrency: [1, 4], requests_per_worker: 2, max_tokens: 256 },
    });
    expect(await screen.findByText(started.run_id)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Test running")).toBeInTheDocument();
    expect(screen.getByText("8 / 10")).toBeInTheDocument();
    expect(screen.getByText("https://node-a/v1")).toBeInTheDocument();
  });

  it("keeps the start button disabled and says why while the plan is invalid", async () => {
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { benchmark: "qwen3-max" } });
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText("Concurrency levels"), { target: { value: "0" } });

    expect(screen.getByRole("status")).toHaveTextContent("Concurrency levels must be whole numbers from 1 to 256");
    expect(screen.getByRole("button", { name: "Start test" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
