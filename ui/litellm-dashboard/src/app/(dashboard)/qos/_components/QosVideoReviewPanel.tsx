"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Play, RefreshCw, Sparkles } from "lucide-react";

import {
  fetchVideoContent,
  useQosVideoReviews,
  useSaveVideoReview,
} from "@/app/(dashboard)/hooks/qos/useQosVideoReviews";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { extractErrorMessage } from "@/utils/errorUtils";
import {
  AI_DIMENSIONS,
  formatScore,
  isQosRange,
  QOS_RANGES,
  REVIEW_DIMENSION_LABELS,
  REVIEW_DIMENSIONS,
  reviewInput,
  reviewScores,
  type AiDimension,
  type PromptVideos,
  type QosRange,
  type QosReviewVideo,
  type QosVideoAiReview,
  type QosVideoAiSummary,
  type QosVideoEvaluationStarted,
  type QosVideoReviewSummary,
  type ReviewDimension,
  type ReviewScores,
  videosByPrompt,
} from "./qosData";
import StartVideoEvaluationDialog from "./StartVideoEvaluationDialog";

const SCORES = [1, 2, 3, 4, 5] as const;

const dimensionColumn = (dimension: ReviewDimension): ColumnDef<QosVideoReviewSummary> => ({
  id: dimension,
  header: REVIEW_DIMENSION_LABELS[dimension],
  cell: ({ row }) => formatScore(row.original[dimension]),
});

const summaryColumns: ColumnDef<QosVideoReviewSummary>[] = [
  {
    id: "model_group",
    header: "Model",
    cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span>,
  },
  { id: "videos", header: "Videos rated", cell: ({ row }) => row.original.videos },
  { id: "reviews", header: "Ratings", cell: ({ row }) => row.original.reviews },
  ...REVIEW_DIMENSIONS.map(dimensionColumn),
];

const aiDimensionColumn = (dimension: AiDimension): ColumnDef<QosVideoAiSummary> => ({
  id: dimension,
  header: REVIEW_DIMENSION_LABELS[dimension],
  cell: ({ row }) => formatScore(row.original[dimension]),
});

const aiSummaryColumns: ColumnDef<QosVideoAiSummary>[] = [
  {
    id: "model_group",
    header: "Model",
    cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span>,
  },
  { id: "videos", header: "Videos rated", cell: ({ row }) => row.original.videos },
  ...AI_DIMENSIONS.map(aiDimensionColumn),
];

function ScoreButtons({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | undefined;
  onChange: (score: number | undefined) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex gap-1">
        {SCORES.map((score) => (
          <Button
            key={score}
            type="button"
            size="sm"
            role="radio"
            aria-checked={value === score}
            variant={value === score ? "default" : "outline"}
            className="size-8 p-0"
            onClick={() => onChange(value === score ? undefined : score)}
          >
            {score}
          </Button>
        ))}
      </div>
    </div>
  );
}

