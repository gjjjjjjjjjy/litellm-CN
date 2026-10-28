export type AccountLock =
  | { readonly kind: "permanent"; readonly lockedAt: string }
  | { readonly kind: "temporary"; readonly until: string };

export const ACCOUNT_LOCK_LABELS: Readonly<Record<AccountLock["kind"], string>> = {
  permanent: "Locked",
  temporary: "Temporarily locked",
};

export const ACCOUNT_LOCK_HINTS: Readonly<Record<AccountLock["kind"], string>> = {
  permanent: "Locked after 10 failed sign-in attempts. Open the user to unlock the account.",
  temporary: "Locked for 15 minutes after 3 failed sign-in attempts. Open the user to unlock the account now.",
};

export const accountLock = (metadata: unknown, now: Date): AccountLock | null => {
  if (metadata === null || typeof metadata !== "object") return null;
  const { login_locked_at: lockedAt, login_locked_until: until } = metadata as Record<string, unknown>;
  if (typeof lockedAt === "string") return { kind: "permanent", lockedAt };
  if (typeof until === "string" && new Date(until) > now) return { kind: "temporary", until };
  return null;
};

export const withoutLock = <T extends Record<string, unknown>>(
  metadata: T,
): Omit<T, "login_locked_at" | "login_locked_until" | "login_failed_attempts"> => {
  const {
    login_locked_at: _lockedAt,
    login_locked_until: _until,
    login_failed_attempts: _attempts,
    ...rest
  } = metadata;
  return rest;
};
