"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Play, RefreshCw } from "lucide-react";

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
  formatScore,
  isQosRange,
  QOS_RANGES,
  REVIEW_DIMENSION_LABELS,
  REVIEW_DIMENSIONS,
  reviewInput,
  reviewScores,
  type QosRange,
  type QosReviewVideo,
  type QosVideoReviewSummary,
  type ReviewDimension,
  type ReviewScores,
} from "./qosData";

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

function VideoReviewCard({ accessToken, video }: { accessToken: string | null; video: QosReviewVideo }) {
  const [scores, setScores] = React.useState<ReviewScores>(() => reviewScores(video.my_review));
  const [comment, setComment] = React.useState(() => video.my_review?.comment ?? "");
  const save = useSaveVideoReview(accessToken);
  const input = reviewInput(scores, comment);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{video.model_group}</CardTitle>
        <CardDescription>
          {new Date(video.created_at).toLocaleString()} · {video.reviews} ratings · average {formatScore(video.overall)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {video.prompt === null ? (
          <p className="text-sm text-muted-foreground">
            No prompt recorded: only videos made by the scheduled probe keep their prompt.
          </p>
        ) : (
          <p className="text-sm">
            <span className="text-muted-foreground">Prompt: </span>
            {video.prompt}
          </p>
        )}
        <VideoPlayer accessToken={accessToken} videoId={video.video_id} />
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
      </CardContent>
    </Card>
  );
}

export default function QosVideoReviewPanel({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("7d");
  const reviewsQuery = useQosVideoReviews(accessToken, range);
  const data = reviewsQuery.data;

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
      </div>

      {reviewsQuery.error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load videos to review</AlertTitle>
          <AlertDescription>{extractErrorMessage(reviewsQuery.error)}</AlertDescription>
        </Alert>
      )}

      <section className="flex flex-col gap-2">
        <h3 className="text-base font-semibold">Ratings per model</h3>
        <DataTable
          data={data === undefined ? [] : [...data.summary]}
          columns={summaryColumns}
          getRowId={(summary) => summary.model_group}
          isLoading={reviewsQuery.isLoading}
          noDataMessage="No ratings in this time range"
        />
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-base font-semibold">Videos to review</h3>
        <p className="text-sm text-muted-foreground">
          Watch each finished video and rate it from 1 (bad) to 5 (good). Saving again replaces your own earlier rating;
          other reviewers keep theirs.
        </p>
        {data !== undefined && data.videos.length === 0 && (
          <p className="text-sm text-muted-foreground">No finished videos in this time range</p>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          {(data?.videos ?? []).map((video) => (
            <VideoReviewCard key={video.video_id} accessToken={accessToken} video={video} />
          ))}
        </div>
      </section>
    </div>
  );
}
