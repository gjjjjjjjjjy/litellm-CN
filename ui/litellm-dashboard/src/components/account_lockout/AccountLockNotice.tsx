"use client";

import { LockKeyhole } from "lucide-react";

import { apiClient } from "@/components/networking";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";
import { type AccountLock, accountLock } from "./accountLockout";

interface AccountLockNoticeProps {
  readonly accessToken: string | null;
  readonly userId: string;
  readonly metadata: unknown;
  readonly canUnlock: boolean;
  readonly onUnlocked: () => void;
}

const lockText = (lock: AccountLock): { readonly title: string; readonly description: string } => {
  switch (lock.kind) {
    case "permanent":
      return {
        title: "This account is locked",
        description: `Locked after 10 failed sign-in attempts on ${new Date(lock.lockedAt).toLocaleString()}. The user cannot sign in until an administrator unlocks the account.`,
      };
    case "temporary":
      return {
        title: "This account is temporarily locked",
        description: `Locked after 3 failed sign-in attempts until ${new Date(lock.until).toLocaleString()}. Unlock the account to let the user sign in now.`,
      };
  }
};

export default function AccountLockNotice({ accessToken, userId, metadata, canUnlock, onUnlocked }: AccountLockNoticeProps) {
  const lock = accountLock(metadata, new Date());
  if (lock === null) return null;
  const { title, description } = lockText(lock);

  const unlock = async () => {
    try {
      await apiClient.post("/account_lockout/unlock", { accessToken, body: { user_id: userId } });
      toast.success("Account unlocked");
      onUnlocked();
    } catch (error) {
      toast.fromError(error);
    }
  };

  return (
    <Alert variant="destructive" className="mb-6">
      <LockKeyhole />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{description}</AlertDescription>
      {canUnlock && (
        <AlertAction>
          <Button variant="outline" size="sm" onClick={() => void unlock()}>
            Unlock account
          </Button>
        </AlertAction>
      )}
    </Alert>
  );
}
