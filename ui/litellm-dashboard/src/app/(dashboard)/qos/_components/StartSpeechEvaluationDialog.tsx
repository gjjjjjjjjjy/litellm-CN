"use client";

import React from "react";

import {
  useSpeechEvaluationOptions,
  useStartSpeechEvaluation,
} from "@/app/(dashboard)/hooks/qos/useQosSpeechEvaluations";
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
import { extractErrorMessage } from "@/utils/errorUtils";
import { MediaEvaluationSetupHint } from "./MediaEvaluationSetupHint";
import { AUDIO_MODALITY_LABELS, type QosSpeechEvaluationStarted } from "./qosData";

interface StartSpeechEvaluationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accessToken: string | null;
  onStarted: (started: QosSpeechEvaluationStarted) => void;
}

export default function StartSpeechEvaluationDialog({
  open,
  onOpenChange,
  accessToken,
  onStarted,
}: StartSpeechEvaluationDialogProps) {
  const options = useSpeechEvaluationOptions(accessToken, open);
  const start = useStartSpeechEvaluation(accessToken);
  const data = options.data;
  const canStart = data?.available === true && data.models.length > 0 && !start.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Start a speech evaluation</DialogTitle>
          <DialogDescription>
            Every speech synthesis model the probe covers reads the test sentence, and every transcription model
            transcribes the same recording of it. Results appear on this page within a few minutes.
          </DialogDescription>
        </DialogHeader>

        {data !== undefined && data.models.length > 0 && (
          <ul aria-label="Models in this evaluation" className="flex flex-wrap gap-2">
            {data.models.map((model) => (
              <li key={model.model_group}>
                <Badge variant="outline">
                  {model.model_group} · {AUDIO_MODALITY_LABELS[model.modality]}
                </Badge>
              </li>
            ))}
          </ul>
        )}
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
          <Button disabled={!canStart} onClick={() => start.mutate(undefined, { onSuccess: onStarted })}>
            {start.isPending ? "Starting…" : "Start evaluation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
