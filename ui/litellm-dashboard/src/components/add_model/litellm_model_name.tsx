import React from "react";
import { MultiSelect } from "@/components/shared/MultiSelect";
import { useFormContext, useWatch } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { requiredRule } from "../common_components/formRules";
import { labelWithHint } from "@/components/shared/form/LabelWithHint";
import { MountedFormField, type MountedFormValues } from "../common_components/MountedFormField";
import { Providers, resolveProvider } from "../provider_info_helpers";
import { CUSTOM_MODEL_OPTION, selectedModelsOf, WILDCARD_MODEL_OPTION } from "./model_mappings";

interface LiteLLMModelNameFieldProps {
  selectedProvider: string | null;
  providerModels: string[];
  getPlaceholder: (provider: string) => string;
}

const LiteLLMModelNameField: React.FC<LiteLLMModelNameFieldProps> = ({
  selectedProvider,
  providerModels,
  getPlaceholder,
}) => {
  const form = useFormContext<MountedFormValues>();
  const modelValue = useWatch({ control: form.control, name: "model" });
  const selectedModels = selectedModelsOf(modelValue);
  const provider = selectedProvider === null ? null : resolveProvider(selectedProvider);
  const typesModelName =
    provider === Providers.Azure || provider === Providers.OpenAI_Compatible || provider === Providers.Ollama;
  const focusCustomInput = React.useRef(false);

  const handleModelSelection = (onChange: (value: string[]) => void, value: string[]) => {
    focusCustomInput.current = value.includes(CUSTOM_MODEL_OPTION) && !selectedModels.includes(CUSTOM_MODEL_OPTION);
    onChange(value);
  };

  const focusWhenJustSelected = (node: HTMLInputElement | null) => {
    if (node === null || !focusCustomInput.current) return;
    focusCustomInput.current = false;
    node.focus();
  };

  return (
    <>
      <MountedFormField
        name="model"
        label={labelWithHint("LiteLLM Model Name(s)", "The model name LiteLLM will send to the LLM API")}
        required
        rules={{
          validate: {
            required: requiredRule(
              `Please enter ${provider === Providers.Azure ? "a deployment name" : "at least one model"}.`,
            ),
          },
        }}
        className="mb-0"
      >
        {(control) =>
          typesModelName ? (
            <Input
              id={control.id}
              value={(control.value as string | undefined) ?? ""}
              onBlur={control.onBlur}
              placeholder={selectedProvider === null ? "Select a provider first" : getPlaceholder(selectedProvider)}
              onChange={control.onChange}
            />
          ) : providerModels.length > 0 && !(typeof control.value === "string" && control.value !== "") ? (
            <MultiSelect
              id={control.id}
              placeholder="Select models"
              emptyText="No models found"
              value={Array.isArray(control.value) ? control.value : []}
              onValueChange={(value: string[]) => handleModelSelection(control.onChange, value)}
              options={[
                {
                  label: "Custom Model Name (Enter below)",
                  value: CUSTOM_MODEL_OPTION,
                },
                {
                  label: `All ${selectedProvider ?? "provider"} Models (Wildcard)`,
                  value: WILDCARD_MODEL_OPTION,
                },
                ...providerModels.map((model) => ({
                  label: model,
                  value: model,
                })),
              ]}
              className="w-full"
            />
          ) : (
            <Input
              id={control.id}
              value={(control.value as string | undefined) ?? ""}
              onChange={control.onChange}
              onBlur={control.onBlur}
              placeholder={selectedProvider === null ? "Select a provider first" : getPlaceholder(selectedProvider)}
            />
          )
        }
      </MountedFormField>

      {selectedModels.includes(CUSTOM_MODEL_OPTION) && (
        <MountedFormField
          name="custom_model_name"
          required
          rules={{ validate: { required: requiredRule("Please enter a custom model name.") } }}
          className="mt-2"
        >
          {(control) => (
            <Input
              ref={focusWhenJustSelected}
              id={control.id}
              value={(control.value as string | undefined) ?? ""}
              onBlur={control.onBlur}
              placeholder={provider === Providers.Azure ? "Enter Azure deployment name" : "Enter custom model name"}
              onChange={control.onChange}
            />
          )}
        </MountedFormField>
      )}
      <div className="grid grid-cols-24">
        <p className="col-start-11 col-span-14 text-sm mb-3 mt-1">
          {provider === Providers.Azure
            ? "Your deployment name will be saved as the public model name, and LiteLLM will use 'azure/deployment-name' internally"
            : "The model name LiteLLM will send to the LLM API"}
        </p>
      </div>
    </>
  );
};

export default LiteLLMModelNameField;
