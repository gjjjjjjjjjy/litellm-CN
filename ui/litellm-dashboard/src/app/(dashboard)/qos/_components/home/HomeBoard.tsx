"use client";

import React from "react";
import Image from "next/image";
import { Activity, CircleAlert, CircleCheck, CircleDashed, CircleX, Clock3, RefreshCw, Timer } from "lucide-react";

import { useQosTargets } from "@/app/(dashboard)/hooks/qos/useQosBenchmarks";
import { useQosHealth } from "@/app/(dashboard)/hooks/qos/useQosHealth";
import { useQosSummary } from "@/app/(dashboard)/hooks/qos/useQosSummary";
import { Logo } from "@/components/molecules/logo/Logo";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cva.config";
import { extractErrorMessage } from "@/utils/errorUtils";
import { uiHref } from "@/utils/uiHref";
import { formatMs, vendorName } from "../qosData";
import { ActivityPanel } from "./HomeFeeds";
import {
  channelCards,
  overallStatus,
  relativeTimeLabel,
  statusLabel,
  type ChannelCard,
  type ServiceStatus,
} from "./homeData";

const REFRESH_MS = 60_000;
const BOARD_RANGE = "24h";

interface StatusStyle {
  readonly icon: typeof CircleCheck;
  readonly className: string;
  readonly dot: string;
  readonly badge: string;
  readonly surface: string;
  readonly label: string;
}

const STATUS_STYLE: Readonly<Record<ServiceStatus, StatusStyle>> = {
  ok: {
    icon: CircleCheck,
    className: "text-success",
    dot: "bg-success",
    badge: "bg-success/10 text-success",
    surface: "border-success/20 bg-success/5",
    label: "Operational",
  },
  degraded: {
    icon: CircleAlert,
    className: "text-warning",
    dot: "bg-warning",
    badge: "bg-warning/10 text-warning",
    surface: "border-warning/20 bg-warning/5",
    label: "Degraded",
  },
  down: {
    icon: CircleX,
    className: "text-destructive",
    dot: "bg-destructive",
    badge: "bg-destructive/10 text-destructive",
    surface: "border-destructive/20 bg-destructive/5",
    label: "Unavailable",
  },
  idle: {
    icon: CircleDashed,
    className: "text-muted-foreground",
    dot: "bg-muted-foreground",
    badge: "bg-muted text-muted-foreground",
    surface: "border-border bg-muted/30",
    label: "Awaiting checks",
  },
};

const useNow = (): Date => {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);
  return now;
};

const RefreshStatus = ({ fetching, updatedAt }: { fetching: boolean; updatedAt: number }) => {
  if (!fetching && updatedAt === 0) return null;
  return (
    <p className="text-xs text-muted-foreground" aria-live="polite">
      {fetching ? "Refreshing" : `Updated ${new Date(updatedAt).toLocaleTimeString()}`}
    </p>
  );
};

const ChannelStatusCard = ({ card, now }: { card: ChannelCard; now: Date }) => {
  const style = STATUS_STYLE[card.status];
  return (
    <article className="min-w-0 rounded-xl border bg-card p-4 shadow-xs transition-colors hover:border-primary/30">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted/30">
          <Logo provider={card.deployment.vendor} className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold" title={card.model}>
            {card.model}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">{vendorName(card.deployment.vendor)}</p>
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium",
            style.badge,
          )}
        >
          <span className={cn("size-1.5 rounded-full", style.dot)} aria-hidden="true" />
          {style.label}
        </span>
      </header>
      {card.deployment.api_base !== "" && (
        <p className="mt-3 truncate font-mono text-[11px] text-muted-foreground" title={card.deployment.api_base}>
          {card.deployment.api_base}
        </p>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5">
          <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Timer className="size-3" aria-hidden="true" />
            TTFT P95
          </dt>
          <dd className="mt-1 text-lg font-semibold tracking-tight tabular-nums">
            {card.metrics === undefined ? "-" : formatMs(card.metrics.ttft_ms.p95)}
          </dd>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5">
          <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Activity className="size-3" aria-hidden="true" />
            Response latency P95
          </dt>
          <dd className="mt-1 text-lg font-semibold tracking-tight tabular-nums">
            {card.metrics === undefined ? "-" : formatMs(card.metrics.e2e_latency_ms.p95)}
          </dd>
        </div>
      </dl>
      <div className="mt-4 flex items-center justify-between gap-3 border-t pt-3">
        <div className="text-[11px] leading-5 text-muted-foreground">
          <p>Health check availability</p>
          <p>Last 24 hours</p>
        </div>
        <p className={cn("text-2xl font-semibold tracking-tight tabular-nums", style.className)}>
          {card.health === undefined ? "-" : `${(card.health.availability * 100).toFixed(2)}%`}
        </p>
      </div>
      <p className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Clock3 className="size-3" aria-hidden="true" />
        {card.health === undefined
          ? "No health check yet"
          : `Checked ${relativeTimeLabel(card.health.last_checked_at, now)}`}
      </p>
      {card.health?.latest_status === "unhealthy" && card.health.last_error !== null && (
        <p
          className="mt-2 line-clamp-2 break-words rounded-md bg-destructive/5 px-2 py-1.5 text-xs text-destructive"
          title={card.health.last_error}
        >
          {card.health.last_error}
        </p>
      )}
    </article>
  );
};

