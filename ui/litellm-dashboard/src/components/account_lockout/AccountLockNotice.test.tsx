import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AccountLockNotice from "./AccountLockNotice";
import { apiClient } from "@/components/networking";

vi.mock("@/components/networking", () => ({ apiClient: { post: vi.fn() } }));

const locked = { login_failed_attempts: 3, login_locked_at: "2026-10-23T06:00:00Z" };

describe("AccountLockNotice", () => {
  beforeEach(() => {
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.post).mockResolvedValue({ user_id: "user-1", unlocked: true });
  });

  it("renders nothing for an account that is not locked", () => {
    const { container } = render(
      <AccountLockNotice accessToken="token" userId="user-1" metadata={{ login_failed_attempts: 2 }} canUnlock onUnlocked={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("lets a proxy admin unlock the account", async () => {
    const user = userEvent.setup();
    const onUnlocked = vi.fn();
    render(<AccountLockNotice accessToken="token" userId="user-1" metadata={locked} canUnlock onUnlocked={onUnlocked} />);

    expect(screen.getByText("This account is locked")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Unlock account" }));

    expect(apiClient.post).toHaveBeenCalledWith("/account_lockout/unlock", { accessToken: "token", body: { user_id: "user-1" } });
    expect(onUnlocked).toHaveBeenCalledOnce();
  });

  it("shows the lock without an unlock button to users who cannot unlock", () => {
    render(<AccountLockNotice accessToken="token" userId="user-1" metadata={locked} canUnlock={false} onUnlocked={vi.fn()} />);
    expect(screen.getByText("This account is locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unlock account" })).not.toBeInTheDocument();
  });
});
