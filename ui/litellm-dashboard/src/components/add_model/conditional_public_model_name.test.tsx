import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React, { useEffect, useRef } from "react";
import { useFormContext, useWatch } from "react-hook-form";
import { describe, expect, it } from "vitest";
import { MountedFormHost } from "../../../tests/mounted-form-host";
import type { MountedFormValues } from "../common_components/MountedFormField";
import ConditionalPublicModelName from "./conditional_public_model_name";
import LiteLLMModelNameField from "./litellm_model_name";

const WRITE_BUDGET = 20;

const LoopGuard: React.FC = () => {
  const form = useFormContext<MountedFormValues>();
  const mappings = useWatch({ control: form.control, name: "model_mappings" });
  const writes = useRef(0);

  useEffect(() => {
    writes.current += 1;
    if (writes.current > WRITE_BUDGET) {
      throw new Error(`model_mappings changed ${WRITE_BUDGET}+ times: the mapping effects are looping`);
    }
  }, [mappings]);

  return null;
};

describe("ConditionalPublicModelName", () => {
  it("should render", () => {
    render(
      <MountedFormHost
        defaultValues={{
          model: ["gpt-4"],
          model_mappings: [
            {
              public_name: "gpt-4",
              litellm_model: "gpt-4",
            },
          ],
        }}
      >
        <ConditionalPublicModelName />
      </MountedFormHost>,
    );

    expect(screen.getByText("Model Mappings")).toBeInTheDocument();
    expect(screen.getByText("Public Model Name")).toBeInTheDocument();
    expect(screen.getByText("LiteLLM Model Name")).toBeInTheDocument();
  });

  it("settles after rewriting the custom placeholder mapping to the entered model name", () => {
    render(
      <MountedFormHost
        defaultValues={{
          model: ["custom"],
          custom_model_name: "my-custom-model",
          model_mappings: [
            {
              public_name: "custom",
              litellm_model: "custom",
            },
          ],
        }}
      >
        <ConditionalPublicModelName />
        <LoopGuard />
      </MountedFormHost>,
    );

    expect(screen.getByDisplayValue("my-custom-model")).toBeInTheDocument();
    expect(screen.getByText("my-custom-model")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("custom")).not.toBeInTheDocument();
  });

  it("keeps the public name input focused across keystrokes", async () => {
    const user = userEvent.setup();
    render(
      <MountedFormHost
        defaultValues={{
          model: ["gpt-4"],
          model_mappings: [{ public_name: "gpt-4", litellm_model: "gpt-4" }],
        }}
      >
        <ConditionalPublicModelName />
      </MountedFormHost>,
    );

    const input = screen.getByDisplayValue("gpt-4");
    await user.type(input, "-prod");

    expect(input).toHaveValue("gpt-4-prod");
    expect(input).toHaveFocus();
  });
});

describe("ConditionalPublicModelName with the model name field", () => {
  const renderForm = (defaultValues: MountedFormValues) =>
    render(
      <MountedFormHost defaultValues={defaultValues}>
        <LiteLLMModelNameField selectedProvider="OpenAI" providerModels={["gpt-4o"]} getPlaceholder={() => ""} />
        <ConditionalPublicModelName />
        <LoopGuard />
      </MountedFormHost>,
    );

  it("does not remount the public name input while the custom model name is typed", async () => {
    const user = userEvent.setup();
    renderForm({ custom_llm_provider: "OpenAI", model: ["custom"] });

    const customInput = screen.getByPlaceholderText("Enter custom model name");
    await user.type(customInput, "q");
    const publicInput = screen.getAllByDisplayValue("q").find((element) => element !== customInput);
    await user.type(customInput, "wen3");

    expect(customInput).toHaveFocus();
    expect(customInput).toHaveValue("qwen3");
    expect(publicInput).toHaveValue("qwen3");
    expect(publicInput).toBeInTheDocument();
  });

  it("keeps an edited public name on one row while the custom model name changes", async () => {
    const user = userEvent.setup();
    renderForm({ custom_llm_provider: "OpenAI", model: ["gpt-4o", "custom"] });

    const gptPublicName = await screen.findByDisplayValue("gpt-4o");
    await user.clear(gptPublicName);
    await user.type(gptPublicName, "fast-chat");
    await user.type(screen.getByPlaceholderText("Enter custom model name"), "qwen3");

    expect(screen.getByDisplayValue("fast-chat")).toBeInTheDocument();
    expect(screen.getByText("qwen3")).toBeInTheDocument();
  });
});
