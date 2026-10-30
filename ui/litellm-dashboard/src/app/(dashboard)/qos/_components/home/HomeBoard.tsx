"use client";

import React from "react";
import Image from "next/image";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock3,
  Cpu,
  Globe2,
  RefreshCw,
  Timer,
} from "lucide-react";

import { useQosTargets } from "@/app/(dashboard)/hooks/qos/useQosBenchmarks";
import { healthKeys, useQosHealth, useRefreshQosHealth } from "@/app/(dashboard)/hooks/qos/useQosHealth";
import { homeKeys } from "@/app/(dashboard)/hooks/qos/useQosHome";
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
const INITIAL_VISIBLE_CHANNELS = 3;

interface StatusStyle {
  readonly icon: typeof CircleCheck;
  readonly className: string;
  readonly dot: string;
  readonly badge: string;
  readonly label: string;
}

const STATUS_STYLE: Readonly<Record<ServiceStatus, StatusStyle>> = {
  ok: {
    icon: CircleCheck,
    className: "text-success",
    dot: "bg-success",
    badge: "bg-success/10 text-success",
    label: "Operational",
  },
  degraded: {
    icon: CircleAlert,
    className: "text-warning",
    dot: "bg-warning",
    badge: "bg-warning/10 text-warning",
    label: "Degraded",
  },
  down: {
    icon: CircleX,
    className: "text-destructive",
    dot: "bg-destructive",
    badge: "bg-destructive/10 text-destructive",
    label: "Unavailable",
  },
  idle: {
    icon: CircleDashed,
    className: "text-muted-foreground",
    dot: "bg-muted-foreground",
    badge: "bg-muted text-muted-foreground",
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

const RefreshAction = ({
  checking,
  fetching,
  canCheckHealth,
  onRefresh,
}: {
  checking: boolean;
  fetching: boolean;
  canCheckHealth: boolean;
  onRefresh: () => void;
}) => {
  const busy = checking ? true : fetching;
  const label = canCheckHealth ? "Check and refresh" : "Refresh data";
  return (
    <Button variant="outline" size="sm" onClick={onRefresh} disabled={busy}>
      <RefreshCw className={cn("size-3.5", busy && "motion-safe:animate-spin")} />
      {checking ? "Checking endpoints" : label}
    </Button>
  );
};

const ChannelStatusCard = ({ card, now }: { card: ChannelCard; now: Date }) => {
  const style = STATUS_STYLE[card.status];
  return (
    <article className="min-w-0 overflow-hidden rounded-xl border border-border/70 bg-card p-5 shadow-xs transition-shadow hover:shadow-sm">
      <header className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-blue-500/8 text-blue-600 dark:text-blue-400">
          <Cpu className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[15px] font-semibold tracking-tight" title={card.model}>
            {card.model}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">{vendorName(card.deployment.vendor)}</p>
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
            style.badge,
          )}
        >
          <span className={cn("size-1.5 rounded-full", style.dot)} aria-hidden="true" />
          {style.label}
        </span>
      </header>
      {card.deployment.api_base !== "" && (
        <p
          className="mt-4 flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground"
          title={card.deployment.api_base}
        >
          <Globe2 className="size-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{card.deployment.api_base}</span>
        </p>
      )}
      <dl className="mt-5 grid grid-cols-2 divide-x border-y border-border/60 py-4">
        <div className="pr-4">
          <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Timer className="size-3" aria-hidden="true" />
            TTFT
          </dt>
          <dd className="mt-2 text-xl font-semibold tracking-tight tabular-nums">
            {formatMs(card.health?.last_ttft_ms)}
          </dd>
        </div>
        <div className="pl-4">
          <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Activity className="size-3" aria-hidden="true" />
            Response time
          </dt>
          <dd className="mt-2 text-xl font-semibold tracking-tight tabular-nums">
            {formatMs(card.health?.last_latency_ms)}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] text-muted-foreground">
        {card.health?.last_streamed_at == null
          ? "No streamed check yet"
          : `Streamed check ${relativeTimeLabel(card.health.last_streamed_at, now)}`}
      </p>
      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="text-[11px] leading-4 text-muted-foreground">
          <p>Health check availability</p>
          <p>Last 24 hours</p>
        </div>
        <p className="text-lg font-semibold tracking-tight tabular-nums">
          {card.health === undefined ? "-" : `${(card.health.availability * 100).toFixed(2)}%`}
        </p>
      </div>
      <p
        className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground"
        title="Stable health checks are recorded hourly; manual checks are always recorded"
      >
        <Clock3 className="size-3" aria-hidden="true" />
        {card.health === undefined
          ? "No health check yet"
          : `Last recorded check ${relativeTimeLabel(card.health.last_checked_at, now)}`}
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

export default function HomeBoard({
  accessToken,
  canCheckHealth,
}: {
  accessToken: string | null;
  canCheckHealth: boolean;
}) {
  const queryClient = useQueryClient();
  const checkHealth = useRefreshQosHealth(accessToken);
  const now = useNow();
  const [expanded, setExpanded] = React.useState(false);
  const targetsQuery = useQosTargets(accessToken, REFRESH_MS);
  const healthQuery = useQosHealth(accessToken, BOARD_RANGE, REFRESH_MS);
  const cards = channelCards(
    targetsQuery.data === undefined ? [] : targetsQuery.data,
    healthQuery.data === undefined ? [] : healthQuery.data.nodes,
  );
  const visibleCards = expanded ? cards : cards.slice(0, INITIAL_VISIBLE_CHANNELS);
  const ExpandIcon = expanded ? ChevronUp : ChevronDown;
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
  const refreshData = () =>
    Promise.all([targetsQuery.refetch(), queryClient.invalidateQueries({ queryKey: homeKeys.all })]);
  const refresh = () => {
    if (canCheckHealth) {
      checkHealth.mutate(undefined, {
        onSuccess: (data) => {
          queryClient.setQueryData(healthKeys.list({ filters: { range: BOARD_RANGE } }), data);
          void refreshData();
        },
      });
      return;
    }
    void healthQuery.refetch();
    void refreshData();
  };

  return (
    <div className="min-h-full min-w-0 bg-muted/15 px-4 py-6 text-foreground md:px-8">
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
            <RefreshAction
              checking={checkHealth.isPending}
              fetching={fetching}
              canCheckHealth={canCheckHealth}
              onRefresh={refresh}
            />
          </div>
        </header>

        <section
          className="flex flex-wrap items-center justify-between gap-6 rounded-xl border border-border/70 bg-card px-5 py-5 sm:px-6"
          aria-label="Service overview"
        >
          <div className="flex items-center gap-3">
            <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-full", style.badge)}>
              <StatusIcon className="size-5" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-base font-semibold" role="status">
                {title}
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">Automatic data refresh every minute</p>
            </div>
          </div>
          <dl className="grid w-full grid-cols-4 divide-x sm:w-auto">
            {figures.map((figure) => (
              <div key={figure.label} className="min-w-0 px-4 text-center first:pl-0 last:pr-0">
                <dt className="text-[11px] text-muted-foreground">{figure.label}</dt>
                <dd className={cn("mt-1 text-xl font-semibold tabular-nums", figure.className)}>
                  {targetsQuery.data === undefined ? "-" : figure.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {checkHealth.isError && (
          <Alert variant="destructive">
            <AlertTitle>Endpoint checks could not be completed</AlertTitle>
            <AlertDescription>{extractErrorMessage(checkHealth.error)}</AlertDescription>
          </Alert>
        )}

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

        <section aria-label="Channel status" className="flex flex-col gap-3">
          <header className="flex items-center justify-between gap-3 px-0.5">
            <h2 className="text-sm font-semibold">Model channels</h2>
            {targetsQuery.isSuccess && (
              <p className="text-xs tabular-nums text-muted-foreground">{`${visibleCards.length} of ${cards.length} channels`}</p>
            )}
          </header>
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
          <div id="home-model-channels" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] gap-4">
            {visibleCards.map((card) => (
              <ChannelStatusCard key={`${card.model}-${card.deployment.model_id}`} card={card} now={now} />
            ))}
          </div>
          {cards.length > INITIAL_VISIBLE_CHANNELS && (
            <div className="flex justify-center pt-1">
              <Button
                variant="outline"
                size="sm"
                className="rounded-full px-5"
                aria-expanded={expanded}
                aria-controls="home-model-channels"
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? "Show fewer models" : "View more models"}
                <ExpandIcon className="size-3.5" aria-hidden="true" />
              </Button>
            </div>
          )}
        </section>

        <ActivityPanel accessToken={accessToken} refreshMs={REFRESH_MS} now={now} />
      </div>
    </div>
  );
}
