"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";

import { useQosHealth } from "@/app/(dashboard)/hooks/qos/useQosHealth";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { extractErrorMessage } from "@/utils/errorUtils";
import {
  formatPercentiles,
  formatRatio,
  isQosRange,
  QOS_RANGES,
  type QosHealthNode,
  type QosHealthProbe,
  type QosRange,
} from "./qosData";

const formatTime = (value: string | null | undefined): string =>
  value === null || value === undefined ? "-" : new Date(value).toLocaleString();

const nodeColumns: ColumnDef<QosHealthNode>[] = [
  { id: "model_name", header: "Model", cell: ({ row }) => <span className="font-medium">{row.original.model_name}</span> },
  {
    id: "node",
    header: "Node",
    cell: ({ row }) => (
      <div className="min-w-0">
        <p className="truncate font-mono text-xs">{row.original.api_base}</p>
        <p className="truncate text-xs text-muted-foreground">{row.original.upstream_model}</p>
      </div>
    ),
  },
  {
    id: "latest_status",
    header: "Latest status",
    cell: ({ row }) =>
      row.original.latest_status === "healthy" ? (
        <Badge variant="secondary">Healthy</Badge>
      ) : (
        <Badge variant="destructive">Unhealthy</Badge>
      ),
  },
  { id: "availability", header: "Availability", cell: ({ row }) => formatRatio(row.original.availability) },
  { id: "checks", header: "Checks recorded", cell: ({ row }) => row.original.checks },
  { id: "failures", header: "Failures", cell: ({ row }) => row.original.failures },
  {
    id: "last_error",
    header: "Last error",
    cell: ({ row }) =>
      row.original.last_error === null ? (
        "-"
      ) : (
        <div className="max-w-xs">
          <p className="truncate text-xs text-destructive" title={row.original.last_error}>
            {row.original.last_error}
          </p>
          <p className="text-xs text-muted-foreground">{formatTime(row.original.last_failure_at)}</p>
        </div>
      ),
  },
  { id: "last_checked_at", header: "Last checked", cell: ({ row }) => formatTime(row.original.last_checked_at) },
];

const probeColumns: ColumnDef<QosHealthProbe>[] = [
  {
    id: "node",
    header: "Node",
    cell: ({ row }) => (
      <div className="min-w-0">
        <p className="truncate font-mono text-xs">{row.original.api_base}</p>
        <p className="truncate text-xs text-muted-foreground">{row.original.model}</p>
      </div>
    ),
  },
  { id: "probes", header: "Probes", cell: ({ row }) => row.original.probes },
  { id: "latency", header: "Latency P50 / P95", cell: ({ row }) => formatPercentiles(row.original.latency_ms) },
  { id: "last_probe_at", header: "Last probe", cell: ({ row }) => formatTime(row.original.last_probe_at) },
];

export default function QosHealthPanel({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("24h");
  const healthQuery = useQosHealth(accessToken, range);
  const health = healthQuery.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="qos-health-range" className="text-sm text-muted-foreground">
            Time range
          </label>
          <Select
            items={QOS_RANGES}
            value={range}
            onValueChange={(value: string | null) => {
              if (value !== null && isQosRange(value)) setRange(value);
            }}
          >
            <SelectTrigger id="qos-health-range" className="w-44">
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
        <Button variant="outline" disabled={healthQuery.isFetching} onClick={() => void healthQuery.refetch()}>
          <RefreshCw className={`size-4 ${healthQuery.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {healthQuery.error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load health check history</AlertTitle>
          <AlertDescription>{extractErrorMessage(healthQuery.error)}</AlertDescription>
        </Alert>
      )}

      <section className="flex flex-col gap-2">
        <h3 className="text-base font-semibold">Node availability</h3>
        <p className="text-sm text-muted-foreground">
          Results of the gateway&apos;s background health checks, saved once per save window, including failures and
          their errors.
        </p>
        <DataTable
          data={health === undefined ? [] : [...health.nodes]}
          columns={nodeColumns}
          getRowId={(node) => `${node.model_name}:${node.model_id}`}
          isLoading={healthQuery.isLoading}
          noDataMessage="No health checks in this time range"
        />
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-base font-semibold">Health check latency</h3>
        <p className="text-sm text-muted-foreground">
          End-to-end latency of every successful health check request sent to each node.
        </p>
        <DataTable
          data={health === undefined ? [] : [...health.probes]}
          columns={probeColumns}
          getRowId={(probe) => `${probe.api_base}:${probe.model}`}
          isLoading={healthQuery.isLoading}
          noDataMessage="No health check requests in this time range"
        />
      </section>
    </div>
  );
}
