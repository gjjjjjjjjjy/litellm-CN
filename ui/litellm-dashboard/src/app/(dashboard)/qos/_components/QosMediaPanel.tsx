"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleHelp, RefreshCw } from "lucide-react";

import { useQosMedia } from "@/app/(dashboard)/hooks/qos/useQosMedia";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import {
  AUDIO_MODALITY_LABELS,
  formatAudioLength,
  formatFactorPercentiles,
  formatPercentiles,
  formatPrice,
  formatRatio,
  isQosRange,
  QOS_RANGES,
  successRate,
  videosWithoutResult,
  type QosAudioMetrics,
  type QosRange,
  type QosVideoMetrics,
} from "./qosData";

const audioColumns: ColumnDef<QosAudioMetrics>[] = [
  {
    id: "model_group",
    header: "Model",
    cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span>,
  },
  { id: "modality", header: "Type", cell: ({ row }) => AUDIO_MODALITY_LABELS[row.original.modality] },
  { id: "requests", header: "Requests", cell: ({ row }) => row.original.requests },
  { id: "success_rate", header: "Success rate", cell: ({ row }) => formatRatio(successRate(row.original)) },
  { id: "audio_seconds", header: "Audio length", cell: ({ row }) => formatAudioLength(row.original.audio_seconds) },
  {
    id: "input_chars",
    header: "Spoken characters",
    cell: ({ row }) => (row.original.modality === "speech" ? row.original.input_chars : "-"),
  },
  { id: "latency", header: "Latency P50 / P95", cell: ({ row }) => formatPercentiles(row.original.latency_ms) },
  {
    id: "real_time_factor",
    header: "Real-time factor P50 / P95",
    cell: ({ row }) => formatFactorPercentiles(row.original.real_time_factor),
  },
];

const videoColumns: ColumnDef<QosVideoMetrics>[] = [
  {
    id: "model_group",
    header: "Model",
    cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span>,
  },
  { id: "submitted", header: "Submitted", cell: ({ row }) => row.original.submitted },
  { id: "failed_submissions", header: "Failed submissions", cell: ({ row }) => row.original.failed_submissions },
  { id: "succeeded", header: "Succeeded", cell: ({ row }) => row.original.succeeded },
  { id: "failed", header: "Failed", cell: ({ row }) => row.original.failed },
  { id: "cancelled", header: "Cancelled", cell: ({ row }) => row.original.cancelled },
  { id: "without_result", header: "No result yet", cell: ({ row }) => videosWithoutResult(row.original) },
  { id: "queue", header: "Queue time P50 / P95", cell: ({ row }) => formatPercentiles(row.original.queue_ms) },
  { id: "run", header: "Generation time P50 / P95", cell: ({ row }) => formatPercentiles(row.original.run_ms) },
  { id: "task_price", header: "Provider price", cell: ({ row }) => formatPrice(row.original.task_price) },
];

interface MetricDefinition {
  readonly label: string;
  readonly description: string;
}

const AUDIO_DEFINITIONS: readonly MetricDefinition[] = [
  {
    label: "Requests",
    description: "Speech synthesis or transcription requests that started in the time range, failed ones included.",
  },
  { label: "Success rate", description: "Requests that did not fail, divided by all requests." },
  {
    label: "Audio length",
    description:
      "Total audio of the successful requests. Speech synthesis reads it from the header of the returned WAV or MP3 file; transcription uses the length of the uploaded audio.",
  },
  {
    label: "Spoken characters",
    description:
      "Characters of the input text without punctuation, spaces or control characters, summed over successful speech synthesis requests.",
  },
  { label: "Latency", description: "End time minus start time of each successful request." },
  {
    label: "Real-time factor",
    description:
      "Latency divided by the audio length of each successful request. Below 1 is faster than real time: 0.2 means 10 seconds of audio took 2 seconds.",
  },
];

const VIDEO_DEFINITIONS: readonly MetricDefinition[] = [
  {
    label: "Submitted",
    description: "Video generation requests that started in the time range, each creating at most one provider task.",
  },
  {
    label: "Failed submissions",
    description: "Submissions the gateway or the provider rejected, so no task was created.",
  },
  {
    label: "Succeeded, failed, cancelled",
    description:
      "How each task ended, as seen by a status check up to one day after the time range. A task counts once however often its status was checked.",
  },
  {
    label: "No result yet",
    description:
      "Submitted tasks whose end no status check has seen: still running, or nobody checked after they finished.",
  },
  { label: "Queue time", description: "From the provider creating the task to starting it, per its task record." },
  {
    label: "Generation time",
    description: "From the provider starting the task to finishing it, succeeded tasks only.",
  },
  {
    label: "Provider price",
    description: "Sum of the prices in the provider's task records, in the provider's currency.",
  },
];

function MetricHelp({ title, definitions }: { title: string; definitions: readonly MetricDefinition[] }) {
  return (
    <Popover>
      <PopoverTrigger aria-label={title} className="text-muted-foreground hover:text-foreground">
        <CircleHelp className="size-4" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 gap-3 p-3">
        <PopoverTitle>{title}</PopoverTitle>
        <p className="text-muted-foreground">
          P50 is the median and P95 the value 95% stay at or below, over the selected time range.
        </p>
        <dl className="flex flex-col gap-2">
          {definitions.map((definition) => (
            <div key={definition.label}>
              <dt className="font-medium">{definition.label}</dt>
              <dd className="text-muted-foreground">{definition.description}</dd>
            </div>
          ))}
        </dl>
      </PopoverContent>
    </Popover>
  );
}

export default function QosMediaPanel({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("24h");
  const mediaQuery = useQosMedia(accessToken, range, false);
  const media = mediaQuery.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-media-range" className="text-sm text-muted-foreground">
            Time range
          </label>
          <Select
            items={QOS_RANGES}
            value={range}
            onValueChange={(value: string | null) => {
              if (value !== null && isQosRange(value)) setRange(value);
            }}
          >
            <SelectTrigger id="qos-media-range" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {QOS_RANGES.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button variant="outline" disabled={mediaQuery.isFetching} onClick={() => void mediaQuery.refetch()}>
          <RefreshCw className={`size-4 ${mediaQuery.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {mediaQuery.error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load audio and video metrics</AlertTitle>
          <AlertDescription>{extractErrorMessage(mediaQuery.error)}</AlertDescription>
        </Alert>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-1.5">
          <h3 className="text-base font-semibold">Speech synthesis and transcription</h3>
          <MetricHelp title="How speech synthesis and transcription are measured" definitions={AUDIO_DEFINITIONS} />
        </div>
        <DataTable
          data={media === undefined ? [] : [...media.audio]}
          columns={audioColumns}
          getRowId={(metrics) => `${metrics.model_group}:${metrics.modality}`}
          isLoading={mediaQuery.isLoading}
          noDataMessage="No speech synthesis or transcription requests in this time range"
        />
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-1.5">
          <h3 className="text-base font-semibold">Video generation</h3>
          <MetricHelp title="How video generation is measured" definitions={VIDEO_DEFINITIONS} />
        </div>
        <DataTable
          data={media === undefined ? [] : [...media.video]}
          columns={videoColumns}
          getRowId={(metrics) => metrics.model_group}
          isLoading={mediaQuery.isLoading}
          noDataMessage="No video tasks in this time range"
        />
      </section>
    </div>
  );
}
