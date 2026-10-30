import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosVideoReviewPanel from "./QosVideoReviewPanel";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn(), getBlob: vi.fn(), put: vi.fn() } }));

const PROBE_PROMPT = "固定镜头：阳光下的绿色草地上，一个红色皮球从画面左侧向右滚动，蓝天上飘着白云";
const OLDER_PROMPT = "颜色缓慢流动的渐变";

const earlierReview = {
  overall: 4,
  visual: 5,
  detail: 3,
  motion: 2,
  alignment: null,
  physics: null,
  audio: null,
  comment: "hands jitter",
  reviewed_at: "2026-10-29T08:00:00Z",
};

const reviews = {
  start_time: "2026-10-22T09:00:00Z",
  end_time: "2026-10-29T09:00:00Z",
  summary: [
    {
      model_group: "LTX-2",
      videos: 1,
      reviews: 2,
      overall: 3.5,
      visual: 5,
      detail: 4,
      motion: 2,
      alignment: null,
      physics: null,
      audio: null,
    },
  ],
  videos: [
    {
      video_id: "video-minimax",
      model_group: "MiniMax-H3",
      created_at: "2026-10-30T09:00:01Z",
      completed_at: "2026-10-30T09:01:40Z",
      prompt: PROBE_PROMPT,
      reviews: 0,
      overall: null,
      my_review: null,
    },
    {
      video_id: "video-ltx",
      model_group: "LTX-2",
      created_at: "2026-10-30T09:00:00Z",
      completed_at: "2026-10-30T09:02:17Z",
      prompt: PROBE_PROMPT,
      reviews: 2,
      overall: 3.5,
      my_review: earlierReview,
    },
    {
      video_id: "video-wan",
      model_group: "Wan2_2-I2V-A14B",
      created_at: "2026-10-29T09:00:00Z",
      completed_at: "2026-10-29T09:10:00Z",
      prompt: OLDER_PROMPT,
      reviews: 0,
      overall: null,
      my_review: null,
    },
  ],
};

const cardOf = (modelGroup: string): HTMLElement => screen.getByRole("article", { name: modelGroup });

const cardTitles = (group: HTMLElement): (string | null)[] =>
  within(group)
    .getAllByText(/.+/, { selector: '[data-slot="card-title"]' })
    .map((title) => title.textContent);

const scoreButton = (card: HTMLElement, dimension: string, score: number): HTMLElement =>
  within(within(card).getByRole("radiogroup", { name: dimension })).getByRole("radio", { name: String(score) });

describe("QosVideoReviewPanel", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(reviews);
    vi.mocked(apiClient.getBlob).mockReset();
    vi.mocked(apiClient.put).mockReset();
    Object.defineProperty(URL, "createObjectURL", { value: vi.fn(() => "blob:video-ltx"), configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
  });

  it("shows each model's average ratings and the videos of each prompt under that prompt", async () => {
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);

    await screen.findByText("MiniMax-H3", { selector: '[data-slot="card-title"]' });
    const summaryRow = screen.getAllByRole("row").find((row) => within(row).queryByText("LTX-2") !== null);
    expect(
      within(summaryRow as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["LTX-2", "1", "2", "3.5", "5.0", "4.0", "2.0", "-", "-", "-"]);
    expect(cardTitles(screen.getByRole("group", { name: /红色皮球/ }))).toEqual(["MiniMax-H3", "LTX-2"]);
    expect(cardTitles(screen.getByRole("group", { name: new RegExp(OLDER_PROMPT) }))).toEqual(["Wan2_2-I2V-A14B"]);
    expect(screen.getAllByText(PROBE_PROMPT)).toHaveLength(1);
  });

  it("asks for the last 7 days by default", async () => {
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("MiniMax-H3", { selector: '[data-slot="card-title"]' });

    const [path, options] = vi.mocked(apiClient.get).mock.calls[0];
    expect(path).toBe("/qos/videos");
    const query = options?.query;
    expect(Date.parse(String(query?.end_time)) - Date.parse(String(query?.start_time))).toBe(7 * 24 * 60 * 60 * 1000);
  });

  it("downloads a video only when asked to play it", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.getBlob).mockResolvedValue(new Blob(["mp4"], { type: "video/mp4" }));
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("LTX-2", { selector: '[data-slot="card-title"]' });
    expect(apiClient.getBlob).not.toHaveBeenCalled();

    await user.click(within(cardOf("LTX-2")).getByRole("button", { name: "Play video" }));

    expect(await within(cardOf("LTX-2")).findByLabelText("Generated video")).toHaveAttribute("src", "blob:video-ltx");
    expect(apiClient.getBlob).toHaveBeenCalledWith("/qos/videos/content", {
      accessToken: "token",
      query: { video_id: "video-ltx" },
    });
  });

  it("shows why a video cannot be played", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.getBlob).mockRejectedValue(new Error("Could not fetch the video: the result file has expired"));
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("LTX-2", { selector: '[data-slot="card-title"]' });

    await user.click(within(cardOf("LTX-2")).getByRole("button", { name: "Play video" }));

    expect(
      await within(cardOf("LTX-2")).findByText("Could not fetch the video: the result file has expired"),
    ).toBeInTheDocument();
  });

  it("starts from the reviewer's own earlier rating", async () => {
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("LTX-2", { selector: '[data-slot="card-title"]' });
    const card = cardOf("LTX-2");

    expect(scoreButton(card, "Overall", 4)).toHaveAttribute("aria-checked", "true");
    expect(scoreButton(card, "Video detail", 3)).toHaveAttribute("aria-checked", "true");
    expect(scoreButton(card, "Motion", 2)).toHaveAttribute("aria-checked", "true");
    expect(scoreButton(card, "Sound", 3)).toHaveAttribute("aria-checked", "false");
    expect(within(card).getByLabelText("Comment")).toHaveValue("hands jitter");
  });

  it("saves only once Overall is rated, sending the chosen scores and the trimmed comment", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.put).mockResolvedValue({ ...earlierReview, overall: 3 });
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("MiniMax-H3", { selector: '[data-slot="card-title"]' });
    const card = cardOf("MiniMax-H3");
    const save = within(card).getByRole("button", { name: "Save rating" });
    expect(save).toBeDisabled();

    await user.click(scoreButton(card, "Visual quality", 5));
    await user.click(scoreButton(card, "Video detail", 4));
    await user.click(scoreButton(card, "Physics and common sense", 2));
    await user.click(scoreButton(card, "Physics and common sense", 2));
    expect(save).toBeDisabled();
    await user.click(scoreButton(card, "Overall", 3));
    await user.type(within(card).getByLabelText("Comment"), "  the cat walks backwards  ");
    await user.click(save);

    await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
    expect(apiClient.put).toHaveBeenCalledWith("/qos/videos/review", {
      accessToken: "token",
      query: { video_id: "video-minimax" },
      body: { visual: 5, detail: 4, overall: 3, comment: "the cat walks backwards" },
    });
    expect(await within(card).findByText("Saved")).toBeInTheDocument();
  });
});
