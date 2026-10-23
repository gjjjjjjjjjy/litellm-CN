"use client";

import React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Play, Trash2 } from "lucide-react";

import {
  useDeleteQosBenchmark,
  useQosBenchmarkDetail,
  useQosBenchmarkRuns,
} from "@/app/(dashboard)/hooks/qos/useQosBenchmarks";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import { DataTable } from "@/components/shared/DataTable";
import { Meter, MeterIndicator, MeterTrack } from "@/components/shared/Meter";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { extractErrorMessage } from "@/utils/errorUtils";
import { isProxyAdminRole } from "@/utils/roles";
import { deploymentColumns, deploymentLevelColumns, levelColumns } from "./QosColumns";
import {
  comparesProviders,
  formatRatio,
  recordedRequests,
  type QosBenchmarkDetail,
  type QosBenchmarkRun,
  type QosBenchmarkStarted,
} from "./qosData";

const runSuccessRate = (run: QosBenchmarkRun): number | null =>
  run.requests === 0 ? null : (run.requests - run.failed_requests) / run.requests;

const runColumns: ColumnDef<QosBenchmarkRun>[] = [
  { id: "started_at", header: "Started", cell: ({ row }) => new Date(row.original.started_at).toLocaleString() },
  {
    id: "model_group",
    header: "Model",
    cell: ({ row }) => <span className="font-medium">{row.original.model_group}</span>,
  },
  { id: "requests", header: "Requests", cell: ({ row }) => row.original.requests },
  { id: "success_rate", header: "Success rate", cell: ({ row }) => formatRatio(runSuccessRate(row.original)) },
  {
    id: "run_id",
    header: "Run ID",
    cell: ({ row }) => <span className="font-mono text-xs text-muted-foreground">{row.original.run_id}</span>,
  },
];

const deleteColumn = (
  onDelete: (run: QosBenchmarkRun) => void,
  runningRunId: string | null,
): ColumnDef<QosBenchmarkRun> => ({
  id: "actions",
  header: "",
  cell: ({ row }) => (
    <Button
      variant="ghost"
      size="icon"
      className="size-7 text-muted-foreground hover:text-destructive"
      aria-label="Delete test record"
      disabled={row.original.run_id === runningRunId}
      onClick={(event) => {
        event.stopPropagation();
        onDelete(row.original);
      }}
    >
      <Trash2 className="size-4" />
    </Button>
  ),
});

const RunProgress = ({ detail, total }: { detail: QosBenchmarkDetail | undefined; total: number }) => {
  const recorded = detail === undefined ? 0 : Math.min(recordedRequests(detail), total);
  const done = recorded >= total;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-sm">
        <span>{done ? "Test finished" : "Test running"}</span>
        <span className="tabular-nums text-muted-foreground">{`${recorded} / ${total}`}</span>
      </div>
      <Meter value={(recorded / total) * 100} aria-label="Benchmark progress">
        <MeterTrack>
          <MeterIndicator />
        </MeterTrack>
      </Meter>
    </div>
  );
};

interface BenchmarksPanelProps {
  readonly accessToken: string | null;
  readonly activeRun: QosBenchmarkStarted | null;
  readonly selectedRunId: string | null;
  readonly onSelectRun: (runId: string | null) => void;
  readonly onStartClick: () => void;
}

export default function BenchmarksPanel({
  accessToken,
  activeRun,
  selectedRunId,
  onSelectRun,
  onStartClick,
}: BenchmarksPanelProps) {
  const { userRole, isViewOnly } = useAuthorized();
  const canManage = isProxyAdminRole(userRole) && !isViewOnly;
  const expectedTotal = activeRun !== null && activeRun.run_id === selectedRunId ? activeRun.total_requests : null;
  const detailQuery = useQosBenchmarkDetail(accessToken, selectedRunId, expectedTotal);
  const detail = detailQuery.data;
  const running = expectedTotal !== null && (detail === undefined || recordedRequests(detail) < expectedTotal);
  const runsQuery = useQosBenchmarkRuns(accessToken, running);
  const deleteRun = useDeleteQosBenchmark(accessToken);
  const [pendingDelete, setPendingDelete] = React.useState<QosBenchmarkRun | null>(null);
  const error = runsQuery.error ?? detailQuery.error ?? deleteRun.error;
  const runningRunId = running && activeRun !== null ? activeRun.run_id : null;
  const columns = React.useMemo(
    () => (canManage ? [...runColumns, deleteColumn(setPendingDelete, runningRunId)] : runColumns),
    [canManage, runningRunId],
  );

  const confirmDelete = (run: QosBenchmarkRun) => {
    deleteRun.mutate(run.run_id, {
      onSuccess: () => {
        if (run.run_id === selectedRunId) onSelectRun(null);
      },
      onSettled: () => setPendingDelete(null),
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Each test is tagged so its requests can be told apart from other traffic. Results come from the gateway
          request logs and appear a few seconds after the requests finish.
        </p>
        {canManage && (
          <Button onClick={onStartClick}>
            <Play className="size-4" />
            Start test
          </Button>
        )}
      </div>

      {error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Could not load benchmark results</AlertTitle>
          <AlertDescription>{extractErrorMessage(error)}</AlertDescription>
        </Alert>
      )}

      <DataTable
        data={runsQuery.data === undefined ? [] : runsQuery.data}
        columns={columns}
        getRowId={(run) => run.run_id}
        isLoading={runsQuery.isLoading}
        noDataMessage="No benchmark runs in the last 7 days"
        onRowClick={(run) => onSelectRun(run.run_id)}
        rowClassName={(row) => (row.original.run_id === selectedRunId ? "bg-muted" : "")}
      />

      {selectedRunId !== null && (
        <Card>
          <CardHeader>
            <CardTitle className="font-mono text-base">{selectedRunId}</CardTitle>
            <CardDescription>Results per concurrency level and per node for this run</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {expectedTotal !== null && <RunProgress detail={detail} total={expectedTotal} />}
            {detail !== undefined && comparesProviders(detail) ? (
              <div className="flex flex-col gap-2">
                <h3 className="text-base font-semibold">Provider comparison</h3>
                <DataTable
                  data={[...detail.deployment_levels]}
                  columns={deploymentLevelColumns}
                  getRowId={(level) => `${level.concurrency}-${level.model_id}`}
                  noDataMessage="No requests recorded for this run yet"
                />
              </div>
            ) : (
              <DataTable
                data={detail === undefined ? [] : [...detail.levels]}
                columns={levelColumns}
                getRowId={(level) => String(level.concurrency)}
                isLoading={detailQuery.isLoading}
                noDataMessage="No requests recorded for this run yet"
              />
            )}
            <DataTable
              data={detail === undefined ? [] : [...detail.deployments]}
              columns={deploymentColumns}
              getRowId={(deployment) => deployment.model_id}
              size="compact"
              noDataMessage="No node results yet"
            />
          </CardContent>
        </Card>
      )}

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        {pendingDelete !== null && (
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete this test record?</AlertDialogTitle>
              <AlertDialogDescription>
                {`This permanently deletes the ${pendingDelete.requests} request logs recorded for ${pendingDelete.run_id}. Usage totals and spend already counted do not change.`}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                disabled={deleteRun.isPending}
                onClick={() => confirmDelete(pendingDelete)}
              >
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        )}
      </AlertDialog>
    </div>
  );
}
