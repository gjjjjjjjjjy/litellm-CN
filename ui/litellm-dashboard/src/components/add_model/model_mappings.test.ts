import { describe, expect, it } from "vitest";
import { Providers } from "../provider_info_helpers";
import { deriveModelMappings, selectedModelsOf } from "./model_mappings";

describe("selectedModelsOf", () => {
  it("treats a typed model name as one selection and blank input as none", () => {
    expect(selectedModelsOf(" qwen3-max ")).toEqual(["qwen3-max"]);
    expect(selectedModelsOf("")).toEqual([]);
    expect(selectedModelsOf(undefined)).toEqual([]);
    expect(selectedModelsOf(["gpt-4o", ""])).toEqual(["gpt-4o"]);
  });
});

describe("deriveModelMappings", () => {
  it("maps each selected model to itself and replaces the custom option with the typed name", () => {
    expect(deriveModelMappings(["gpt-4o", "custom"], "qwen3-max", Providers.OpenAI, [])).toEqual([
      { public_name: "gpt-4o", litellm_model: "gpt-4o" },
      { public_name: "qwen3-max", litellm_model: "qwen3-max" },
    ]);
  });

  it("leaves the custom row out until a name is typed, and maps nothing for a wildcard", () => {
    expect(deriveModelMappings(["custom"], "  ", Providers.OpenAI, [])).toEqual([]);
    expect(deriveModelMappings(["all-wildcard"], "", Providers.OpenAI, [])).toEqual([]);
  });

  it("prefixes Azure deployments for the upstream call while keeping the plain public name", () => {
    expect(deriveModelMappings(["my-deployment"], "", Providers.Azure, [])).toEqual([
      { public_name: "my-deployment", litellm_model: "azure/my-deployment" },
    ]);
  });

  it("keeps a public name the user edited while other selections change", () => {
    const edited = [{ public_name: "fast-chat", litellm_model: "gpt-4o" }];
    expect(deriveModelMappings(["gpt-4o", "custom"], "qwen3-max", Providers.OpenAI, edited)).toEqual([
      { public_name: "fast-chat", litellm_model: "gpt-4o" },
      { public_name: "qwen3-max", litellm_model: "qwen3-max" },
    ]);
  });
});
