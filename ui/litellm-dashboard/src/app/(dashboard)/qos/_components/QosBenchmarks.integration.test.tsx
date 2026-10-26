import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosView from "./QosView";
import { apiClient } from "@/components/networking";
import { downloadBlob } from "@/components/EntityUsageExport/utils";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock("@/components/EntityUsageExport/utils", () => ({ downloadBlob: vi.fn() }));
const authorized = vi.hoisted(() => ({ userRole: "Admin", isViewOnly: false }));
vi.mock("@/app/(dashboard)/hooks/useAuthorized", () => ({ default: () => authorized }));
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
  response_checks: { checked: 8, crosstalk: 0, marker_missing: 0 },
};

const quiet = { same_deployment: 0, same_endpoint: 0 };

const started = {
  run_id: "qos-20261023-090000-qwen3-max-ab12",
  model_group: "qwen3-max",
  deployment_ids: [],
  concurrency: [1, 4],
  requests_per_worker: 2,
  max_tokens: 256,
  total_requests: 10,
  started_at: "2026-10-23T01:00:00Z",
};

const pastRun = {
  run_id: "qos-20261022-120000-glm-5-cd34",
  model_group: "glm-5",
  requests: 42,
  failed_requests: 0,
  crosstalk_responses: 3,
  started_at: "2026-10-22T04:00:00Z",
  last_response_at: "2026-10-22T04:01:00Z",
};

const qwenProviders = [
  {
    model_id: "node-moark",
    provider: "moark",
    vendor: "moark",
    api_base: "https://api.moark.com/v1",
    upstream_model: "Qwen3-Max",
  },
  {
    model_id: "node-gitee",
    provider: "openai",
    vendor: "ai.gitee.com",
    api_base: "https://ai.gitee.com/v1",
    upstream_model: "Qwen3-Max",
  },
];

interface ProviderLevel {
  readonly model_id: string;
  readonly vendor: string;
  readonly api_base: string;
  readonly ttft: number;
  readonly crosstalk: number;
  readonly sameDeployment: number;
}

const providerLevel = ({ model_id, vendor, api_base, ttft, crosstalk, sameDeployment }: ProviderLevel) => ({
  ...metrics,
  model_id,
  model: "Qwen3-Max",
  api_base,
  vendor,
  concurrency: 1,
  ttft_ms: { p50: ttft, p95: ttft * 2, p99: ttft * 2 },
  response_checks: { checked: 4, crosstalk, marker_missing: 0 },
  interference: { same_deployment: sameDeployment, same_endpoint: 0 },
});

const crossedGitee: ProviderLevel = {
  model_id: "node-gitee",
  vendor: "ai.gitee.com",
  api_base: "https://ai.gitee.com/v1",
  ttft: 900,
  crosstalk: 2,
  sameDeployment: 0,
};
const busyMoark: ProviderLevel = {
  model_id: "node-moark",
  vendor: "moark",
  api_base: "https://api.moark.com/v1",
  ttft: 300,
  crosstalk: 0,
  sameDeployment: 5,
};

const singleProviderDetail = {
  run_id: started.run_id,
  levels: [{ ...metrics, concurrency: 4, requests: 8, interference: quiet }],
  deployments: [
    { ...metrics, model_id: "node-a", model: "moark/qwen3.8-max", api_base: "https://node-a/v1", vendor: "moark" },
  ],
  deployment_levels: [
    {
      ...metrics,
      model_id: "node-a",
      model: "moark/qwen3.8-max",
      api_base: "https://node-a/v1",
      vendor: "moark",
      concurrency: 4,
      interference: quiet,
    },
  ],
};

const comparisonDetail = {
  run_id: started.run_id,
  levels: [{ ...metrics, concurrency: 1, requests: 4, interference: quiet }],
  deployments: [],
  deployment_levels: [providerLevel(crossedGitee), providerLevel(busyMoark)],
};

const rowContaining = (text: string): HTMLElement => {
  const row = screen.getAllByRole("row").find((candidate) => within(candidate).queryByText(text) !== null);
  if (row === undefined) throw new Error(`No table row contains ${text}`);
  return row;
};

const blobText = (blob: Blob): Promise<string> =>
  new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });

const respondWith =
  (detail: unknown) =>
  async (path: string): Promise<unknown> => {
    if (path === "/qos/summary") return { start_time: "", end_time: "", tag: null, model_groups: [], deployments: [] };
    if (path === "/qos/benchmarks") return { runs: [pastRun] };
    if (path === "/qos/targets") return { models: [{ model_group: "qwen3-max", deployments: qwenProviders }] };
    return detail;
  };

