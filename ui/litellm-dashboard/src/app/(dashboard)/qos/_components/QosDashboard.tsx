"use client";

import React from "react";
import { Activity, BarChart3, HeartPulse, TrendingDown, TrendingUp } from "lucide-react";

import { useQosHealth } from "@/app/(dashboard)/hooks/qos/useQosHealth";
import { useQosTrends } from "@/app/(dashboard)/hooks/qos/useQosTrends";
import { Panel, Segmented, Stat } from "@/app/(dashboard)/usage/_components/components/overview/Primitives";
import { BarChart, LineChart } from "@/components/shared/charts";
import { Meter, MeterIndicator, MeterTrack } from "@/components/shared/Meter";
import { StatusBadge } from "@/components/shared/table_cells";
import { cn } from "@/lib/cva.config";
import {
  COMPARE_METRICS,
  TREND_GROUPINGS,
  TREND_METRICS,
  compareBars,
  compareValueFormatter,
  headlines,
  trendChart,
  trendValueFormatter,
  type Change,
  type CompareMetric,
  type TrendGrouping,
  type TrendMetric,
} from "./dashboardData";
import { formatRatio, type QosHealthNode, type QosRange, type QosSummary } from "./qosData";
import VendorName from "./VendorName";

interface QosDashboardProps {
  readonly accessToken: string | null;
  readonly range: QosRange;
  readonly tag: string;
  readonly summary: QosSummary | undefined;
  readonly refreshMs: number | false;
}

const ChangeHint = ({ change }: { change: Change }) => {
  if (change === null) return <span>No earlier data</span>;
  const Icon = change.percent >= 0 ? TrendingUp : TrendingDown;
  return (
    <span className={cn("inline-flex items-center gap-1", change.better ? "text-success" : "text-destructive")}>
      <Icon className="size-3" aria-hidden="true" />
      {`${Math.abs(change.percent).toFixed(1)}% vs previous period`}
    </span>
  );
};

const byAttention = (left: QosHealthNode, right: QosHealthNode): number => {
  const leftDown = left.latest_status === "unhealthy" ? 0 : 1;
  const rightDown = right.latest_status === "unhealthy" ? 0 : 1;
  if (leftDown !== rightDown) return leftDown - rightDown;
  return left.availability - right.availability;
};

const HEADLINE_COUNT = 5;

const compareRowsFor = (summary: QosSummary | undefined, grouping: TrendGrouping) => {
  if (summary === undefined) return [];
  return grouping === "model" ? summary.model_groups : summary.deployments;
};

const NodeHealthRow = ({ node }: { node: QosHealthNode }) => (
  <li className="flex items-center gap-3 py-2">
    <div className="min-w-0 flex-1">
      <VendorName vendor={node.vendor} />
      <p className="truncate text-xs text-muted-foreground">{node.model_name}</p>
    </div>
    <Meter value={node.availability * 100} aria-label={`${node.model_name} availability`} className="w-28">
      <MeterTrack>
        <MeterIndicator tone={node.availability < 0.99 ? "over" : "default"} />
      </MeterTrack>
    </Meter>
    <span className="w-14 text-right text-xs tabular-nums">{formatRatio(node.availability)}</span>
    <StatusBadge
      tone={node.latest_status === "unhealthy" ? "error" : "success"}
      label={node.latest_status === "unhealthy" ? "Unhealthy" : "Healthy"}
    />
  </li>
);

export default function QosDashboard({ accessToken, range, tag, summary, refreshMs }: QosDashboardProps) {
  const [grouping, setGrouping] = React.useState<TrendGrouping>("model");
  const [trendMetric, setTrendMetric] = React.useState<TrendMetric>("ttft");
  const [compareMetric, setCompareMetric] = React.useState<CompareMetric>("ttft");
  const trendsQuery = { range, tag, groupBy: grouping, refreshMs };
  const trends = useQosTrends(accessToken, trendsQuery).data;
  const health = useQosHealth(accessToken, range, refreshMs).data;

  const nodes = health === undefined ? [] : [...health.nodes].sort(byAttention);
  const unhealthy = nodes.filter((node) => node.latest_status === "unhealthy").length;
  const chart = trends === undefined ? undefined : trendChart(trends, trendMetric);
  const bars = compareBars(compareRowsFor(summary, grouping), compareMetric);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Service quality at a glance</h2>
        <Segmented label="Group charts" value={grouping} options={TREND_GROUPINGS} onChange={setGrouping} />
      </div>

      <section className="grid grid-cols-2 gap-4 rounded-xl border bg-card p-5 md:grid-cols-3 xl:grid-cols-6">
        {trends === undefined
          ? Array.from({ length: HEADLINE_COUNT }, (_, index) => <Stat key={index} label="" value="" pending />)
          : headlines(trends.current, trends.previous).map((headline) => (
              <Stat
                key={headline.key}
                label={headline.label}
                value={headline.value}
                hint={<ChangeHint change={headline.change} />}
              />
            ))}
        <Stat
          label="Unhealthy nodes"
          value={health === undefined ? "" : `${unhealthy} / ${nodes.length}`}
          pending={health === undefined}
          tone={unhealthy > 0 ? "destructive" : "success"}
          hint="Latest health check per node"
        />
      </section>

      <Panel
        icon={Activity}
        title="Trend"
        subtitle={
          trends === undefined ? undefined : `One point every ${Math.round(trends.bucket_seconds / 60)} minutes`
        }
        action={
          <Segmented label="Trend metric" value={trendMetric} options={TREND_METRICS} onChange={setTrendMetric} />
        }
      >
        <LineChart
          data={chart === undefined ? [] : chart.rows}
          index="time"
          categories={chart === undefined ? [] : chart.categories}
          valueFormatter={trendValueFormatter(trendMetric)}
          yAxisWidth={64}
          className="h-72"
        />
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          icon={BarChart3}
          title="Comparison"
          subtitle={grouping === "model" ? "Each model over the selected period" : "Each provider of each model"}
          action={
            <Segmented
              label="Comparison metric"
              value={compareMetric}
              options={COMPARE_METRICS}
              onChange={setCompareMetric}
            />
          }
        >
          <BarChart
            data={bars}
            index="name"
            categories={["value"]}
            layout="vertical"
            colorByDatum
            showLegend={false}
            valueFormatter={compareValueFormatter(compareMetric)}
            yAxisWidth={180}
            className="h-72"
          />
        </Panel>

        <Panel
          icon={HeartPulse}
          title="Node health"
          subtitle="Availability from health checks, nodes needing attention first"
          bodyClassName="max-h-80 overflow-y-auto"
        >
          {nodes.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">No health checks in this time range</p>
          ) : (
            <ul className="divide-y">
              {nodes.map((node) => (
                <NodeHealthRow key={node.model_id} node={node} />
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
