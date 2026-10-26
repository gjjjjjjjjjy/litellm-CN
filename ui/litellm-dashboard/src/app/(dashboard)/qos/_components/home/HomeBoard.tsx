"use client";

import React from "react";
import Image from "next/image";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  Timer,
  Zap,
} from "lucide-react";

import { useQosHealth } from "@/app/(dashboard)/hooks/qos/useQosHealth";
import { useQosSummary } from "@/app/(dashboard)/hooks/qos/useQosSummary";
import { useQosTrends } from "@/app/(dashboard)/hooks/qos/useQosTrends";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import { AreaChart, LineChart, type ChartColor } from "@/components/shared/charts";
import { cn } from "@/lib/cva.config";
import { isProxyAdminRole } from "@/utils/roles";
import { uiHref } from "@/utils/uiHref";
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

const HEADLINE_STYLE: Readonly<Record<string, { readonly icon: typeof Activity; readonly className: string }>> = {
  requests: { icon: Activity, className: "bg-primary/10 text-primary" },
  success: { icon: CircleCheck, className: "bg-success/10 text-success" },
  ttft: { icon: Timer, className: "bg-warning/10 text-warning" },
  throughput: { icon: Zap, className: "bg-violet-500/10 text-violet-500" },
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
  const Icon = change.percent >= 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs", change.better ? "text-success" : "text-destructive")}>
      <Icon className="size-3.5" aria-hidden="true" />
      {`${change.percent >= 0 ? "+" : ""}${change.percent.toFixed(1)}% vs previous 24 h`}
    </span>
  );
};

const ModelStatusCard = ({ card }: { card: ModelCard }) => {
  const style = STATUS_STYLE[card.status];
  const Icon = style.icon;
  return (
    <article className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/40">
      <Icon className={cn("size-4 shrink-0", style.className)} aria-label={statusLabel(card.status)} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={card.model}>
          {card.model}
        </p>
        <p className="mt-0.5 truncate text-xs text-muted-foreground" title={card.vendors.join(" · ")}>
          {card.vendors.join(" · ")}
        </p>
      </div>
      <div className="w-20 shrink-0 text-right text-sm tabular-nums">
        <p className="text-[11px] text-muted-foreground">TTFT P95</p>
        <p className="mt-0.5 font-medium">{card.metrics === undefined ? "-" : formatMs(card.metrics.ttft_ms.p95)}</p>
      </div>
      <div className="w-16 shrink-0 text-right text-sm tabular-nums">
        <p className="text-[11px] text-muted-foreground">Success</p>
        <p className="mt-0.5 font-medium">
          {card.metrics === undefined ? "-" : formatRatio(successRate(card.metrics))}
        </p>
      </div>
      <div className="hidden w-24 shrink-0 xl:block">
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
          className="h-9"
        />
      </div>
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
    <div className="flex min-h-full min-w-0 flex-col gap-4 bg-muted/30 p-4 text-foreground lg:h-full lg:min-h-[600px] xl:p-5">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Image
            src={uiHref("assets/logos/qosllm.svg")}
            alt=""
            aria-hidden="true"
            width={40}
            height={40}
            className="size-10 shrink-0"
          />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">QosLLM</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">Service quality board · last 24 hours</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div
            className={cn(
              "flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5 text-xs font-medium",
              STATUS_STYLE[status].className,
            )}
            role="status"
          >
            <StatusIcon className="size-3.5" />
            {statusLabel(status)}
          </div>
          <div className="hidden border-l pl-4 text-right tabular-nums sm:block">
            <p className="text-sm font-medium">{now.toLocaleTimeString()}</p>
            <p className="text-[11px] text-muted-foreground">{now.toLocaleDateString()}</p>
          </div>
        </div>
      </header>

      <section className="grid shrink-0 grid-cols-2 gap-3 lg:grid-cols-4">
        {figures.map((figure) => {
          const style = HEADLINE_STYLE[figure.key];
          const Icon = style.icon;
          return (
            <div key={figure.key} className="rounded-xl border bg-card p-3.5 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium text-muted-foreground">{figure.label}</p>
                <span className={cn("flex size-6 items-center justify-center rounded-lg", style.className)}>
                  <Icon className="size-3.5" aria-hidden="true" />
                </span>
              </div>
              <p className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">{figure.value}</p>
              <div className="mt-1.5">
                <ChangeBadge change={figure.change} />
              </div>
            </div>
          );
        })}
      </section>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1.8fr)_minmax(300px,1fr)]">
        <div className="flex min-h-0 min-w-0 flex-col gap-4">
          <section className="shrink-0 rounded-xl border bg-card p-4 shadow-xs">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Requests over the last 24 hours</h2>
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="size-1.5 rounded-full bg-primary" />
                Requests
              </span>
            </div>
            <AreaChart
              data={trends === undefined ? [] : requestVolume(trends)}
              index="time"
              categories={["requests"]}
              colors={["blue"]}
              showLegend={false}
              yAxisWidth={40}
              className="mt-3 h-36"
            />
          </section>
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">
            <header className="flex shrink-0 items-center justify-between border-b px-4 py-3">
              <h2 className="text-sm font-semibold">Models</h2>
              <span className="rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                {cards.length}
              </span>
            </header>
            {cards.length === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-muted-foreground">
                No model has traffic or health checks yet
              </p>
            ) : (
              <div
                className="max-h-80 min-h-0 divide-y overflow-y-auto overscroll-contain lg:max-h-none"
                role="region"
                aria-label="Models"
                tabIndex={0}
              >
                {cards.map((card) => (
                  <ModelStatusCard key={card.model} card={card} />
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="grid min-h-0 min-w-0 gap-4 lg:grid-rows-[auto_minmax(0,1.2fr)_minmax(0,1fr)]">
          <AnnouncementsPanel accessToken={accessToken} canManage={canManage} now={now} />
          <NewsPanel accessToken={accessToken} now={now} />
          <ActivityPanel accessToken={accessToken} refreshMs={REFRESH_MS} now={now} />
        </div>
      </div>
    </div>
  );
}
