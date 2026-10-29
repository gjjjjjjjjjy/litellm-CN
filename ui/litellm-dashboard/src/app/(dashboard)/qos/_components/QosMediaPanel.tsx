"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";

import { useQosMedia } from "@/app/(dashboard)/hooks/qos/useQosMedia";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
        <h3 className="text-base font-semibold">Speech synthesis and transcription</h3>
        <p className="text-sm text-muted-foreground">
          Latency of successful requests and its ratio to the audio length, the real-time factor; below 1 is faster than
          real time. Audio length is read from the returned audio for speech synthesis and from the uploaded audio for
          transcription.
        </p>
        <DataTable
          data={media === undefined ? [] : [...media.audio]}
          columns={audioColumns}
          getRowId={(metrics) => `${metrics.model_group}:${metrics.modality}`}
          isLoading={mediaQuery.isLoading}
          noDataMessage="No speech synthesis or transcription requests in this time range"
        />
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-base font-semibold">Video generation</h3>
        <p className="text-sm text-muted-foreground">
          Counted once per task, however often its status was checked. Queue time runs from the provider creating the
          task to starting it and generation time from starting to finishing, for succeeded tasks only. A task has no
          result yet until a status check sees it end. The provider price is the total its task records report.
        </p>
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
