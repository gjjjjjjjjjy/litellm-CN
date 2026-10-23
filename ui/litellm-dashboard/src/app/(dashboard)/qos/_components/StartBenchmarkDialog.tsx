"use client";

import React from "react";

import { usePlainChatModelGroups } from "@/app/(dashboard)/hooks/models/useModels";
import { useStartQosBenchmark } from "@/app/(dashboard)/hooks/qos/useQosBenchmarks";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import { checkBenchmarkPlan, type QosBenchmarkStarted } from "./qosData";

interface StartBenchmarkDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly accessToken: string | null;
  readonly initialModel: string;
  readonly onStarted: (started: QosBenchmarkStarted) => void;
}

const Field = ({ id, label, children }: { id: string; label: string; children: React.ReactNode }) => (
  <div className="flex flex-col gap-1.5">
    <label htmlFor={id} className="text-sm font-medium">
      {label}
    </label>
    {children}
  </div>
);

export default function StartBenchmarkDialog({
  open,
  onOpenChange,
  accessToken,
  initialModel,
  onStarted,
}: StartBenchmarkDialogProps) {
  const modelGroups = usePlainChatModelGroups();
  const models = React.useMemo(() => [...modelGroups].sort(), [modelGroups]);
  const [model, setModel] = React.useState(initialModel);
  const [concurrency, setConcurrency] = React.useState("1, 4, 16");
  const [requestsPerWorker, setRequestsPerWorker] = React.useState("8");
  const [maxTokens, setMaxTokens] = React.useState("512");
  const start = useStartQosBenchmark(accessToken);
  const formInput = { model, concurrency, requestsPerWorker, maxTokens };
  const check = checkBenchmarkPlan(formInput);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!check.ok) return;
    start.mutate(check.plan, { onSuccess: onStarted });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Test service quality</DialogTitle>
            <DialogDescription>
              The gateway sends streamed requests to the model at each concurrency level in turn and records TTFT,
              TPOT, latency and success rate per node.
            </DialogDescription>
          </DialogHeader>

          <Field id="qos-benchmark-model" label="Model">
            <Select items={models.map((name) => ({ value: name, label: name }))} value={model} onValueChange={(value: string | null) => setModel(value === null ? "" : value)}>
              <SelectTrigger id="qos-benchmark-model" className="w-full">
                <SelectValue placeholder="Choose a model" />
              </SelectTrigger>
              <SelectContent>
                {models.map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field id="qos-benchmark-concurrency" label="Concurrency levels">
            <Input
              id="qos-benchmark-concurrency"
              value={concurrency}
              placeholder="e.g. 1, 4, 16, 32"
              onChange={(event) => setConcurrency(event.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field id="qos-benchmark-per-worker" label="Requests per worker">
              <Input
                id="qos-benchmark-per-worker"
                inputMode="numeric"
                value={requestsPerWorker}
                onChange={(event) => setRequestsPerWorker(event.target.value)}
              />
            </Field>
            <Field id="qos-benchmark-max-tokens" label="Max output tokens">
              <Input
                id="qos-benchmark-max-tokens"
                inputMode="numeric"
                value={maxTokens}
                onChange={(event) => setMaxTokens(event.target.value)}
              />
            </Field>
          </div>

          <p className={`text-sm ${check.ok ? "text-muted-foreground" : "text-destructive"}`} role="status">
            {check.ok ? `Sends ${check.total} streamed requests through the gateway` : check.message}
          </p>
          {start.error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{extractErrorMessage(start.error)}</AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!check.ok || start.isPending}>
              Start test
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
