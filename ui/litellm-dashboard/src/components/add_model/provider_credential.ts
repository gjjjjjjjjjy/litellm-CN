import type { MountedFormValues } from "../common_components/MountedFormField";
import type { CredentialItem, ProviderCreateInfo, ProviderCredentialFieldMetadata } from "../networking";

export const SAVE_PROVIDER_CREDENTIAL = "save_provider_credential";

export interface ProviderCredential {
  credential_name: string;
  display_name: string;
  credential_values: Record<string, unknown>;
  credential_info: { custom_llm_provider: string };
}

export interface ProviderCredentialPlan {
  credential: ProviderCredential | null;
  modelValues: MountedFormValues;
}

const sameProvider = (stored: string | undefined, provider: string): boolean =>
  stored !== undefined && stored.toLowerCase() === provider.toLowerCase();

export const savedCredentialFor = (credentials: readonly CredentialItem[], provider: string): string | null => {
  const saved = credentials.filter((credential) =>
    sameProvider(credential.credential_info.custom_llm_provider, provider),
  );
  return saved.length === 1 ? saved[0].credential_name : null;
};

const SECRET_FIELD_TYPES: ReadonlySet<ProviderCredentialFieldMetadata["field_type"]> = new Set([
  "password",
  "textarea",
  "upload",
]);

const filled = (value: unknown): boolean => value !== undefined && value !== null && value !== "";

const unusedName = (base: string, taken: ReadonlySet<string>): string => {
  if (!taken.has(base)) {
    return base;
  }
  let suffix = 2;
  while (taken.has(`${base}-${suffix}`)) {
    suffix += 1;
  }
  return `${base}-${suffix}`;
};

/** Moves the provider fields typed alongside a key into a new credential the model then names. */
export const planProviderCredential = (
  values: MountedFormValues,
  provider: ProviderCreateInfo | undefined,
  credentials: readonly CredentialItem[],
): ProviderCredentialPlan => {
  const { [SAVE_PROVIDER_CREDENTIAL]: save, ...modelValues } = values;
  if (save !== true) {
    return { credential: null, modelValues };
  }
  if (provider === undefined) {
    throw new Error("The provider's credential fields are not loaded");
  }
  const fields = provider.credential_fields.filter((field) => filled(modelValues[field.key]));
  if (!fields.some((field) => SECRET_FIELD_TYPES.has(field.field_type))) {
    return { credential: null, modelValues };
  }
  const name = unusedName(
    provider.litellm_provider,
    new Set(credentials.map((credential) => credential.credential_name)),
  );
  const keys = new Set(fields.map((field) => field.key));
  const apiBase = modelValues.api_base;
  return {
    credential: {
      credential_name: name,
      display_name:
        typeof apiBase === "string" && keys.has("api_base")
          ? `${provider.provider_display_name} · ${apiBase}`
          : provider.provider_display_name,
      credential_values: Object.fromEntries(fields.map((field) => [field.key, modelValues[field.key]])),
      credential_info: { custom_llm_provider: provider.provider },
    },
    modelValues: {
      ...Object.fromEntries(Object.entries(modelValues).filter(([key]) => !keys.has(key))),
      litellm_credential_name: name,
    },
  };
};
