import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BenchmarkRequests from "./BenchmarkRequests";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";
import type { QosBenchmarkRequestLog } from "./qosData";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn() } }));
const authorized = vi.hoisted(() => ({ userRole: "Admin" }));
vi.mock("@/app/(dashboard)/hooks/useAuthorized", () => ({ default: () => authorized }));

const request: QosBenchmarkRequestLog = {
  request_id: "request-1",
  started_at: "2026-10-28T10:00:00Z",
  concurrency: 32,
  model_id: "node-a",
  api_base: "https://api.moark.com/v1",
  vendor: "moark",
  status: "success",
  response_check: "passed",
  exchange: {
    question:
      "Write the code QOS-0123456789AB alone on the first line of your reply, then answer:\n\n用三句话解释大语言模型。",
    answer: "QOS-0123456789AB\n<b>模型回答</b>",
    reasoning: "思考内容",
    error: null,
  },
};
const firstPage = { requests: [request], total: 1, page: 1, page_size: 10 };

describe("BenchmarkRequests", () => {
  beforeEach(() => {
    authorized.userRole = "Admin";
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(firstPage);
  });

  it("expands the exact question and answer as text and keeps Reasoning folded separately", async () => {
    const user = userEvent.setup();
    renderWithProviders(<BenchmarkRequests accessToken="token" runId="qos-run-1" />);
    await user.click(await screen.findByRole("button", { name: "View question and answer" }));

    expect(screen.getByText(/Write the code QOS-0123456789AB/)).toHaveTextContent("用三句话解释大语言模型。");
    expect(screen.getByText(/<b>模型回答<\/b>/)).toBeVisible();
    expect(screen.getByText("思考内容")).not.toBeVisible();
    await user.click(screen.getByText("Reasoning"));
    expect(screen.getByText("思考内容")).toBeVisible();
  });

  it("says when an old record has no saved text instead of inventing an answer", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockResolvedValue({ ...firstPage, requests: [{ ...request, exchange: null }] });
    renderWithProviders(<BenchmarkRequests accessToken="token" runId="qos-run-1" />);
    await user.click(await screen.findByRole("button", { name: "View question and answer" }));
    expect(screen.getByText("This request has no saved question or answer.")).toBeInTheDocument();
    expect(screen.queryByText("Answer received")).not.toBeInTheDocument();
  });

  it("shows a saved provider error beside the question", async () => {
    const user = userEvent.setup();
    const failed = {
      ...request,
      status: "failure",
      response_check: null,
      exchange: { question: "question sent", answer: null, reasoning: null, error: "HTTP 429: rate limit exceeded" },
    };
    vi.mocked(apiClient.get).mockResolvedValue({ ...firstPage, requests: [failed] });
    renderWithProviders(<BenchmarkRequests accessToken="token" runId="qos-run-1" />);
    await user.click(await screen.findByRole("button", { name: "View question and answer" }));
    expect(screen.getByText("question sent")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP 429: rate limit exceeded");
  });

  it("fetches pages on demand and refreshes the current page manually", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockResolvedValue({ ...firstPage, total: 12 });
    renderWithProviders(<BenchmarkRequests accessToken="token" runId="qos-run-1" />);
    await screen.findByText("request-1");
    await user.click(screen.getByTestId("pagination-next"));
    await waitFor(() => expect(vi.mocked(apiClient.get).mock.lastCall?.[1]?.query).toEqual({ page: 2, page_size: 10 }));
    await user.click(screen.getByRole("button", { name: "Refresh questions and answers" }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(3));
    expect(vi.mocked(apiClient.get).mock.lastCall?.[1]?.query).toEqual({ page: 2, page_size: 10 });
  });

  it("exposes load errors", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Only proxy admins can view benchmark text"));
    renderWithProviders(<BenchmarkRequests accessToken="token" runId="qos-run-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Only proxy admins can view benchmark text");
  });

  it("keeps full response text scoped to proxy admins", () => {
    authorized.userRole = "Internal User";
    renderWithProviders(<BenchmarkRequests accessToken="token" runId="qos-run-1" />);
    expect(screen.queryByText("Questions and answers")).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