describe("QoS benchmarks", () => {
  beforeEach(() => {
    authorized.userRole = "Admin";
    authorized.isViewOnly = false;
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(downloadBlob).mockReset();
    vi.mocked(apiClient.get).mockImplementation(respondWith(singleProviderDetail));
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
      body: {
        model_group: "qwen3-max",
        deployment_ids: [],
        concurrency: [1, 4],
        requests_per_worker: 2,
        max_tokens: 256,
      },
    });
    expect(await screen.findByText(started.run_id)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Test running")).toBeInTheDocument();
    expect(screen.getByText("8 / 10")).toBeInTheDocument();
    expect(screen.getByText("https://node-a/v1")).toBeInTheDocument();
  });

  it("compares every provider of a model with the same plan and lays their results side by side", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockImplementation(respondWith(comparisonDetail));
    vi.mocked(apiClient.post).mockResolvedValue({
      ...started,
      deployment_ids: ["node-moark", "node-gitee"],
      total_requests: 8,
    });
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { benchmark: "qwen3-max" } });

    await user.click(await screen.findByLabelText("Provider"));
    expect(
      await screen.findByRole("option", { name: "Moark (Gitee AI) · https://api.moark.com/v1" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "ai.gitee.com · https://ai.gitee.com/v1" })).toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Compare all 2 providers" }));
    fireEvent.change(screen.getByLabelText("Concurrency levels"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Requests per worker"), { target: { value: "4" } });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Sends 8 streamed requests, testing 2 providers one after another with the same plan",
    );
    await user.click(screen.getByRole("button", { name: "Start test" }));

    expect(vi.mocked(apiClient.post).mock.calls[0][1]?.body).toMatchObject({
      model_group: "qwen3-max",
      deployment_ids: ["node-moark", "node-gitee"],
    });
    expect(await screen.findByText("Provider comparison")).toBeInTheDocument();
    expect(screen.getByText("https://api.moark.com/v1")).toBeInTheDocument();
    expect(screen.getByText("https://ai.gitee.com/v1")).toBeInTheDocument();
    expect(screen.getByText("300 ms / 600 ms")).toBeInTheDocument();
    expect(screen.getByText("900 ms / 1.80 s")).toBeInTheDocument();
    expect(within(rowContaining("https://ai.gitee.com/v1")).getByText("2 cross-talk")).toBeInTheDocument();
    expect(within(rowContaining("https://ai.gitee.com/v1")).getByText("ai.gitee.com")).toBeInTheDocument();
    const moarkRow = within(rowContaining("https://api.moark.com/v1"));
    expect(moarkRow.getByText("Moark (Gitee AI)")).toBeInTheDocument();
    expect(moarkRow.getByText("4 passed")).toBeInTheDocument();
    expect(moarkRow.getByText("5")).toBeInTheDocument();
  });

  it("keeps the start button disabled and says why while the plan is invalid", async () => {
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { benchmark: "qwen3-max" } });
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText("Concurrency levels"), { target: { value: "0" } });

    expect(screen.getByRole("status")).toHaveTextContent("Concurrency levels must be whole numbers from 1 to 256");
    expect(screen.getByRole("button", { name: "Start test" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("deletes a test record only after the admin confirms how many request logs it removes", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockResolvedValue({ run_id: pastRun.run_id, deleted_requests: 42 });
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { tab: "benchmarks" } });

    await user.click(await screen.findByRole("button", { name: "Delete test record" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(`This permanently deletes the 42 request logs recorded for ${pastRun.run_id}.`);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(apiClient.delete).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete test record" }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(apiClient.delete).toHaveBeenCalledWith(`/qos/benchmarks/${pastRun.run_id}`, { accessToken: "token" });
  });

  it("exports only the ticked test records to CSV", async () => {
    const user = userEvent.setup();
    const otherRun = { ...pastRun, run_id: "qos-20261021-120000-glm-5-ef56" };
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/benchmarks" ? { runs: [pastRun, otherRun] } : respondWith(singleProviderDetail)(path),
    );
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { tab: "benchmarks" } });

    expect(await screen.findByRole("button", { name: "Export CSV" })).toBeDisabled();
    await user.click(await screen.findByRole("checkbox", { name: `Select ${pastRun.run_id}` }));
    await user.click(screen.getByRole("button", { name: "Export 1 to CSV" }));

    await vi.waitFor(() => expect(downloadBlob).toHaveBeenCalledOnce());
    const detailPaths = vi
      .mocked(apiClient.get)
      .mock.calls.map(([path]) => path)
      .filter((path) => path.startsWith("/qos/benchmarks/"));
    expect(detailPaths).toEqual([`/qos/benchmarks/${pastRun.run_id}`]);
    const [blob, fileName] = vi.mocked(downloadBlob).mock.calls[0];
    expect(fileName).toMatch(/^qos_benchmarks_.+\.csv$/);
    const csv = await blobText(blob);
    expect(csv).toContain(pastRun.run_id);
    expect(csv).not.toContain(otherRun.run_id);
  });

  it("says why an export failed and downloads nothing", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === `/qos/benchmarks/${pastRun.run_id}`) throw new Error("Benchmark run not found");
      return respondWith(singleProviderDetail)(path);
    });
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { tab: "benchmarks" } });

    await user.click(await screen.findByRole("checkbox", { name: `Select ${pastRun.run_id}` }));
    await user.click(screen.getByRole("button", { name: "Export 1 to CSV" }));

    expect(await screen.findByText("Benchmark run not found")).toBeInTheDocument();
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("flags past runs whose responses crossed with other requests", async () => {
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { tab: "benchmarks" } });

    await screen.findByText(pastRun.run_id);
    expect(within(rowContaining(pastRun.run_id)).getByText("3 responses")).toBeInTheDocument();
  });

  it("shows view-only admins the results without start or delete controls", async () => {
    authorized.isViewOnly = true;
    renderWithProviders(<QosView accessToken="token" />, { searchParams: { tab: "benchmarks" } });

    expect(await screen.findByText(pastRun.run_id)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete test record" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start test" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
  });
});
