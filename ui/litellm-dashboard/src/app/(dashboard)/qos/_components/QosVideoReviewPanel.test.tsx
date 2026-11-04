import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosVideoReviewPanel from "./QosVideoReviewPanel";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({
  apiClient: { get: vi.fn(), getBlob: vi.fn(), put: vi.fn(), post: vi.fn() },
}));

const PROBE_PROMPT = "固定镜头：阳光下的绿色草地上，一个红色皮球从画面左侧向右滚动，蓝天上飘着白云";
const OLDER_PROMPT = "颜色缓慢流动的渐变";
const STREET_PROMPT = "夜晚刚下过雨的街道，镜头从左向右缓慢平移，一个穿黄色雨衣的人骑着自行车从画面左侧骑向右侧";

const aiReview = {
  judge: "qwen3.8-27b",
  frames: 3,
  overall: 2,
  visual: 3,
  detail: 1,
  motion: 2,
  alignment: 3,
  physics: 1,
  reasons: { visual: "", detail: "草叶糊成一片", motion: "", alignment: "", physics: "球没有影子" },
  checklist: [
    { requirement: "固定镜头", met: true, evidence: "背景不动" },
    { requirement: "蓝天上飘着白云", met: false, evidence: "第 2 秒云消失" },
  ],
  problems: [{ second: 1, problem: "草叶凭空长出" }],
  reviewed_at: "2026-10-30T09:05:00Z",
};

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

const ago = (minutes: number): string => new Date(Date.now() - minutes * 60_000).toISOString();

const video = (overrides: Record<string, unknown>) => ({
  status: "completed",
  ai_review: null,
  model_group: "LTX-2",
  created_at: ago(10),
  completed_at: ago(8),
  prompt: STREET_PROMPT,
  run: "manual-new",
  scheduled: false,
  reviews: 0,
  overall: null,
  my_review: null,
  ...overrides,
});

