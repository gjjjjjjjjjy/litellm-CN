import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { getPlaceholder, Providers } from "../provider_info_helpers";
import { MountedFormHost } from "../../../tests/mounted-form-host";
import LiteLLMModelNameField from "./litellm_model_name";

describe("LitellmModelNameField", () => {
  it("should render", () => {
    render(
      <MountedFormHost>
        <LiteLLMModelNameField
          selectedProvider={Providers.OpenAI}
          providerModels={[]}
          getPlaceholder={getPlaceholder}
        />
      </MountedFormHost>,
    );
    expect(screen.getByText("LiteLLM Model Name(s)")).toBeInTheDocument();
  });

  it("should show Azure placeholder as 'my-deployment'", () => {
    render(
      <MountedFormHost>
        <LiteLLMModelNameField selectedProvider={Providers.Azure} providerModels={[]} getPlaceholder={getPlaceholder} />
      </MountedFormHost>,
    );
    expect(screen.getByPlaceholderText("my-deployment")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("gpt-3.5-turbo")).not.toBeInTheDocument();
  });

  it("asks for a typed model name for OpenAI-compatible endpoints chosen by their provider key", () => {
    render(
      <MountedFormHost>
        <LiteLLMModelNameField
          selectedProvider="OpenAI_Compatible"
          providerModels={["gpt-4o"]}
          getPlaceholder={() => "my-model"}
        />
      </MountedFormHost>,
    );
    expect(screen.getByPlaceholderText("my-model")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("moves the cursor into the custom model name box when the custom option is chosen", async () => {
    const user = userEvent.setup();
    render(
      <MountedFormHost>
        <LiteLLMModelNameField
          selectedProvider={Providers.OpenAI}
          providerModels={["gpt-4o"]}
          getPlaceholder={getPlaceholder}
        />
      </MountedFormHost>,
    );

    await user.click(screen.getByRole("combobox", { name: "Select models" }));
    await user.click(await screen.findByRole("option", { name: "Custom Model Name (Enter below)" }));

    expect(screen.getByPlaceholderText("Enter custom model name")).toHaveFocus();
  });
});
