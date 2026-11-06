import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StartVideoEvaluationDialog from "./StartVideoEvaluationDialog";
import { apiClient } from "@/components/networking";
import { uiHref } from "@/utils/uiHref";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

const TEA = "固定镜头特写：清晨的阳光从左侧窗户照在木桌上，一只手拿起白色陶瓷茶壶，把琥珀色的茶倒进玻璃杯";
const STREET = "夜晚刚下过雨的街道，镜头从左向右缓慢平移，一个穿黄色雨衣的人骑着自行车从画面左侧骑向右侧";
const MODELS = ["MiniMax-H3", "LTX-2", "Wan2_2-I2V-A14B"];

const options = {
  available: true,
  models: [
    { model_group: "MiniMax-H3", image_to_video: false, last_price: 2.5, currency: "CNY" },
    { model_group: "LTX-2", image_to_video: true, last_price: 1.5, currency: "CNY" },
    { model_group: "Wan2_2-I2V-A14B", image_to_video: true, last_price: null, currency: null },
  ],
  prompts: [{ prompt: TEA, last_used: "2026-10-30T10:11:39Z", videos: 2 }],
};

const renderDialog = (onStarted = vi.fn()) => {
  renderWithProviders(
    <StartVideoEvaluationDialog open onOpenChange={vi.fn()} accessToken="token" onStarted={onStarted} />,
  );
  return { onStarted, dialog: screen.getByRole("dialog", { name: "Start an evaluation" }) };
};

const startButton = (dialog: HTMLElement): HTMLElement =>
  within(dialog).getByRole("button", { name: "Start evaluation" });

describe("StartVideoEvaluationDialog", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(options);
    vi.mocked(apiClient.post).mockReset();
  });

  it("writes a new prompt that tests every rating and starts the evaluation with it", async () => {
    const user = userEvent.setup();
    const started = { prompt: STREET, models: MODELS };
    vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
      path === "/qos/videos/evaluations/prompt" ? { prompt: STREET } : started,
    );
    const { onStarted, dialog } = renderDialog();

    await user.click(await within(dialog).findByRole("button", { name: "Write a prompt that tests every rating" }));

    expect(await within(dialog).findByDisplayValue(STREET)).toBeInTheDocument();
    await user.click(startButton(dialog));
    await waitFor(() => expect(onStarted).toHaveBeenCalledTimes(1));
    expect(onStarted.mock.calls[0][0]).toEqual(started);
    expect(apiClient.post).toHaveBeenCalledWith("/qos/videos/evaluations/prompt", { accessToken: "token" });
    expect(apiClient.post).toHaveBeenLastCalledWith("/qos/videos/evaluations", {
      accessToken: "token",
      body: { prompt: STREET },
    });
  });

  it("fills the prompt from one an earlier run used", async () => {
    const user = userEvent.setup();
    const { dialog } = renderDialog();
    await within(dialog).findByText(/Estimated cost/);

    await user.click(within(dialog).getByRole("radio", { name: "Earlier prompt" }));
    await user.click(within(dialog).getByLabelText("Earlier prompts"));
    await user.click(await screen.findByRole("option", { name: new RegExp(TEA) }));

    expect(within(dialog).getByLabelText("Prompt")).toHaveValue(TEA);
  });

  it("starts with my own prompt, trimmed", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({ prompt: "一只猫跳上窗台", models: MODELS });
    const { dialog } = renderDialog();
    await within(dialog).findByText(/Estimated cost/);

    fireEvent.change(within(dialog).getByLabelText("Prompt"), { target: { value: "  一只猫跳上窗台 \n" } });
    await user.click(startButton(dialog));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/qos/videos/evaluations", {
        accessToken: "token",
        body: { prompt: "一只猫跳上窗台" },
      }),
    );
  });

  it("lists the models with their latest price and estimates the cost of a run", async () => {
    const { dialog } = renderDialog();

    const models = await within(dialog).findByRole("region", { name: "Models in this evaluation" });
    expect(
      within(models)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "MiniMax-H3 · text to video · 2.50 CNY",
      "LTX-2 · image to video · 1.50 CNY",
      "Wan2_2-I2V-A14B · image to video",
    ]);
    expect(within(models).getByRole("status")).toHaveTextContent(
      "Estimated cost: about 4.00 CNY, from each model's latest video; no recent price for Wan2_2-I2V-A14B",
    );
  });

  it("does not start while the prompt is empty", async () => {
    const { dialog } = renderDialog();
    await within(dialog).findByText(/Estimated cost/);

    expect(startButton(dialog)).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Prompt"), { target: { value: "   " } });
    expect(startButton(dialog)).toBeDisabled();
  });

  it("explains that nothing can start without a media probe", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...options, available: false });
    const { dialog } = renderDialog();

    expect(await within(dialog).findByText(/No media probe is set up/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Write a prompt that tests every rating" })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Prompt"), { target: { value: STREET } });
    expect(startButton(dialog)).toBeDisabled();
  });

  it("shows how to enroll a video model when a prompt is ready but there are no models to test", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...options, models: [] });
    const { dialog } = renderDialog();

    fireEvent.change(within(dialog).getByLabelText("Prompt"), { target: { value: STREET } });

    const hint = await within(dialog).findByRole("alert");
    expect(hint).toHaveTextContent('"qos_probe": {} to Model Info');
    expect(within(hint).getByRole("link", { name: "Open model management" })).toHaveAttribute(
      "href",
      uiHref("models-and-endpoints"),
    );
    expect(startButton(dialog)).toBeDisabled();
  });

  it("shows why an evaluation could not start", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockRejectedValue(
      new Error("The media probe answered 401: this needs the gateway's master key"),
    );
    const { onStarted, dialog } = renderDialog();
    await within(dialog).findByText(/Estimated cost/);

    fireEvent.change(within(dialog).getByLabelText("Prompt"), { target: { value: STREET } });
    await user.click(startButton(dialog));

    expect(await within(dialog).findByText(/answered 401/)).toBeInTheDocument();
    expect(onStarted).not.toHaveBeenCalled();
  });
});
