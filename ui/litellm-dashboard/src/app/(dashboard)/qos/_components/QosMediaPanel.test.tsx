import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QosMediaPanel from "./QosMediaPanel";
import { apiClient } from "@/components/networking";
import { renderWithProviders, testQueryClient } from "../../../../../tests/test-utils";

vi.mock("@/components/networking", () => ({ apiClient: { get: vi.fn() } }));

const media = {
  start_time: "2026-10-28T06:00:00Z",
  end_time: "2026-10-29T06:00:00Z",
  audio: [
    {
      model_group: "IndexTTS-2",
      modality: "speech",
      requests: 6,
      failed_requests: 3,
      audio_seconds: 8.29,
      input_chars: 35,
      latency_ms: { p50: 8400, p95: 8660, p99: 8680 },
      real_time_factor: { p50: 2.69, p95: 4.09, p99: 4.21 },
    },
    {
      model_group: "SenseVoiceSmall",
      modality: "transcription",
      requests: 3,
      failed_requests: 0,
      audio_seconds: 6.92,
      input_chars: 0,
      latency_ms: { p50: 694, p95: 732.7, p99: 736.1 },
      real_time_factor: { p50: 0.1897, p95: 0.1986, p99: 0.1994 },
    },
  ],
  video: [
    {
      model_group: "LTX-2",
      submitted: 5,
      failed_submissions: 1,
      succeeded: 2,
      failed: 1,
      cancelled: 0,
      queue_ms: { p50: 811, p95: 4000, p99: 4000 },
      run_ms: { p50: 85200, p95: 91000, p99: 91000 },
      task_price: 3,
    },
  ],
};

const cellsOfRow = (text: string): (string | null)[] => {
  const row = screen.getAllByRole("row").find((candidate) => within(candidate).queryByText(text) !== null);
  if (row === undefined) throw new Error(`No table row contains ${text}`);
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
};

describe("QosMediaPanel", () => {
  beforeEach(() => {
    testQueryClient.clear();
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue(media);
  });

  it("shows speech synthesis and transcription per model with audio length and real-time factor", async () => {
    renderWithProviders(<QosMediaPanel accessToken="token" />);

    await screen.findByText("IndexTTS-2");
    expect(cellsOfRow("IndexTTS-2")).toEqual([
      "IndexTTS-2",
      "Speech synthesis",
      "6",
      "50.0%",
      "8.3 s",
      "35",
      "8.40 s / 8.66 s",
      "2.69 / 4.09",
    ]);
    expect(cellsOfRow("SenseVoiceSmall")).toEqual([
      "SenseVoiceSmall",
      "Transcription",
      "3",
      "100.0%",
      "6.9 s",
      "-",
      "694 ms / 733 ms",
      "0.19 / 0.20",
    ]);
  });

  it("counts video tasks by outcome, including tasks that have no result yet", async () => {
    renderWithProviders(<QosMediaPanel accessToken="token" />);

    await screen.findByText("LTX-2");
    expect(cellsOfRow("LTX-2")).toEqual([
      "LTX-2",
      "5",
      "1",
      "2",
      "1",
      "0",
      "1",
      "811 ms / 4.00 s",
      "85.20 s / 91.00 s",
      "3.00",
    ]);
  });

  it("keeps how each table is measured hidden until its question mark is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosMediaPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");

    expect(screen.queryByText(/Below 1 is faster than real time/)).not.toBeInTheDocument();
    expect(screen.queryByText(/nobody checked after they finished/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "How speech synthesis and transcription are measured" }));
    const audioHelp = await screen.findByRole("dialog");
    expect(within(audioHelp).getByText("Real-time factor")).toBeInTheDocument();
    expect(within(audioHelp).getByText(/Below 1 is faster than real time/)).toBeInTheDocument();
    expect(within(audioHelp).queryByText("No result yet")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "How video generation is measured" }));
    expect(await screen.findByText(/nobody checked after they finished/)).toBeInTheDocument();
  });

  it("asks /qos/media for the last 24 hours by default", async () => {
    renderWithProviders(<QosMediaPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");

    const [path, options] = vi.mocked(apiClient.get).mock.calls[0];
    expect(path).toBe("/qos/media");
    const query = options?.query;
    expect(Date.parse(String(query?.end_time)) - Date.parse(String(query?.start_time))).toBe(24 * 60 * 60 * 1000);
  });

  it("requests all retained history when All is selected", async () => {
    const user = userEvent.setup();
    renderWithProviders(<QosMediaPanel accessToken="token" />);
    await screen.findByText("IndexTTS-2");

    await user.click(screen.getByLabelText("Time range"));
    await user.click(await screen.findByRole("option", { name: "All", exact: true }));

    await waitFor(() => expect(vi.mocked(apiClient.get).mock.lastCall?.[1]?.query?.all_time).toBe(true));
    expect(vi.mocked(apiClient.get).mock.lastCall?.[1]?.query?.start_time).toBeUndefined();
  });

  it("says when the time range has no audio or video traffic", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...media, audio: [], video: [] });
    renderWithProviders(<QosMediaPanel accessToken="token" />);

    expect(
      await screen.findByText("No speech synthesis or transcription requests in this time range"),
    ).toBeInTheDocument();
    expect(screen.getByText("No video tasks in this time range")).toBeInTheDocument();
  });

  it("shows the server's error message when loading fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new Error("Only users of this gateway can view service quality metrics"),
    );
    renderWithProviders(<QosMediaPanel accessToken="token" />);

    expect(await screen.findByText("Could not load audio and video metrics")).toBeInTheDocument();
    expect(screen.getByText("Only users of this gateway can view service quality metrics")).toBeInTheDocument();
  });
});