const scheduledVideo = (run: string, minutes: number) =>
  video({ video_id: `video-${run}`, run, scheduled: true, prompt: PROBE_PROMPT, created_at: ago(minutes) });

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
  ai_summary: [
    { model_group: "LTX-2", videos: 1, overall: 2, visual: 3, detail: 1, motion: 2, alignment: 3, physics: 1 },
  ],
  videos: [
    video({ video_id: "video-minimax", model_group: "MiniMax-H3", created_at: ago(9) }),
    video({ video_id: "video-ltx", ai_review: aiReview, reviews: 2, overall: 3.5, my_review: earlierReview }),
    video({ video_id: "video-hunyuan", model_group: "HunyuanVideo-1.5", status: "generating", completed_at: null }),
    video({ video_id: "video-vidu", model_group: "ViduQ2-Turbo", status: "failed", completed_at: null }),
    scheduledVideo("scheduled-1", 60),
    video({
      video_id: "video-wan",
      model_group: "Wan2_2-I2V-A14B",
      prompt: OLDER_PROMPT,
      run: "manual-old",
      created_at: ago(180),
    }),
    scheduledVideo("scheduled-2", 240),
    scheduledVideo("scheduled-3", 420),
    scheduledVideo("scheduled-4", 600),
    video({
      video_id: "video-expired",
      model_group: "Wan2.7",
      prompt: "过期的 Prompt",
      run: "manual-expired",
      created_at: ago(2 * 24 * 60),
    }),
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
    window.localStorage.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(reviews);
    vi.mocked(apiClient.getBlob).mockReset();
    vi.mocked(apiClient.put).mockReset();
    Object.defineProperty(URL, "createObjectURL", { value: vi.fn(() => "blob:video-ltx"), configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
  });

  it("shows each model's average ratings and the newest manual run open with its videos in model order", async () => {
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);

    await screen.findByText("MiniMax-H3", { selector: '[data-slot="card-title"]' });
    const summaryRow = within(screen.getByRole("region", { name: "Ratings per model" }))
      .getAllByRole("row")
      .find((row) => within(row).queryByText("LTX-2") !== null);
    expect(
      within(summaryRow as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["LTX-2", "1", "2", "3.5", "5.0", "4.0", "2.0", "-", "-", "-"]);
    const newest = screen.getByRole("group", { name: STREET_PROMPT });
    expect(cardTitles(newest)).toEqual(["HunyuanVideo-1.5", "LTX-2", "MiniMax-H3", "ViduQ2-Turbo"]);
    expect(within(newest).getByText("Latest")).toBeInTheDocument();
    expect(within(newest).getByText(/· 4 videos · AI average 2.0 · rated 1\/4$/)).toBeInTheDocument();
  });

  it("folds earlier manual runs to one line each until one is opened", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("MiniMax-H3", { selector: '[data-slot="card-title"]' });
    const manual = screen.getByRole("region", { name: "Manual evaluations" });

    expect(within(manual).getByText("Earlier manual evaluations")).toBeInTheDocument();
    expect(screen.queryByText("Wan2_2-I2V-A14B", { selector: '[data-slot="card-title"]' })).not.toBeInTheDocument();

    await user.click(within(manual).getByRole("button", { name: new RegExp(OLDER_PROMPT) }));

    expect(cardTitles(screen.getByRole("group", { name: OLDER_PROMPT }))).toEqual(["Wan2_2-I2V-A14B"]);
  });

  it("lists the latest three scheduled runs, folded, until all are asked for", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    const scheduled = await screen.findByRole("region", { name: "Scheduled evaluations" });
    await within(scheduled).findByText("4 runs, only the latest 3 listed");

    expect(within(scheduled).getAllByRole("group")).toHaveLength(3);
    expect(within(scheduled).queryByRole("article")).not.toBeInTheDocument();
    expect(within(scheduled).getByText(new RegExp(PROBE_PROMPT))).toBeInTheDocument();

    await user.click(within(scheduled).getByRole("button", { name: "Show all" }));

    expect(within(scheduled).getAllByRole("group")).toHaveLength(4);
  });

  it("hides videos the provider no longer keeps until asked to show them", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("MiniMax-H3", { selector: '[data-slot="card-title"]' });

    expect(screen.getByText(/^1 more videos have expired/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /过期的 Prompt/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show expired videos" }));

    expect(screen.getByRole("button", { name: /过期的 Prompt/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide expired videos" })).toBeInTheDocument();
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
  it("shows the AI rating of a finished video and, when asked, why it gave it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("LTX-2", { selector: '[data-slot="card-title"]' });
    const rating = within(cardOf("LTX-2")).getByRole("region", { name: "AI rating" });

    expect(
      within(rating).getByText("qwen3.8-27b rated 3 stills, one per second, without the sound"),
    ).toBeInTheDocument();
    const terms = within(rating)
      .getAllByRole("term")
      .map((term) => term.textContent);
    const values = within(rating)
      .getAllByRole("definition")
      .map((value) => value.textContent);
    expect(terms.map((term, index) => [term, values[index]])).toEqual([
      ["Overall", "2"],
      ["Visual quality", "3"],
      ["Video detail", "1"],
      ["Motion", "2"],
      ["Prompt alignment", "3"],
      ["Physics and common sense", "1"],
    ]);
    expect(within(rating).getByText("草叶糊成一片")).not.toBeVisible();

    await user.click(within(rating).getByText("Why it gave these ratings"));

    expect(within(rating).getByText("草叶糊成一片")).toBeVisible();
    expect(within(rating).getByText(/蓝天上飘着白云 \(第 2 秒云消失\)/)).toBeVisible();
    expect(within(rating).getByText("草叶凭空长出")).toBeVisible();
    expect(within(rating).queryByText("固定镜头")).not.toBeInTheDocument();
    expect(within(cardOf("MiniMax-H3")).queryByRole("region", { name: "AI rating" })).not.toBeInTheDocument();
  });

  it("shows a video still generating or one that failed without a player or ratings", async () => {
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("HunyuanVideo-1.5", { selector: '[data-slot="card-title"]' });

    expect(within(cardOf("HunyuanVideo-1.5")).getByRole("status")).toHaveTextContent(
      "Still generating; the AI rates it as soon as it finishes",
    );
    expect(within(cardOf("ViduQ2-Turbo")).getByRole("status")).toHaveTextContent(
      "The provider could not generate this video",
    );
    for (const model of ["HunyuanVideo-1.5", "ViduQ2-Turbo"]) {
      expect(within(cardOf(model)).queryByRole("button", { name: "Play video" })).not.toBeInTheDocument();
      expect(within(cardOf(model)).queryByRole("radiogroup")).not.toBeInTheDocument();
    }
  });

  it("shows each model's average AI ratings apart from the ratings people give", async () => {
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    const aiRatings = await screen.findByRole("region", { name: "AI ratings per model" });

    const row = await within(aiRatings).findByRole("row", { name: /LTX-2/ });
    expect(
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["LTX-2", "1", "2.0", "3.0", "1.0", "2.0", "3.0", "1.0"]);
  });

  it("starts an evaluation from the dialog and says which models are generating", async () => {
    const user = userEvent.setup();
    const evaluationOptions = {
      available: true,
      models: [{ model_group: "MiniMax-H3", image_to_video: false, last_price: 2.5, currency: "CNY" }],
      prompts: [],
    };
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/videos/evaluations/options" ? evaluationOptions : reviews,
    );
    vi.mocked(apiClient.post).mockResolvedValue({ prompt: STREET_PROMPT, models: ["MiniMax-H3", "LTX-2"] });
    renderWithProviders(<QosVideoReviewPanel accessToken="token" />);
    await screen.findByText("LTX-2", { selector: '[data-slot="card-title"]' });

    await user.click(screen.getByRole("button", { name: "Start evaluation" }));
    const dialog = await screen.findByRole("dialog", { name: "Start an evaluation" });
    await within(dialog).findByText(/Estimated cost/);
    fireEvent.change(within(dialog).getByLabelText("Prompt"), { target: { value: STREET_PROMPT } });
    await user.click(within(dialog).getByRole("button", { name: "Start evaluation" }));

    expect(await screen.findByText("Evaluation started")).toBeInTheDocument();
    expect(screen.getByText(/MiniMax-H3, LTX-2 are generating the prompt/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
