"use client";

import React from "react";
import { CircleAlert, CircleCheck, CircleDashed, CircleX } from "lucide-react";

import { useQosHealth } from "@/app/(dashboard)/hooks/qos/useQosHealth";
import { useQosSummary } from "@/app/(dashboard)/hooks/qos/useQosSummary";
import { useQosTrends } from "@/app/(dashboard)/hooks/qos/useQosTrends";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import { AreaChart, LineChart, type ChartColor } from "@/components/shared/charts";
import { cn } from "@/lib/cva.config";
import { isProxyAdminRole } from "@/utils/roles";
import { headlines, type Change } from "../dashboardData";
import { formatMs, formatRatio, successRate } from "../qosData";
import { ActivityPanel, AnnouncementsPanel, NewsPanel } from "./HomeFeeds";
import { modelCards, overallStatus, requestVolume, statusLabel, type ModelCard, type ServiceStatus } from "./homeData";

const REFRESH_MS = 60_000;
const BOARD_RANGE = "24h";
const HEADLINE_KEYS = ["requests", "success", "ttft", "throughput"];
const BOARD_TRENDS = { range: BOARD_RANGE, tag: "", groupBy: "model", refreshMs: REFRESH_MS } as const;

const STATUS_STYLE: Readonly<Record<ServiceStatus, { readonly icon: typeof CircleCheck; readonly className: string }>> =
  {
    ok: { icon: CircleCheck, className: "text-success" },
    degraded: { icon: CircleAlert, className: "text-warning" },
    down: { icon: CircleX, className: "text-destructive" },
    idle: { icon: CircleDashed, className: "text-muted-foreground" },
  };

const STATUS_COLOR: Readonly<Record<ServiceStatus, ChartColor>> = {
  ok: "emerald",
  degraded: "amber",
  down: "rose",
  idle: "slate",
};

const useNow = (): Date => {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
};

const ChangeBadge = ({ change }: { change: Change }) => {
  if (change === null) return <span className="text-xs text-muted-foreground">No earlier data</span>;
  return (
    <span className={cn("text-xs font-medium", change.better ? "text-success" : "text-destructive")}>
      {`${change.percent >= 0 ? "+" : ""}${change.percent.toFixed(1)}% vs previous 24 h`}
    </span>
  );
};

const ModelStatusCard = ({ card }: { card: ModelCard }) => {
  const style = STATUS_STYLE[card.status];
  const Icon = style.icon;
  return (
    <article className="flex flex-col gap-2 rounded-xl border border-border/60 bg-card/60 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium">{card.model}</p>
          <p className="truncate text-xs text-muted-foreground">{card.vendors.join(" · ")}</p>
        </div>
        <Icon className={cn("size-5 shrink-0", style.className)} aria-label={statusLabel(card.status)} />
      </div>
      <div className="flex items-baseline gap-4 text-sm tabular-nums">
        <span>
          <span className="text-xs text-muted-foreground">TTFT P95 </span>
          {card.metrics === undefined ? "-" : formatMs(card.metrics.ttft_ms.p95)}
        </span>
        <span>
          <span className="text-xs text-muted-foreground">Success </span>
          {card.metrics === undefined ? "-" : formatRatio(successRate(card.metrics))}
        </span>
      </div>
      <LineChart
        data={card.ttftTrend}
        index="time"
        categories={["ttft"]}
        colors={[STATUS_COLOR[card.status]]}
        showXAxis={false}
        showLegend={false}
        showGridLines={false}
        yAxisWidth={0}
        valueFormatter={formatMs}
        className="h-12"
      />
    </article>
  );
};

export default function HomeBoard({ accessToken }: { accessToken: string | null }) {
  const { userRole, isViewOnly } = useAuthorized();
  const canManage = isProxyAdminRole(userRole) && !isViewOnly;
  const now = useNow();
  const summary = useQosSummary(accessToken, BOARD_RANGE, "", REFRESH_MS).data;
  const trends = useQosTrends(accessToken, BOARD_TRENDS).data;
  const health = useQosHealth(accessToken, BOARD_RANGE, REFRESH_MS).data;

  const cards = modelCards(
    summary === undefined ? [] : summary.model_groups,
    health === undefined ? [] : health.nodes,
    trends,
  );
  const status = overallStatus(cards.map((card) => card.status));
  const StatusIcon = STATUS_STYLE[status].icon;
  const figures =
    trends === undefined
      ? []
      : headlines(trends.current, trends.previous).filter((headline) => HEADLINE_KEYS.includes(headline.key));

  return (
    <div className="dark">
      <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-6 rounded-2xl bg-background p-6 text-foreground">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">QosLLM</h1>
            <p className="text-sm text-muted-foreground">Service quality board · last 24 hours</p>
          </div>
          <div
            className={cn(
              "flex items-center gap-2 rounded-full border border-border/60 bg-card/60 px-4 py-2 text-sm font-medium",
              STATUS_STYLE[status].className,
            )}
            role="status"
          >
            <StatusIcon className="size-4" />
            {statusLabel(status)}
          </div>
          <div className="text-right tabular-nums">
            <p className="text-2xl font-semibold">{now.toLocaleTimeString()}</p>
            <p className="text-xs text-muted-foreground">{now.toLocaleDateString()}</p>
          </div>
        </header>

        <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {figures.map((figure) => (
            <div key={figure.key} className="rounded-xl border border-border/60 bg-card/60 p-5">
              <p className="text-sm text-muted-foreground">{figure.label}</p>
              <p className="mt-2 text-4xl font-semibold tracking-tight tabular-nums">{figure.value}</p>
              <div className="mt-2">
                <ChangeBadge change={figure.change} />
              </div>
            </div>
          ))}
        </section>

        <div className="grid min-h-0 flex-1 gap-6 xl:grid-cols-3">
          <div className="flex min-w-0 flex-col gap-6 xl:col-span-2">
            <section className="rounded-xl border border-border/60 bg-card/60 p-5">
              <h2 className="text-sm font-medium text-muted-foreground">Requests over the last 24 hours</h2>
              <AreaChart
                data={trends === undefined ? [] : requestVolume(trends)}
                index="time"
                categories={["requests"]}
                colors={["cyan"]}
                showLegend={false}
                yAxisWidth={40}
                className="mt-3 h-56"
              />
            </section>
            <section>
              <h2 className="mb-3 text-sm font-medium text-muted-foreground">Models</h2>
              {cards.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border/60 py-10 text-center text-sm text-muted-foreground">
                  No model has traffic or health checks yet
                </p>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
                  {cards.map((card) => (
                    <ModelStatusCard key={card.model} card={card} />
                  ))}
                </div>
              )}
            </section>
          </div>

          <div className="grid min-h-0 gap-6 xl:grid-rows-[auto_minmax(0,1fr)_minmax(0,1fr)]">
            <AnnouncementsPanel accessToken={accessToken} canManage={canManage} now={now} />
            <NewsPanel accessToken={accessToken} now={now} />
            <ActivityPanel accessToken={accessToken} refreshMs={REFRESH_MS} now={now} />
          </div>
        </div>
      </div>
    </div>
  );
}
