import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosSpeechEvaluationPanel from "./QosSpeechEvaluationPanel";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({
  apiClient: { get: vi.fn(), getBlob: vi.fn(), put: vi.fn(), post: vi.fn() },
}));

const SENTENCE = "今天天气很好，我们一起去公园散步，顺便买些水果回家。";
const ago = (minutes: number): string => new Date(Date.now() - minutes * 60_000).toISOString();

const result = (overrides: Record<string, unknown>) => ({
  request_id: "call",
  run: "manual-new",
  scheduled: false,
  model_group: "IndexTTS-2",
  modality: "speech",
  created_at: ago(5),
  succeeded: true,
  error: null,
  latency_ms: 2000,
  audio_seconds: 5,
  text: SENTENCE,
  transcript: null,
  reviews: 0,
  overall: null,
  my_review: null,
  ...overrides,
});

const evaluations = {
  start_time: "2026-10-28T06:00:00Z",
  end_time: "2026-11-04T06:00:00Z",
  results: [
    result({
      request_id: "call-index",
      reviews: 1,
      overall: 4,
      my_review: { overall: 4, reviewed_at: "2026-11-04T06:00:00Z" },
    }),
    result({
      request_id: "call-broken",
      model_group: "Step-Audio-TTS-3B",
      succeeded: false,
      error: "the resource pack does not cover this model",
      audio_seconds: null,
    }),
    result({
      request_id: "call-sense",
      model_group: "SenseVoiceSmall",
      modality: "transcription",
      latency_ms: 800,
      transcript: "今天天气很好，我们一起去公园散步，顺便买写水果回家。",
    }),
    result({ request_id: "call-whisper", model_group: "whisper-large-v3-turbo", modality: "transcription" }),
    result({ request_id: "call-scheduled", run: "scheduled-1", scheduled: true, created_at: ago(60) }),
  ],
};

const rowOf = (model: string): HTMLElement => {
  const row = screen.getAllByRole("row").find((candidate) => within(candidate).queryByText(model) !== null);
  if (row === undefined) throw new Error(`No table row contains ${model}`);
  return row;
};

const cells = (row: HTMLElement): (string | null)[] =>
  within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

