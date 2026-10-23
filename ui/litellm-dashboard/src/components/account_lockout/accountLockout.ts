export const LOCKED_AT_KEY = "login_locked_at";
export const ACCOUNT_LOCKED_HINT = "Locked after 3 failed sign-in attempts. Open the user to unlock the account.";

export const accountLockedAt = (metadata: unknown): string | null => {
  if (metadata === null || typeof metadata !== "object" || !Object.hasOwn(metadata, LOCKED_AT_KEY)) return null;
  const lockedAt = (metadata as Record<string, unknown>)[LOCKED_AT_KEY];
  return typeof lockedAt === "string" ? lockedAt : null;
};

export const withoutLock = <T extends Record<string, unknown>>(metadata: T): Omit<T, "login_locked_at" | "login_failed_attempts"> => {
  const { login_locked_at: _lockedAt, login_failed_attempts: _attempts, ...rest } = metadata;
  return rest;
};
