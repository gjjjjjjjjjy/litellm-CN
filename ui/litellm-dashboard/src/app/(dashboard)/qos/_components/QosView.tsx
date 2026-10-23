"use client";

import React from "react";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";

import { useQosSummary } from "@/app/(dashboard)/hooks/qos/useQosSummary";
import { DataTable } from "@/components/shared/DataTable";
import { Page } from "@/components/shared/Page";
import { PageHeader, PageHeaderDescription, PageHeaderTitle } from "@/components/shared/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import {
  deploymentsFor,
  formatPercentiles,
  formatRate,
  formatRatio,
  isQosRange,
  nodeLabel,
  QOS_RANGES,
  successRate,
  type QosDeploymentMetrics,
  type QosModelGroupMetrics,
  type QosRange,
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

const groupColumns: ColumnDef<QosModelGroupMetrics>[] = [
  { id: "expand", header: "", cell: ({ row }) => <ExpandToggle row={row} /> },
  { id: "model_group", header: "Model", cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span> },
  ...metricColumns<QosModelGroupMetrics>(),
];

const deploymentColumns: ColumnDef<QosDeploymentMetrics>[] = [
  {
    id: "node",
    header: "Node",
    cell: ({ row }) => (
      <div className="min-w-0">
        <p className="truncate font-mono text-xs">{nodeLabel(row.original)}</p>
        <p className="truncate text-xs text-muted-foreground">{row.original.model}</p>
      </div>
    ),
  },
  ...metricColumns<QosDeploymentMetrics>(),
];

export default function QosView({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("1h");
  const [tagInput, setTagInput] = React.useState("");
  const [tag, setTag] = React.useState("");
  const summaryQuery = useQosSummary(accessToken, range, tag);
  const summary = summaryQuery.data;
  const loading = summaryQuery.isFetching;
  const error = summaryQuery.error === null ? null : extractErrorMessage(summaryQuery.error);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextTag = tagInput.trim();
    if (nextTag === tag) {
      void summaryQuery.refetch();
      return;
    }
    setTag(nextTag);
  };

  return (
    <Page>
      <PageHeader>
        <PageHeaderTitle>Service Quality</PageHeaderTitle>
        <PageHeaderDescription>
          Concurrency, success rate, TTFT, TPOT and latency per model and per node, measured from gateway traffic.
          TTFT and TPOT come from streamed requests only; cache hits are excluded.
        </PageHeaderDescription>
      </PageHeader>

      <form className="flex flex-wrap items-end gap-3" onSubmit={handleSubmit}>
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-range" className="text-sm text-muted-foreground">
            Time range
          </label>
          <Select
            items={QOS_RANGES}
            value={range}
            onValueChange={(value: string | null) => {
              if (value !== null && isQosRange(value)) setRange(value);
            }}
          >
            <SelectTrigger id="qos-range" className="w-44">
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
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-tag" className="text-sm text-muted-foreground">
            Request tag
          </label>
          <Input
            id="qos-tag"
            className="w-64"
            value={tagInput}
            placeholder="e.g. qos-run-1"
            onChange={(event) => setTagInput(event.target.value)}
          />
        </div>
        <Button type="submit" variant="outline" disabled={loading}>
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </form>

      {error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load service quality metrics</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <DataTable
        data={summary === undefined ? [] : [...summary.model_groups]}
        columns={groupColumns}
        getRowId={(row) => row.model_group}
        isLoading={loading && summary === undefined}
        noDataMessage="No requests in this time range"
        getRowCanExpand={() => true}
        renderSubComponent={({ row }) => (
          <div className="bg-muted/30 p-3">
            <DataTable
              data={summary === undefined ? [] : deploymentsFor(summary, row.original.model_group)}
              columns={deploymentColumns}
              getRowId={(deployment) => `${deployment.model_group}:${deployment.model_id}`}
              size="compact"
            />
          </div>
        )}
      />
    </Page>
  );
}