function VideoPlayer({ accessToken, videoId }: { accessToken: string | null; videoId: string }) {
  const [url, setUrl] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setUrl(URL.createObjectURL(await fetchVideoContent(accessToken, videoId)));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  if (url !== null) {
    return <video controls src={url} aria-label="Generated video" className="max-h-72 w-full rounded-md bg-black" />;
  }
  return (
    <div className="flex flex-col gap-1">
      <Button variant="outline" size="sm" className="w-fit" disabled={loading} onClick={() => void load()}>
        <Play className="size-4" />
        Play video
      </Button>
      {error !== null && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function AiReview({ review }: { review: QosVideoAiReview }) {
  const labelId = React.useId();
  const reasons = AI_DIMENSIONS.flatMap((dimension) => {
    const reason = dimension === "overall" ? "" : review.reasons[dimension] ?? "";
    return reason === "" ? [] : [{ dimension, reason }];
  });
  const unmet = review.checklist.filter((check) => !check.met);

  return (
    <section aria-labelledby={labelId} className="flex flex-col gap-2 rounded-md border p-3">
      <p id={labelId} className="text-sm font-medium">
        AI rating
      </p>
      <p className="text-xs text-muted-foreground">
        {review.judge} rated {review.frames} stills, one per second, without the sound
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
        {AI_DIMENSIONS.map((dimension) => (
          <div key={dimension} className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{REVIEW_DIMENSION_LABELS[dimension]}</dt>
            <dd className="font-medium">{review[dimension]}</dd>
          </div>
        ))}
      </dl>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Why it gave these ratings</summary>
        <div className="mt-2 flex flex-col gap-1">
          {reasons.map(({ dimension, reason }) => (
            <p key={dimension}>
              <span className="text-muted-foreground">{REVIEW_DIMENSION_LABELS[dimension]}: </span>
              {reason}
            </p>
          ))}
          {unmet.map((check) => (
            <p key={check.requirement}>
              <span className="text-destructive">Not met: </span>
              {check.requirement}
              {check.evidence !== "" && ` (${check.evidence})`}
            </p>
          ))}
          {review.problems.map((problem) => (
            <p key={`${problem.second}-${problem.problem}`}>
              <span className="text-muted-foreground">At second {problem.second}: </span>
              {problem.problem}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}

function VideoReviewForm({ accessToken, video }: { accessToken: string | null; video: QosReviewVideo }) {
  const [scores, setScores] = React.useState<ReviewScores>(() => reviewScores(video.my_review));
  const [comment, setComment] = React.useState(() => video.my_review?.comment ?? "");
  const save = useSaveVideoReview(accessToken);
  const input = reviewInput(scores, comment);

  return (
    <>
      <div className="flex flex-col gap-2">
        {REVIEW_DIMENSIONS.map((dimension) => (
          <ScoreButtons
            key={dimension}
            label={REVIEW_DIMENSION_LABELS[dimension]}
            value={scores[dimension]}
            onChange={(score) => setScores((current) => ({ ...current, [dimension]: score }))}
          />
        ))}
      </div>
      <Textarea
        aria-label="Comment"
        placeholder="What stood out, good or bad"
        maxLength={500}
        value={comment}
        onChange={(event) => setComment(event.target.value)}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={input === null || save.isPending}
          onClick={() => {
            if (input !== null) save.mutate({ videoId: video.video_id, review: input });
          }}
        >
          Save rating
        </Button>
        {input === null && <span className="text-xs text-muted-foreground">Rate Overall to save</span>}
        {save.isSuccess && <span className="text-xs text-muted-foreground">Saved</span>}
        {save.error !== null && <span className="text-xs text-destructive">{extractErrorMessage(save.error)}</span>}
      </div>
    </>
  );
}

function VideoReviewCard({ accessToken, video }: { accessToken: string | null; video: QosReviewVideo }) {
  const titleId = React.useId();

  return (
    <Card role="article" aria-labelledby={titleId}>
      <CardHeader>
        <CardTitle id={titleId}>{video.model_group}</CardTitle>
        <CardDescription>
          {new Date(video.created_at).toLocaleString()} · {video.reviews} ratings · average {formatScore(video.overall)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {video.status === "generating" && (
          <p role="status" className="text-sm text-muted-foreground">
            Still generating; the AI rates it as soon as it finishes
          </p>
        )}
        {video.status === "failed" && (
          <p role="status" className="text-sm text-destructive">
            The provider could not generate this video
          </p>
        )}
        {video.status === "completed" && (
          <>
            <VideoPlayer accessToken={accessToken} videoId={video.video_id} />
            {video.ai_review !== null && <AiReview review={video.ai_review} />}
            <VideoReviewForm accessToken={accessToken} video={video} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function PromptGroup({ accessToken, group }: { accessToken: string | null; group: PromptVideos }) {
  const labelId = React.useId();
  return (
    <div role="group" aria-labelledby={labelId} className="flex flex-col gap-3">
      <p id={labelId} className="text-sm">
        <span className="text-muted-foreground">Prompt: </span>
        {group.prompt}
      </p>
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {group.videos.map((video) => (
          <VideoReviewCard key={video.video_id} accessToken={accessToken} video={video} />
        ))}
      </div>
    </div>
  );
}

export default function QosVideoReviewPanel({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("7d");
  const [evaluating, setEvaluating] = React.useState(false);
  const [started, setStarted] = React.useState<{ readonly run: QosVideoEvaluationStarted; readonly at: number } | null>(
    null,
  );
  const reviewsQuery = useQosVideoReviews(accessToken, range, started?.at ?? null);
  const data = reviewsQuery.data;
  const ratingsId = React.useId();
  const aiRatingsId = React.useId();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-review-range" className="text-sm text-muted-foreground">
            Time range
          </label>
          <Select
            items={QOS_RANGES}
            value={range}
            onValueChange={(value: string | null) => {
              if (value !== null && isQosRange(value)) setRange(value);
            }}
          >
            <SelectTrigger id="qos-review-range" className="w-44">
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
        <Button variant="outline" disabled={reviewsQuery.isFetching} onClick={() => void reviewsQuery.refetch()}>
          <RefreshCw className={`size-4 ${reviewsQuery.isFetching ? "animate-spin" : ""}`} />
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
            {started.run.models.join(", ")} are generating the prompt. Their videos and AI ratings appear below as they
            finish, and this list refreshes every 30 seconds meanwhile.
          </AlertDescription>
        </Alert>
      )}

      {reviewsQuery.error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load videos to review</AlertTitle>
          <AlertDescription>{extractErrorMessage(reviewsQuery.error)}</AlertDescription>
        </Alert>
      )}

      <section aria-labelledby={ratingsId} className="flex flex-col gap-2">
        <h3 id={ratingsId} className="text-base font-semibold">
          Ratings per model
        </h3>
        <DataTable
          data={data === undefined ? [] : [...data.summary]}
          columns={summaryColumns}
          getRowId={(summary) => summary.model_group}
          isLoading={reviewsQuery.isLoading}
          noDataMessage="No ratings in this time range"
        />
      </section>

      <section aria-labelledby={aiRatingsId} className="flex flex-col gap-2">
        <h3 id={aiRatingsId} className="text-base font-semibold">
          AI ratings per model
        </h3>
        <DataTable
          data={data === undefined ? [] : [...data.ai_summary]}
          columns={aiSummaryColumns}
          getRowId={(summary) => summary.model_group}
          isLoading={reviewsQuery.isLoading}
          noDataMessage="No AI ratings in this time range"
        />
      </section>

      <section className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h3 className="text-base font-semibold">Videos to review</h3>
          <p className="text-sm text-muted-foreground">
            Every model in a probe run gets the same prompt, and the image-to-video models the same first frame, so
            compare them side by side and rate each from 1 (bad) to 5 (good). Saving again replaces your own earlier
            rating; other reviewers keep theirs.
          </p>
          <p className="text-sm text-muted-foreground">
            A vision model also rates each finished video from one still per second. Its ratings are kept apart from the
            ratings people give.
          </p>
        </div>
        {data !== undefined && data.videos.length === 0 && (
          <p className="text-sm text-muted-foreground">No finished probe videos in this time range</p>
        )}
        {videosByPrompt(data?.videos ?? []).map((group) => (
          <PromptGroup key={group.prompt} accessToken={accessToken} group={group} />
        ))}
      </section>

      {evaluating && (
        <StartVideoEvaluationDialog
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
