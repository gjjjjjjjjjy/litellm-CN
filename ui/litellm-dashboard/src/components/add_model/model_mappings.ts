import { Providers } from "../provider_info_helpers";

export interface ModelMapping {
  readonly public_name: string;
  readonly litellm_model: string;
}

export const CUSTOM_MODEL_OPTION = "custom";
export const WILDCARD_MODEL_OPTION = "all-wildcard";

export const selectedModelsOf = (value: unknown): readonly string[] => {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string" && item !== "");
  return typeof value === "string" && value.trim() !== "" ? [value.trim()] : [];
};

const upstreamModel = (model: string, provider: Providers | null): string =>
  provider === Providers.Azure ? `azure/${model}` : model;

export const deriveModelMappings = (
  selectedModels: readonly string[],
  customModelName: string,
  provider: Providers | null,
  current: readonly ModelMapping[],
): ModelMapping[] => {
  if (selectedModels.includes(WILDCARD_MODEL_OPTION)) return [];
  const publicNames = new Map(current.map((mapping) => [mapping.litellm_model, mapping.public_name]));
  return selectedModels
    .map((model) => (model === CUSTOM_MODEL_OPTION ? customModelName.trim() : model))
    .filter((model) => model !== "")
    .map((model) => {
      const litellmModel = upstreamModel(model, provider);
      return { public_name: publicNames.get(litellmModel) ?? model, litellm_model: litellmModel };
    });
};

export const sameMappings = (left: readonly ModelMapping[], right: readonly ModelMapping[]): boolean =>
  left.length === right.length &&
  left.every(
    (mapping, index) =>
      mapping.public_name === right[index].public_name && mapping.litellm_model === right[index].litellm_model,
  );
