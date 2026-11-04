"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Play, RefreshCw, Sparkles } from "lucide-react";

import {
  fetchSpeechAudio,
  fetchSpeechRecording,
  useQosSpeechEvaluations,
  useSaveSpeechReview,
} from "@/app/(dashboard)/hooks/qos/useQosSpeechEvaluations";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import ProbeRuns, { formatRunTime } from "./ProbeRuns";
import {
  characterErrors,
  formatFactor,
  formatMs,
  formatRatio,
  formatScore,
  isQosRange,
  probeRuns,
  QOS_RANGES,
  realTimeFactor,
  speechRunSummary,
  type ProbeRun,
  type QosRange,
  type QosSpeechEvaluationStarted,
  type QosSpeechResult,
  type TranscriptMark,
} from "./qosData";
import StartSpeechEvaluationDialog from "./StartSpeechEvaluationDialog";

const SCORES = [1, 2, 3, 4, 5] as const;

function AudioPlayer({ label, load }: { label: string; load: () => Promise<Blob> }) {
  const [url, setUrl] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );

  const play = async () => {
    setLoading(true);
    setError(null);
    try {
      setUrl(URL.createObjectURL(await load()));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  if (url !== null) return <audio controls autoPlay src={url} aria-label={label} className="h-8 w-56" />;
  return (
    <div className="flex flex-col gap-1">
      <Button variant="outline" size="sm" className="w-fit" disabled={loading} onClick={() => void play()}>
        <Play className="size-4" />
        Play
      </Button>
      {error !== null && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function ReadingRating({ accessToken, result }: { accessToken: string | null; result: QosSpeechResult }) {
  const save = useSaveSpeechReview(accessToken);
  const [score, setScore] = React.useState(result.my_review?.overall);

  return (
    <div className="flex flex-col gap-1">
      <div role="radiogroup" aria-label="Your rating" className="flex gap-1">
        {SCORES.map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            role="radio"
            aria-checked={score === value}
            variant={score === value ? "default" : "outline"}
            className="size-7 p-0"
            disabled={save.isPending}
            onClick={() => {
              setScore(value);
              save.mutate({ requestId: result.request_id, overall: value });
            }}
          >
            {value}
          </Button>
        ))}
      </div>
      {save.error !== null && <span className="text-xs text-destructive">{extractErrorMessage(save.error)}</span>}
    </div>
  );
}

function Failure({ error }: { error: string | null }) {
  return (
    <span title={error ?? undefined} className="line-clamp-2 max-w-md text-sm text-destructive">
      Failed: {error ?? "no reason was logged"}
    </span>
  );
}

const modelColumn: ColumnDef<QosSpeechResult> = {
  id: "model_group",
  header: "Model",
  cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span>,
};

const latencyColumn: ColumnDef<QosSpeechResult> = {
  id: "latency",
  header: "Latency",
  cell: ({ row }) => (row.original.succeeded ? formatMs(row.original.latency_ms) : "-"),
};

const readingColumns = (accessToken: string | null): ColumnDef<QosSpeechResult>[] => [
  modelColumn,
  {
    id: "audio",
    header: "Audio",
    cell: ({ row }) =>
      row.original.succeeded ? (
        <AudioPlayer
          label={`Audio from ${row.original.model_group}`}
          load={() => fetchSpeechAudio(accessToken, row.original.request_id)}
        />
      ) : (
        <Failure error={row.original.error} />
      ),
  },
  latencyColumn,
  { id: "real_time_factor", header: "Real-time factor", cell: ({ row }) => formatFactor(realTimeFactor(row.original)) },
  {
    id: "rating",
    header: "Your rating (saved when clicked)",
    cell: ({ row }) =>
      row.original.succeeded ? <ReadingRating accessToken={accessToken} result={row.original} /> : "-",
  },
  {
    id: "average",
    header: "Average",
    cell: ({ row }) =>
      row.original.reviews === 0 ? (
        "-"
      ) : (
        <span>
          {formatScore(row.original.overall)} ({row.original.reviews} ratings)
        </span>
      ),
  },
];

function Transcript({ marks }: { marks: readonly TranscriptMark[] }) {
  return (
    <span className="text-sm">
      {marks.map((mark, index) => {
        if (mark.kind === "wrong") {
          return (
            <mark key={index} className="bg-transparent font-semibold text-destructive">
              {mark.char}
            </mark>
          );
        }
        if (mark.kind === "missing") {
          return (
            <del key={index} className="text-destructive opacity-70">
              {mark.char}
            </del>
          );
        }
        return <React.Fragment key={index}>{mark.char}</React.Fragment>;
      })}
    </span>
  );
}

const transcriptionColumns: ColumnDef<QosSpeechResult>[] = [
  modelColumn,
  {
    id: "error_rate",
    header: "Character error rate",
    cell: ({ row }) => {
      const transcript = row.original.transcript;
      const errors = transcript === null ? null : characterErrors(row.original.text, transcript);
      return formatRatio(errors?.rate ?? null);
    },
  },
  latencyColumn,
  {
    id: "transcript",
    header: "Transcript",
    cell: ({ row }) => {
      const { succeeded, error, text, transcript } = row.original;
      if (!succeeded) return <Failure error={error} />;
      if (transcript === null) {
        return <span className="text-sm text-muted-foreground">Waiting for the probe to report the transcript</span>;
      }
      const errors = characterErrors(text, transcript);
      return errors === null ? transcript : <Transcript marks={errors.marks} />;
    },
  },
];

function SpeechRunMeta({ run }: { run: ProbeRun<QosSpeechResult> }) {
  const summary = speechRunSummary(run.items);
  return (
    <span>
      {summary.readings} speech synthesis · {summary.transcriptions} transcription · rated {summary.rated}/
      {summary.rateable} · average character error rate {formatRatio(summary.errorRate)}
    </span>
  );
}

function SpeechRun({ accessToken, run }: { accessToken: string | null; run: ProbeRun<QosSpeechResult> }) {
  const readings = run.items.filter((result) => result.modality === "speech");
  const transcriptions = run.items.filter((result) => result.modality === "transcription");
  const sentence = run.items[0]?.text ?? "";
  const columns = React.useMemo(() => readingColumns(accessToken), [accessToken]);

  return (
    <div className="flex flex-col gap-6">
      {readings.length > 0 && (
        <section aria-label="Speech synthesis" className="flex flex-col gap-2">
          <p className="text-sm">
            <span className="font-medium">Speech synthesis</span>{" "}
            <span className="text-muted-foreground">Test sentence: {sentence}</span>
          </p>
          <DataTable
            data={readings}
            columns={columns}
            getRowId={(result) => result.request_id}
            noDataMessage="No speech synthesis in this run"
          />
        </section>
      )}
      {transcriptions.length > 0 && (
        <section aria-label="Transcription" className="flex flex-col gap-2">
          <p className="text-sm">
            <span className="font-medium">Transcription</span>{" "}
            <span className="text-muted-foreground">
              Every model transcribes the same fixed recording; red characters are the ones it got wrong or missed
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span>Original: {sentence}</span>
            <AudioPlayer label="Recording" load={() => fetchSpeechRecording(accessToken)} />
          </div>
          <DataTable
            data={transcriptions}
            columns={transcriptionColumns}
            getRowId={(result) => result.request_id}
            noDataMessage="No transcription in this run"
          />
        </section>
      )}
    </div>
  );
}

export default function QosSpeechEvaluationPanel({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("7d");
  const [evaluating, setEvaluating] = React.useState(false);
  const [started, setStarted] = React.useState<{
    readonly run: QosSpeechEvaluationStarted;
    readonly at: number;
  } | null>(null);
  const evaluationsQuery = useQosSpeechEvaluations(accessToken, range, started?.at ?? null);
  const runs = probeRuns(evaluationsQuery.data?.results ?? [], (result) => result.run);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-speech-range" className="text-sm text-muted-foreground">
            Time range
          </label>
          <Select
            items={QOS_RANGES}
            value={range}
            onValueChange={(value: string | null) => {
              if (value !== null && isQosRange(value)) setRange(value);
            }}
          >
            <SelectTrigger id="qos-speech-range" className="w-44">
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
        <Button
          variant="outline"
          disabled={evaluationsQuery.isFetching}
          onClick={() => void evaluationsQuery.refetch()}
        >
          <RefreshCw className={`size-4 ${evaluationsQuery.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        <Button onClick={() => setEvaluating(true)}>
          <Sparkles className="size-4" />
          Start evaluation
        </Button>
      </div>

      {started !== null && (
        <Alert>
          <AlertTitle>Evaluation started</AlertTitle>
          <AlertDescription>
            {started.run.models.join(", ")} are being tested. Their results appear below within a few minutes, and this
            list refreshes every 10 seconds meanwhile.
          </AlertDescription>
        </Alert>
      )}

      {evaluationsQuery.error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load speech evaluations</AlertTitle>
          <AlertDescription>{extractErrorMessage(evaluationsQuery.error)}</AlertDescription>
        </Alert>
      )}

      <ProbeRuns
        id="speech"
        runs={runs}
        schedule={
          <span>
            Runs every day at the probe&apos;s scheduled times, together with the video evaluation, with the same
            sentence and recording as runs started by hand.
          </span>
        }
        title={(run) => formatRunTime(run.startedAt)}
        meta={(run) => <SpeechRunMeta run={run} />}
      >
        {(run) => <SpeechRun accessToken={accessToken} run={run} />}
      </ProbeRuns>

      {evaluating && (
        <StartSpeechEvaluationDialog
          open
          onOpenChange={(open) => {
            if (!open) setEvaluating(false);
          }}
          accessToken={accessToken}
          onStarted={(run) => {
            setStarted({ run, at: Date.now() });
            setEvaluating(false);
          }}
        />
      )}
    </div>
  );
}