export default function HomeBoard({ accessToken }: { accessToken: string | null }) {
  const now = useNow();
  const targetsQuery = useQosTargets(accessToken, REFRESH_MS);
  const healthQuery = useQosHealth(accessToken, BOARD_RANGE, REFRESH_MS);
  const summaryQuery = useQosSummary(accessToken, BOARD_RANGE, "", REFRESH_MS);
  const cards = channelCards(
    targetsQuery.data === undefined ? [] : targetsQuery.data,
    healthQuery.data === undefined ? [] : healthQuery.data.nodes,
    summaryQuery.data === undefined ? [] : summaryQuery.data.deployments,
  );
  const statusQueries = [targetsQuery, healthQuery] as const;
  const loading = statusQueries.some((query) => query.isPending);
  const statusFailed = statusQueries.some((query) => query.isError);
  const status = loading ? "idle" : overallStatus(cards.map((card) => card.status));
  const style = STATUS_STYLE[statusFailed ? "idle" : status];
  const StatusIcon = style.icon;
  const statusTitle = loading ? "Loading service status" : statusLabel(status);
  const title = statusFailed ? "Service status unavailable" : statusTitle;
  const queries = [
    { label: "Channels", query: targetsQuery },
    { label: "Health checks", query: healthQuery },
    { label: "Request metrics", query: summaryQuery },
  ] as const;
  const errors = queries.filter(({ query }) => query.isError);
  const fetching = queries.some(({ query }) => query.isFetching);
  const figures = [
    { label: "Channels", value: cards.length, className: "text-foreground" },
    { label: "Operational", value: cards.filter((card) => card.status === "ok").length, className: "text-success" },
    {
      label: "Service issues",
      value: cards.filter((card) => ["down", "degraded"].includes(card.status)).length,
      className: "text-destructive",
    },
    {
      label: "Awaiting checks",
      value: cards.filter((card) => card.status === "idle").length,
      className: "text-muted-foreground",
    },
  ] as const;
  const refresh = () => {
    void targetsQuery.refetch();
    void healthQuery.refetch();
    void summaryQuery.refetch();
  };

  return (
    <div className="min-h-full min-w-0 bg-muted/20 px-4 py-5 text-foreground md:px-6">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-5">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Image
              src={uiHref("assets/logos/qosllm.svg")}
              alt=""
              aria-hidden="true"
              width={38}
              height={38}
              className="size-9 shrink-0"
            />
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Service status</h1>
              <p className="mt-1 text-xs text-muted-foreground">
                Channel availability and response performance at a glance
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <RefreshStatus fetching={fetching} updatedAt={healthQuery.dataUpdatedAt} />
            <Button variant="outline" size="sm" onClick={refresh} disabled={fetching}>
              <RefreshCw className={cn("size-3.5", fetching && "motion-safe:animate-spin")} />
              Refresh
            </Button>
          </div>
        </header>

        <section
          className={cn(
            "flex flex-wrap items-center justify-between gap-5 rounded-xl border p-4 md:px-5",
            style.surface,
          )}
          aria-label="Service overview"
        >
          <div className="flex items-center gap-3">
            <StatusIcon className={cn("size-7 shrink-0", style.className)} aria-hidden="true" />
            <div>
              <h2 className="text-base font-semibold" role="status">
                {title}
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">Latest health checks · data refreshes every minute</p>
            </div>
          </div>
          <dl className="grid grid-cols-4 gap-5 md:gap-8">
            {figures.map((figure) => (
              <div key={figure.label}>
                <dt className="text-[11px] text-muted-foreground">{figure.label}</dt>
                <dd className={cn("mt-1 text-xl font-semibold tabular-nums", figure.className)}>
                  {targetsQuery.data === undefined ? "-" : figure.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {errors.length > 0 && (
          <Alert variant="destructive">
            <AlertTitle>Some data could not be refreshed</AlertTitle>
            <AlertDescription>
              <ul>
                {errors.map(({ label, query }) => (
                  <li key={label}>
                    {label}: {extractErrorMessage(query.error)}
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <section aria-label="Channel status">
          {targetsQuery.isPending && (
            <div
              className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] gap-4"
              role="status"
              aria-label="Loading channels"
            >
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} className="h-64 rounded-xl" />
              ))}
            </div>
          )}
          {targetsQuery.isSuccess && cards.length === 0 && (
            <p className="rounded-xl border bg-card px-4 py-12 text-center text-sm text-muted-foreground">
              No model deployments configured
            </p>
          )}
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] gap-4">
            {cards.map((card) => (
              <ChannelStatusCard key={`${card.model}-${card.deployment.model_id}`} card={card} now={now} />
            ))}
          </div>
        </section>

        <ActivityPanel accessToken={accessToken} refreshMs={REFRESH_MS} now={now} />
      </div>
    </div>
  );
}