describe("QosSpeechEvaluationPanel", () => {
  beforeEach(() => {
    testQueryClient.clear();
    window.localStorage.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(evaluations);
    vi.mocked(apiClient.getBlob).mockReset();
    vi.mocked(apiClient.put).mockReset();
    vi.mocked(apiClient.post).mockReset();
    Object.defineProperty(URL, "createObjectURL", { value: vi.fn(() => "blob:speech"), configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
  });

  it("shows each reading of the newest run with its latency, real-time factor and ratings", async () => {
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");

    expect(cells(rowOf("IndexTTS-2"))).toEqual(["IndexTTS-2", "Play", "2.00 s", "0.40", "12345", "4.0 (1 ratings)"]);
    expect(
      within(within(rowOf("IndexTTS-2")).getByRole("radiogroup", { name: "Your rating" })).getByRole("radio", {
        name: "4",
      }),
    ).toBeChecked();
    expect(cells(rowOf("Step-Audio-TTS-3B"))).toEqual([
      "Step-Audio-TTS-3B",
      "Failed: the resource pack does not cover this model",
      "-",
      "-",
      "-",
      "-",
    ]);
    expect(screen.getByText("Test sentence: " + SENTENCE)).toBeInTheDocument();
    expect(
      screen.getByText(/^2 speech synthesis · 2 transcription · rated 1\/1 · average character error rate 4.3%$/),
    ).toBeInTheDocument();
  });

  it("shows each transcript against the sentence with the wrong characters marked", async () => {
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    await screen.findByText("SenseVoiceSmall");

    const heard = rowOf("SenseVoiceSmall");
    expect(cells(heard).slice(0, 3)).toEqual(["SenseVoiceSmall", "4.3%", "800 ms"]);
    expect(within(heard).getByText("写", { selector: "mark" })).toBeInTheDocument();
    expect(cells(rowOf("whisper-large-v3-turbo"))).toEqual([
      "whisper-large-v3-turbo",
      "-",
      "2.00 s",
      "Waiting for the probe to report the transcript",
    ]);
    expect(screen.getByText("Original: " + SENTENCE)).toBeInTheDocument();
  });

  it("saves a rating as soon as a score is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.put).mockResolvedValue({ overall: 2, reviewed_at: "2026-11-04T06:05:00Z" });
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");
    const rating = within(rowOf("IndexTTS-2")).getByRole("radiogroup", { name: "Your rating" });

    await user.click(within(rating).getByRole("radio", { name: "2" }));

    expect(apiClient.put).toHaveBeenCalledWith("/qos/speech/review", {
      accessToken: "token",
      query: { request_id: "call-index" },
      body: { overall: 2 },
    });
    expect(within(rating).getByRole("radio", { name: "2" })).toBeChecked();
    expect(within(rating).getByRole("radio", { name: "4" })).not.toBeChecked();
  });

  it("fetches a reading's audio and the recording only when asked to play them", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.getBlob).mockResolvedValue(new Blob(["RIFF"], { type: "audio/wav" }));
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");
    expect(apiClient.getBlob).not.toHaveBeenCalled();

    await user.click(within(rowOf("IndexTTS-2")).getByRole("button", { name: "Play" }));
    expect(await screen.findByLabelText("Audio from IndexTTS-2")).toHaveAttribute("src", "blob:speech");
    await user.click(
      within(screen.getByRole("region", { name: "Transcription" })).getByRole("button", { name: "Play" }),
    );
    expect(await screen.findByLabelText("Recording")).toBeInTheDocument();

    expect(vi.mocked(apiClient.getBlob).mock.calls).toEqual([
      ["/qos/speech/audio", { accessToken: "token", query: { request_id: "call-index" } }],
      ["/qos/speech/recording", { accessToken: "token" }],
    ]);
  });

  it("keeps scheduled runs apart from the runs started by hand", async () => {
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    const scheduled = await screen.findByRole("region", { name: "Scheduled evaluations" });

    await waitFor(() => expect(within(scheduled).getAllByRole("group")).toHaveLength(1));
    expect(within(scheduled).getByText(/^1 speech synthesis · 0 transcription · rated 0\/1/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Manual evaluations" })).getAllByRole("group")).toHaveLength(1);
  });

  it("starts a run from the dialog after showing which models it tests", async () => {
    const user = userEvent.setup();
    const options = {
      available: true,
      models: [
        { model_group: "IndexTTS-2", modality: "speech" },
        { model_group: "SenseVoiceSmall", modality: "transcription" },
      ],
    };
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/speech/evaluations/options" ? options : evaluations,
    );
    vi.mocked(apiClient.post).mockResolvedValue({ models: ["IndexTTS-2", "SenseVoiceSmall"] });
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");

    await user.click(screen.getByRole("button", { name: "Start evaluation" }));
    const dialog = await screen.findByRole("dialog", { name: "Start a speech evaluation" });
    expect(await within(dialog).findByText("SenseVoiceSmall · Transcription")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Start evaluation" }));

    expect(apiClient.post).toHaveBeenCalledWith("/qos/speech/evaluations", { accessToken: "token" });
    expect(await screen.findByText(/IndexTTS-2, SenseVoiceSmall are being tested/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cannot start a run without a media probe", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/qos/speech/evaluations/options" ? { available: false, models: [] } : evaluations,
    );
    renderWithProviders(<QosSpeechEvaluationPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");

    await user.click(screen.getByRole("button", { name: "Start evaluation" }));
    const dialog = await screen.findByRole("dialog", { name: "Start a speech evaluation" });

    expect(await within(dialog).findByText(/No media probe is set up/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Start evaluation" })).toBeDisabled();
  });
});
