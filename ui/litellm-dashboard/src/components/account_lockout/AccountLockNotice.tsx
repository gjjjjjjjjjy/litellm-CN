"use client";

import { LockKeyhole } from "lucide-react";

import { apiClient } from "@/components/networking";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";
import { accountLockedAt } from "./accountLockout";

interface AccountLockNoticeProps {
  readonly accessToken: string | null;
  readonly userId: string;
  readonly metadata: unknown;
  readonly canUnlock: boolean;
  readonly onUnlocked: () => void;
}

export default function AccountLockNotice({ accessToken, userId, metadata, canUnlock, onUnlocked }: AccountLockNoticeProps) {
  const lockedAt = accountLockedAt(metadata);
  if (lockedAt === null) return null;

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
      <AlertTitle>This account is locked</AlertTitle>
      <AlertDescription>
        {`Locked after 3 failed sign-in attempts on ${new Date(lockedAt).toLocaleString()}. The user cannot sign in until an administrator unlocks the account.`}
      </AlertDescription>
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
