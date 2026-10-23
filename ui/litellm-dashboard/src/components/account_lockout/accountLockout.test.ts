import { describe, expect, it } from "vitest";
import { accountLock, withoutLock } from "./accountLockout";

const now = new Date("2026-10-23T06:10:00Z");

describe("accountLockout", () => {
  it("reports a permanent lock even while a temporary lock is still running", () => {
    expect(
      accountLock({ login_locked_at: "2026-10-23T06:00:00Z", login_locked_until: "2026-10-23T06:15:00Z" }, now),
    ).toEqual({ kind: "permanent", lockedAt: "2026-10-23T06:00:00Z" });
  });

  it("reports a temporary lock only until it expires", () => {
    const metadata = { login_failed_attempts: 3, login_locked_until: "2026-10-23T06:15:00Z" };
    expect(accountLock(metadata, now)).toEqual({ kind: "temporary", until: "2026-10-23T06:15:00Z" });
    expect(accountLock(metadata, new Date("2026-10-23T06:15:00Z"))).toBeNull();
  });

  it("treats failures without a lock and missing metadata as unlocked", () => {
    expect(accountLock({ login_failed_attempts: 2 }, now)).toBeNull();
    expect(accountLock(null, now)).toBeNull();
  });

  it("drops only the lockout fields when unlocking", () => {
    const lockedMetadata = {
      team: "x",
      login_locked_at: "2026-10-23T06:00:00Z",
      login_locked_until: "2026-10-23T06:15:00Z",
      login_failed_attempts: 10,
    };
    expect(withoutLock(lockedMetadata)).toEqual({ team: "x" });
  });
});
