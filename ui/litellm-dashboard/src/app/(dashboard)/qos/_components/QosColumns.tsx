"use client";

import type { ColumnDef, Row } from "@tanstack/react-table";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  formatPercentiles,
  formatRate,
  formatRatio,
  nodeLabel,
  successRate,
  type QosBenchmarkDeploymentLevel,
  type QosBenchmarkLevel,
  type QosDeploymentMetrics,
  type QosModelGroupMetrics,
} from "./qosData";

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
    <p className="truncate font-mono text-xs">{nodeLabel(deployment)}</p>
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
  ...metricColumns<QosBenchmarkDeploymentLevel>(),
];

export const levelColumns: ColumnDef<QosBenchmarkLevel>[] = [
  {
    id: "concurrency",
    header: "Concurrency",
    cell: ({ row }) => <span className="font-medium">{row.original.concurrency}</span>,
  },
  ...metricColumns<QosBenchmarkLevel>(),
];
