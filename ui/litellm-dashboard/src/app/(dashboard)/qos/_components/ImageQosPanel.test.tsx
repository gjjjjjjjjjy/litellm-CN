import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ImageQosPanel from "./ImageQosPanel";
import { IMAGE_PROMPTS } from "./imagePrompts";

const startRun = vi.hoisted(() => vi.fn());

vi.mock("@/app/(dashboard)/hooks/useAuthorized", () => ({
  default: () => ({ userRole: "Admin", isViewOnly: false }),
}));
vi.mock("@/app/(dashboard)/hooks/qos/useQosImages", () => ({
  useImageConfig: () => ({
    data: {
      max_images: 32,
      models: {
        image_test: {
          unit_cost_cny: 0.01,
          supports_seed: true,
          supports_negative_prompt: true,
          max_prompt_chars: 2000,
        },
      },
    },
    isFetching: false,
    refetch: vi.fn(),
  }),
  useImageRuns: () => ({ data: [], isFetching: false, isError: false, refetch: vi.fn() }),
  useImageRun: () => ({ data: null, isFetching: false, refetch: vi.fn() }),
  useStartImageRun: () => ({ mutate: startRun, isPending: false, isError: false }),
  useRateImage: () => ({ mutate: vi.fn() }),
}));

describe("ImageQosPanel prompt modes", () => {
  beforeEach(() => {
    startRun.mockReset();
  });

  it("submits entered prompts and keeps the first-N preset mode available", async () => {
    const user = userEvent.setup();
    render(<ImageQosPanel accessToken="test-token" />);

    await user.click(screen.getByRole("button", { name: "自填 Prompt" }));
    const submit = screen.getByRole("button", { name: "Start image test" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: /生成提示词/ }), {
      target: { value: "  一只橘猫坐在窗边  " },
    });
    await user.click(screen.getByRole("button", { name: "添加 Prompt" }));
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getAllByRole("textbox", { name: /生成提示词/ })[1], {
      target: { value: "一只白狗在草地上" },
    });
    fireEvent.change(screen.getAllByRole("textbox", { name: /检查要求/ })[1], { target: { value: "只有一只狗" } });
    await user.click(screen.getAllByRole("button", { name: "删除" })[0]);
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    expect(startRun).toHaveBeenCalledWith(
      expect.objectContaining({
        model: "image_test",
        prompts: [{ id: "manual_2", text: "一只白狗在草地上", check: "只有一只狗", negative_prompt: undefined }],
        seeds: [42],
      }),
      expect.any(Object),
    );

    await user.click(screen.getByRole("button", { name: "自选" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: /Prompt 数量/ }), { target: { value: "3" } });
    await user.click(submit);

    expect(startRun).toHaveBeenLastCalledWith(
      expect.objectContaining({ prompts: IMAGE_PROMPTS.slice(0, 3) }),
      expect.any(Object),
    );
  });
});
