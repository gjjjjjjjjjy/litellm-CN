"use client";

import React from "react";
import { RefreshCw } from "lucide-react";

import { useQosSummary } from "@/app/(dashboard)/hooks/qos/useQosSummary";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { extractErrorMessage } from "@/utils/errorUtils";
import { deploymentColumns, groupColumns } from "./QosColumns";
import { deploymentsFor, isQosRange, QOS_RANGES, type QosRange } from "./qosData";
import QosDashboard from "./QosDashboard";

const AUTO_REFRESH_MS = 60_000;

export default function QosOverview({ accessToken }: { accessToken: string | null }) {
  const [range, setRange] = React.useState<QosRange>("1h");
  const [tagInput, setTagInput] = React.useState("");
  const [tag, setTag] = React.useState("");
  const [autoRefresh, setAutoRefresh] = React.useState(true);
  const refreshMs = autoRefresh ? AUTO_REFRESH_MS : false;
  const summaryQuery = useQosSummary(accessToken, range, tag, refreshMs);
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
    <div className="flex flex-col gap-6">
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
        <label htmlFor="qos-auto-refresh" className="flex h-9 items-center gap-2 text-sm text-muted-foreground">
          <Switch id="qos-auto-refresh" checked={autoRefresh} onCheckedChange={setAutoRefresh} />
          Auto refresh every minute
        </label>
      </form>

      {error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load service quality metrics</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <QosDashboard accessToken={accessToken} range={range} tag={tag} summary={summary} refreshMs={refreshMs} />

      <h2 className="text-base font-semibold">Details</h2>
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
    </div>
  );
}
