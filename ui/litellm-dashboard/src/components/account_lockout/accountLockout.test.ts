import { describe, expect, it } from "vitest";
import { accountLockedAt, withoutLock } from "./accountLockout";

describe("accountLockout", () => {
  it("reads the lock time only when the account is locked", () => {
    expect(accountLockedAt({ login_locked_at: "2026-10-23T06:00:00Z", login_failed_attempts: 3 })).toBe(
      "2026-10-23T06:00:00Z",
    );
    expect(accountLockedAt({ login_failed_attempts: 2 })).toBeNull();
    expect(accountLockedAt(null)).toBeNull();
  });

  it("drops only the lockout fields when unlocking", () => {
    expect(withoutLock({ team: "x", login_locked_at: "2026-10-23T06:00:00Z", login_failed_attempts: 3 })).toEqual({
      team: "x",
    });
  });
});
