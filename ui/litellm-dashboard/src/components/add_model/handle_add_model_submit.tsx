import { toast } from "@/lib/toast";
import { Model, modelCreateCall } from "../networking";
import { provider_map } from "../provider_info_helpers";
import { ptuPickerToUtcIso } from "../../utils/ptuDatetime";

const hasValue = (value: unknown): boolean => value !== undefined && value !== null && value !== "";

const perToken = (perMillion: unknown): number => Number(perMillion) / 1000000;

/**
 * Converts the per-million-token prices entered in the form to per-token prices, once for all deployments.
 * Cache read defaults to the input price; cache write stays unset so the backend keeps the model default.
 */
const withPerTokenCosts = (formValues: Record<string, any>): Record<string, any> => {
  const {
    input_cost_per_token,
    output_cost_per_token,
    cache_read_input_token_cost,
    cache_creation_input_token_cost,
    ...rest
  } = formValues;
  const inputCost = hasValue(input_cost_per_token) ? perToken(input_cost_per_token) : undefined;
  const cacheReadCost = hasValue(cache_read_input_token_cost) ? perToken(cache_read_input_token_cost) : inputCost;
  return {
    ...rest,
    ...(inputCost !== undefined && { input_cost_per_token: inputCost }),
    ...(hasValue(output_cost_per_token) && { output_cost_per_token: perToken(output_cost_per_token) }),
    ...(cacheReadCost !== undefined && { cache_read_input_token_cost: cacheReadCost }),
    ...(hasValue(cache_creation_input_token_cost) && {
      cache_creation_input_token_cost: perToken(cache_creation_input_token_cost),
    }),
  };
};

export const prepareModelAddRequest = async (formValues: Record<string, any>, accessToken: string, form: any) => {
  try {
    // Get model mappings and safely remove from formValues
    const modelMappings = formValues["model_mappings"] || [];
    if ("model_mappings" in formValues) {
      delete formValues["model_mappings"];
    }

    // Handle wildcard case
    if (formValues["model"] && formValues["model"].includes("all-wildcard")) {
      const customProviderKey = formValues["custom_llm_provider"] as string;
      const mappedProvider =
        provider_map[customProviderKey as keyof typeof provider_map] ?? customProviderKey.toLowerCase();
      const litellm_custom_provider = mappedProvider;
      const wildcardModel = litellm_custom_provider + "/*";
      formValues["model_name"] = wildcardModel;
      modelMappings.push({
        public_name: wildcardModel,
        litellm_model: wildcardModel,
      });
      formValues["model"] = wildcardModel;
    }

    const pricedValues = withPerTokenCosts(formValues);

    // Create a deployment for each mapping
    const deployments = [];
    for (const mapping of modelMappings) {
      const litellmParamsObj: Record<string, any> = {};
      const modelInfoObj: Record<string, any> = {};

      // Set the model name and litellm model from the mapping
      const modelName = mapping.public_name;
      litellmParamsObj["model"] = mapping.litellm_model;

      // Iterate through the key-value pairs in formValues
      litellmParamsObj["model"] = mapping.litellm_model;
      for (const [key, value] of Object.entries(pricedValues)) {
        if (value === "") {
          continue;
        }
        if (key === "litellm_credential_name" && value == null) {
          continue;
        }
        // Skip the custom_pricing and pricing_model fields as they're only used for UI control
        if (key === "custom_pricing" || key === "pricing_model" || key === "cache_control") {
          continue;
        }
        if (key === "model_name" || key === "custom_model_name") {
          continue;
        } else if (key == "custom_llm_provider") {
          const providerKey = value as string;
          const mappingResult = provider_map[providerKey as keyof typeof provider_map] ?? providerKey.toLowerCase();
          litellmParamsObj["custom_llm_provider"] = mappingResult;
        } else if (key == "model") {
          continue;
        }
        // Check if key is "base_model"
        else if (key === "base_model") {
          // Add key-value pair to model_info dictionary
          modelInfoObj[key] = value;
        } else if (key === "team_id") {
          modelInfoObj["team_id"] = value;
        } else if (key === "model_access_group") {
          modelInfoObj["access_groups"] = value;
        } else if (key == "mode") {
          modelInfoObj["mode"] = value;

          // remove "mode" from litellmParams
          delete litellmParamsObj["mode"];
        } else if (key == "litellm_extra_params") {
          let litellmExtraParams = {};
          if (value && value != undefined) {
            try {
              litellmExtraParams = JSON.parse(value);
            } catch (error) {
              toast.fromError("Failed to parse LiteLLM Extra Params: " + error);
              throw new Error("Failed to parse litellm_extra_params: " + error);
            }
            if ("litellm_credential_name" in litellmExtraParams && formValues.litellm_credential_name) {
              delete litellmExtraParams.litellm_credential_name;
            }
            for (const [key, value] of Object.entries(litellmExtraParams)) {
              litellmParamsObj[key] = value;
            }
          }
        } else if (key == "model_info_params") {
          let modelInfoParams = {};
          if (value && value != undefined) {
            try {
              modelInfoParams = JSON.parse(value);
            } catch (error) {
              toast.fromError("Failed to parse LiteLLM Extra Params: " + error);
              throw new Error("Failed to parse litellm_extra_params: " + error);
            }
            for (const [key, value] of Object.entries(modelInfoParams)) {
              modelInfoObj[key] = value;
            }
          }
        }

        // Handle the pricing fields
        else if (
          key === "input_cost_per_token" ||
          key === "output_cost_per_token" ||
          key === "input_cost_per_second" ||
          key === "cache_read_input_token_cost" ||
          key === "cache_creation_input_token_cost"
        ) {
          if (value !== undefined && value !== null && value !== "") {
            litellmParamsObj[key] = Number(value);
          }
          continue;
        }

        // Handle the PTU flat-cost fields (attributed to the team via model_info)
        else if (key === "ptu_count" || key === "cost_per_ptu_per_hour") {
          if (value !== undefined && value !== null && value !== "") {
            modelInfoObj[key] = Number(value);
          }
          continue;
        }

        // Handle the PTU effective window (DatePicker dayjs value -> ISO 8601 UTC string)
        else if (key === "ptu_effective_from" || key === "ptu_effective_to") {
          const iso = ptuPickerToUtcIso(value);
          if (iso !== null) {
            modelInfoObj[key] = iso;
          }
          continue;
        }

        // Check if key is any of the specified API related keys
        else {
          // Add key-value pair to litellm_params dictionary
          litellmParamsObj[key] = value;
        }
      }

      deployments.push({ litellmParamsObj, modelInfoObj, modelName });
    }

    return deployments;
  } catch (error) {
    toast.fromError("Failed to create model: " + error);
  }
};

export const handleAddModelSubmit = async (
  values: any,
  accessToken: string,
  form: any,
  callback?: () => void,
): Promise<boolean> => {
  try {
    const deployments = await prepareModelAddRequest(values, accessToken, form);

    if (!deployments || deployments.length === 0) {
      return false;
    }

    // Create each deployment
    for (const deployment of deployments) {
      const { litellmParamsObj, modelInfoObj, modelName } = deployment;

      const new_model: Model = {
        model_name: modelName,
        litellm_params: litellmParamsObj,
        model_info: modelInfoObj,
      };

      await modelCreateCall(accessToken, new_model);
    }

    callback && callback();
    form.resetFields();
    return true;
  } catch (error) {
    toast.fromError("Failed to add model: " + error);
    return false;
  }
};
