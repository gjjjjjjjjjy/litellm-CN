"use client";

import type { ColumnDef, Row } from "@tanstack/react-table";
import { ChevronDown, ChevronRight } from "lucide-react";

import { StatusBadge } from "@/components/shared/table_cells";
import { Button } from "@/components/ui/button";
import {
  formatPercentiles,
  interferenceLabel,
  otherTraffic,
  responseCheckBadge,
  formatRate,
  formatRatio,
  nodeLabel,
  successRate,
  type QosBenchmarkDeploymentLevel,
  type QosBenchmarkLevel,
  type QosDeploymentMetrics,
  type QosInterference,
  type QosModelGroupMetrics,
} from "./qosData";
import VendorName from "./VendorName";

const metricColumns = <T extends QosModelGroupMetrics>(): ColumnDef<T>[] => [
  { id: "requests", header: "Requests", cell: ({ row }) => row.original.requests },
  { id: "success_rate", header: "Success rate", cell: ({ row }) => formatRatio(successRate(row.original)) },
  { id: "peak_concurrency", header: "Peak concurrency", cell: ({ row }) => row.original.peak_concurrency },
  { id: "rps", header: "Requests per second", cell: ({ row }) => formatRate(row.original.requests_per_second) },
  { id: "tps", header: "Output tokens/s", cell: ({ row }) => formatRate(row.original.output_tokens_per_second) },
  { id: "ttft", header: "TTFT P50 / P95", cell: ({ row }) => formatPercentiles(row.original.ttft_ms) },
  { id: "tpot", header: "TPOT P50 / P95", cell: ({ row }) => formatPercentiles(row.original.tpot_ms) },
  { id: "e2e", header: "Latency P50 / P95", cell: ({ row }) => formatPercentiles(row.original.e2e_latency_ms) },
];

const ResponseCheckCell = ({ metrics }: { metrics: QosModelGroupMetrics }) => {
  const badge = responseCheckBadge(metrics.response_checks);
  if (badge === null) return <span className="text-muted-foreground">-</span>;
  return <StatusBadge tone={badge.tone} label={badge.label} tooltip={badge.tooltip} />;
};

const OtherTrafficCell = ({ interference }: { interference: QosInterference }) => (
  <StatusBadge
    tone={otherTraffic(interference) === 0 ? "neutral" : "warning"}
    label={String(otherTraffic(interference))}
    tooltip={interferenceLabel(interference)}
  />
);

const benchmarkColumns = <
  T extends QosModelGroupMetrics & { readonly interference: QosInterference },
>(): ColumnDef<T>[] => [
  { id: "response_check", header: "Response check", cell: ({ row }) => <ResponseCheckCell metrics={row.original} /> },
  {
    id: "other_traffic",
    header: "Other traffic",
    cell: ({ row }) => <OtherTrafficCell interference={row.original.interference} />,
  },
];

const ExpandToggle = ({ row }: { row: Row<QosModelGroupMetrics> }) => (
  <Button
    variant="ghost"
    size="icon"
    className="size-6"
    aria-label={row.getIsExpanded() ? "Hide nodes" : "Show nodes"}
    onClick={row.getToggleExpandedHandler()}
  >
    {row.getIsExpanded() ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
  </Button>
);

export const groupColumns: ColumnDef<QosModelGroupMetrics>[] = [
  { id: "expand", header: "", cell: ({ row }) => <ExpandToggle row={row} /> },
  {
    id: "model_group",
    header: "Model",
    cell: ({ row }) =>
      row.original.model_group === "" ? (
        <span className="text-muted-foreground">No public model name</span>
      ) : (
        <span className="font-medium">{row.original.model_group}</span>
      ),
  },
  ...metricColumns<QosModelGroupMetrics>(),
];

const NodeCell = ({ deployment }: { deployment: QosDeploymentMetrics }) => (
  <div className="min-w-0">
    <VendorName vendor={deployment.vendor} />
    <p className="truncate font-mono text-xs text-muted-foreground">{nodeLabel(deployment)}</p>
    <p className="truncate text-xs text-muted-foreground">{deployment.model}</p>
  </div>
);

export const deploymentColumns: ColumnDef<QosDeploymentMetrics>[] = [
  { id: "node", header: "Node", cell: ({ row }) => <NodeCell deployment={row.original} /> },
  ...metricColumns<QosDeploymentMetrics>(),
];

export const deploymentLevelColumns: ColumnDef<QosBenchmarkDeploymentLevel>[] = [
  {
    id: "concurrency",
    header: "Concurrency",
    cell: ({ row }) => <span className="font-medium">{row.original.concurrency}</span>,
  },
  { id: "node", header: "Provider", cell: ({ row }) => <NodeCell deployment={row.original} /> },
  ...benchmarkColumns<QosBenchmarkDeploymentLevel>(),
  ...metricColumns<QosBenchmarkDeploymentLevel>(),
];

export const levelColumns: ColumnDef<QosBenchmarkLevel>[] = [
  {
    id: "concurrency",
    header: "Concurrency",
    cell: ({ row }) => <span className="font-medium">{row.original.concurrency}</span>,
  },
  ...benchmarkColumns<QosBenchmarkLevel>(),
  ...metricColumns<QosBenchmarkLevel>(),
];
