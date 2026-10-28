"use client";

import React from "react";

import { usePlainChatModelGroups } from "@/app/(dashboard)/hooks/models/useModels";
import { useQosTargets, useStartQosBenchmark } from "@/app/(dashboard)/hooks/qos/useQosBenchmarks";
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
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import {
  checkBenchmarkPlan,
  deploymentIdsFor,
  parseTargetChoice,
  providerLabel,
  targetChoiceValue,
  type QosBenchmarkStarted,
  type QosTargetDeployment,
  type TargetChoice,
  vendorName,
} from "./qosData";

interface StartBenchmarkDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly accessToken: string | null;
  readonly initialModel: string;
  readonly onStarted: (started: QosBenchmarkStarted) => void;
}

const BALANCED: TargetChoice = { kind: "balanced" };
const NO_DEPLOYMENTS: readonly QosTargetDeployment[] = [];

const providerSummary = (deployments: readonly QosTargetDeployment[]): string =>
  [...new Set(deployments.map((deployment) => vendorName(deployment.vendor)))].join(", ");

const targetOptions = (deployments: readonly QosTargetDeployment[]): { value: string; label: string }[] => [
  { value: targetChoiceValue(BALANCED), label: "All providers, load-balanced" },
  ...deployments.map((deployment) => ({
    value: targetChoiceValue({ kind: "deployment", modelId: deployment.model_id }),
    label: providerLabel(deployment),
  })),
  ...(deployments.length > 1
    ? [{ value: targetChoiceValue({ kind: "compare" }), label: `Compare all ${deployments.length} providers` }]
    : []),
];

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
  const targets = useQosTargets(accessToken);
  const deploymentsByModel = React.useMemo(
    () => new Map((targets.data ?? []).map((target) => [target.model_group, target.deployments])),
    [targets.data],
  );
  const [model, setModel] = React.useState(initialModel);
  const [target, setTarget] = React.useState<TargetChoice>(BALANCED);
  const deployments = deploymentsByModel.get(model) ?? NO_DEPLOYMENTS;
  const options = targetOptions(deployments);
  const [concurrency, setConcurrency] = React.useState("1, 4, 16");
  const [requestsPerWorker, setRequestsPerWorker] = React.useState("8");
  const [maxTokens, setMaxTokens] = React.useState("512");
  const [saveResponses, setSaveResponses] = React.useState(true);
  const start = useStartQosBenchmark(accessToken);
  const deploymentIds = deploymentIdsFor(target, deployments);
  const formInput = { model, deploymentIds, concurrency, requestsPerWorker, maxTokens, saveResponses };
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
              The gateway sends streamed requests to the model at each concurrency level in turn and records TTFT, TPOT,
              latency and success rate per node.
            </DialogDescription>
          </DialogHeader>

          <Field id="qos-benchmark-model" label="Model">
            <Select
              items={models.map((name) => ({ value: name, label: name }))}
              value={model}
              onValueChange={(value: string | null) => {
                setModel(value === null ? "" : value);
                setTarget(BALANCED);
              }}
            >
              <SelectTrigger id="qos-benchmark-model" className="w-full">
                <SelectValue placeholder="Choose a model" />
              </SelectTrigger>
              <SelectContent>
                {models.map((name) => (
                  <SelectItem key={name} value={name}>
                    <span>{name}</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {providerSummary(deploymentsByModel.get(name) ?? NO_DEPLOYMENTS)}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {deployments.length > 0 && (
            <Field id="qos-benchmark-provider" label="Provider">
              <Select
                items={options}
                value={targetChoiceValue(target)}
                onValueChange={(value: string | null) =>
                  setTarget(value === null ? BALANCED : parseTargetChoice(value))
                }
              >
                <SelectTrigger id="qos-benchmark-provider" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
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

          <label htmlFor="qos-save-responses" className="flex items-center gap-2 text-sm">
            <Switch id="qos-save-responses" checked={saveResponses} onCheckedChange={setSaveResponses} />
            Save questions and answers for this test
          </label>
          <p className="text-xs text-muted-foreground">Saved text is available to proxy admins in the test details.</p>
          <p className={`text-sm ${check.ok ? "text-muted-foreground" : "text-destructive"}`} role="status">
            {!check.ok && check.message}
            {check.ok && target.kind !== "compare" && `Sends ${check.total} streamed requests through the gateway`}
            {check.ok &&
              target.kind === "compare" &&
              `Sends ${check.total} streamed requests, testing ${deploymentIds.length} providers one after another with the same plan`}
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
