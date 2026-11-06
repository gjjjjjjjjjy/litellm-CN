"use client";

import React from "react";
import { Sparkles } from "lucide-react";

import {
  useStartVideoEvaluation,
  useVideoEvaluationOptions,
  useWriteEvaluationPrompt,
} from "@/app/(dashboard)/hooks/qos/useQosVideoReviews";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { extractErrorMessage } from "@/utils/errorUtils";
import { MediaEvaluationSetupHint } from "./MediaEvaluationSetupHint";
import { evaluationCost, formatPrice, type QosVideoEvaluationOptions, type QosVideoEvaluationStarted } from "./qosData";

const PROMPT_SOURCES = ["new", "used", "custom"] as const;
type PromptSource = (typeof PROMPT_SOURCES)[number];
const isPromptSource = (value: unknown): value is PromptSource => PROMPT_SOURCES.some((source) => source === value);

function NewPromptWriter({
  accessToken,
  disabled,
  onWritten,
}: {
  accessToken: string | null;
  disabled: boolean;
  onWritten: (prompt: string) => void;
}) {
  const write = useWriteEvaluationPrompt(accessToken);
  return (
    <div className="flex flex-col gap-1.5">
      <Button
        type="button"
        variant="outline"
        className="w-fit"
        disabled={disabled || write.isPending}
        onClick={() => write.mutate(undefined, { onSuccess: (written) => onWritten(written.prompt) })}
      >
        <Sparkles className="size-4" />
        {write.isPending ? "Writing a prompt…" : "Write a prompt that tests every rating"}
      </Button>
      {write.error !== null && <p className="text-xs text-destructive">{extractErrorMessage(write.error)}</p>}
    </div>
  );
}

function EarlierPromptPicker({
  prompts,
  prompt,
  onPick,
}: {
  prompts: QosVideoEvaluationOptions["prompts"];
  prompt: string;
  onPick: (prompt: string) => void;
}) {
  return (
    <Select
      items={prompts.map((used) => ({ value: used.prompt, label: used.prompt }))}
      value={prompts.some((used) => used.prompt === prompt) ? prompt : null}
      onValueChange={(value: string | null) => {
        if (value !== null) onPick(value);
      }}
    >
      <SelectTrigger aria-label="Earlier prompts" className="w-full">
        <SelectValue placeholder={prompts.length === 0 ? "No earlier prompts" : "Choose an earlier prompt"} />
      </SelectTrigger>
      <SelectContent>
        {prompts.map((used) => (
          <SelectItem key={used.prompt} value={used.prompt}>
            <span className="line-clamp-2 whitespace-normal">{used.prompt}</span>
            <span className="ml-2 shrink-0 text-xs text-muted-foreground">{used.videos} videos</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function EvaluationModels({ options }: { options: QosVideoEvaluationOptions }) {
  const cost = evaluationCost(options.models);
  return (
    <section aria-label="Models in this evaluation" className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-2">
        {options.models.map((model) => (
          <li key={model.model_group}>
            <Badge variant="outline">
              {model.model_group} · {model.image_to_video ? "image to video" : "text to video"}
              {model.last_price !== null && ` · ${formatPrice(model.last_price)} ${model.currency ?? ""}`}
            </Badge>
          </li>
        ))}
      </ul>
      {options.models.some((model) => model.image_to_video) && (
        <p className="text-xs text-muted-foreground">
          Image-to-video models start from the first frame of the text-to-video video, unless the prompt is the
          scheduled probe&apos;s, so they begin a few minutes later.
        </p>
      )}
      {cost !== null && (
        <p className="text-sm" role="status">
          Estimated cost: about {formatPrice(cost.total)} {cost.currency}, from each model&apos;s latest video
          {cost.unpriced.length > 0 && `; no recent price for ${cost.unpriced.join(", ")}`}
        </p>
      )}
    </section>
  );
}

interface StartVideoEvaluationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accessToken: string | null;
  onStarted: (started: QosVideoEvaluationStarted) => void;
}

export default function StartVideoEvaluationDialog({
  open,
  onOpenChange,
  accessToken,
  onStarted,
}: StartVideoEvaluationDialogProps) {
  const options = useVideoEvaluationOptions(accessToken, open);
  const start = useStartVideoEvaluation(accessToken);
  const [source, setSource] = React.useState<PromptSource>("new");
  const [prompt, setPrompt] = React.useState("");
  const data = options.data;
  const probeReady = data?.available === true && data.models.length > 0;
  const canStart = probeReady && prompt.trim() !== "" && !start.isPending;

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canStart) start.mutate(prompt.trim(), { onSuccess: onStarted });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Start an evaluation</DialogTitle>
            <DialogDescription>
              Every video model the probe covers generates the prompt now, and a vision model rates each video from one
              still per second as soon as it finishes. Results appear on this page as they come in.
            </DialogDescription>
          </DialogHeader>

          <RadioGroup
            aria-label="Where the prompt comes from"
            value={source}
            onValueChange={(value: unknown) => {
              if (isPromptSource(value)) setSource(value);
            }}
            className="flex flex-wrap gap-4"
          >
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="new" />
              New prompt
            </label>
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="used" />
              Earlier prompt
            </label>
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="custom" />
              My own prompt
            </label>
          </RadioGroup>

          {source === "new" && (
            <NewPromptWriter accessToken={accessToken} disabled={data?.available !== true} onWritten={setPrompt} />
          )}
          {source === "used" && (
            <EarlierPromptPicker prompts={data?.prompts ?? []} prompt={prompt} onPick={setPrompt} />
          )}

          <Textarea
            aria-label="Prompt"
            placeholder="The prompt every model gets"
            maxLength={500}
            rows={4}
            value={prompt}
            onChange={(event) => {
              setPrompt(event.target.value);
              setSource("custom");
            }}
          />

          {data !== undefined && data.models.length > 0 && <EvaluationModels options={data} />}
          {data?.available === true && data.models.length === 0 && <MediaEvaluationSetupHint />}

          {data?.available === false && (
            <Alert variant="destructive">
              <AlertDescription>
                No media probe is set up, so an evaluation cannot start. Set QOS_MEDIA_PROBE_URL on the gateway.
              </AlertDescription>
            </Alert>
          )}
          {options.error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{extractErrorMessage(options.error)}</AlertDescription>
            </Alert>
          )}
          {start.error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{extractErrorMessage(start.error)}</AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canStart}>
              {start.isPending ? "Starting…" : "Start evaluation"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
