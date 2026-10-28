"use client";

import React from "react";
import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";

import { useQosBenchmarkRequests } from "@/app/(dashboard)/hooks/qos/useQosBenchmarks";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import { DataTable } from "@/components/shared/DataTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { extractErrorMessage } from "@/utils/errorUtils";
import { isProxyAdminTierRole } from "@/utils/roles";
import type { QosBenchmarkExchange, QosBenchmarkRequestLog } from "./qosData";
import VendorName from "./VendorName";

const exchangeTextClass = "max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 text-sm";

const Exchange = ({ exchange }: { exchange: QosBenchmarkExchange | null }) => {
  if (exchange === null) {
    return <p className="text-sm text-muted-foreground">This request has no saved question or answer.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 @min-[60rem]:grid-cols-2">
        <section className="min-w-0">
          <h4 className="mb-2 text-sm font-medium">Question sent</h4>
          <pre className={exchangeTextClass}>{exchange.question}</pre>
        </section>
        {exchange.answer !== null && (
          <section className="min-w-0">
            <h4 className="mb-2 text-sm font-medium">Answer received</h4>
            {exchange.answer === "" ? (
              <p className="text-sm text-muted-foreground">The model returned an empty answer.</p>
            ) : (
              <pre className={exchangeTextClass}>{exchange.answer}</pre>
            )}
          </section>
        )}
      </div>
      {exchange.reasoning !== null && exchange.reasoning !== "" && (
        <details>
          <summary className="cursor-pointer text-sm font-medium">Reasoning</summary>
          <pre className={`${exchangeTextClass} mt-2`}>{exchange.reasoning}</pre>
        </details>
      )}
      {exchange.error !== null && (
        <Alert variant="destructive">
          <AlertDescription>
            <pre className="whitespace-pre-wrap break-words">{exchange.error}</pre>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
};

const CheckLabel = ({ check }: { check: QosBenchmarkRequestLog["response_check"] }): React.ReactElement => {
  switch (check) {
    case "passed":
      return <span>Passed</span>;
    case "crosstalk":
      return <span>Cross-talk</span>;
    case "marker_missing":
      return <span>Missing code</span>;
    case null:
      return <span>Not checked</span>;
  }
};

const StatusLabel = ({ status }: { status: string | null }) => {
  switch (status) {
    case "success":
      return <span>Success</span>;
    case "failure":
      return <span>Failed</span>;
    default:
      return <span>Unknown</span>;
  }
};

const columns: ColumnDef<QosBenchmarkRequestLog>[] = [
  {
    id: "details",
    header: "",
    cell: ({ row }) => (
      <Button variant="ghost" size="sm" aria-expanded={row.getIsExpanded()} onClick={() => row.toggleExpanded()}>
        {row.getIsExpanded() ? "Hide question and answer" : "View question and answer"}
      </Button>
    ),
  },
  { id: "started_at", header: "Started", cell: ({ row }) => new Date(row.original.started_at).toLocaleString() },
  {
    accessorKey: "concurrency",
    header: "Concurrency",
    cell: ({ row }) => (row.original.concurrency === null ? "-" : row.original.concurrency),
  },
  {
    id: "provider",
    header: "Provider",
    cell: ({ row }) => (
      <div className="max-w-xs">
        <VendorName vendor={row.original.vendor} />
        <p className="truncate text-xs text-muted-foreground" title={row.original.api_base}>
          {row.original.api_base}
        </p>
      </div>
    ),
  },
  {
    id: "status",
    header: "Status",
    cell: ({ row }) => <StatusLabel status={row.original.status} />,
  },
  { id: "check", header: "Response check", cell: ({ row }) => <CheckLabel check={row.original.response_check} /> },
  {
    accessorKey: "request_id",
    header: "Request ID",
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.request_id}</span>,
  },
];

function RequestList({ accessToken, runId }: { accessToken: string | null; runId: string }) {
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });
  const query = useQosBenchmarkRequests(accessToken, runId, pagination.pageIndex + 1, pagination.pageSize);
  const data = query.data;
  return (
    <section className="@container flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">Questions and answers</h3>
        <Button variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}>
          <RefreshCw className={`size-4 ${query.isFetching ? "animate-spin" : ""}`} />
          Refresh questions and answers
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Saved text appears after request logging finishes. Refresh to see newly completed requests.
      </p>
      {query.error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{extractErrorMessage(query.error)}</AlertDescription>
        </Alert>
      )}
      {query.isPending && <p className="text-sm text-muted-foreground">Loading questions and answers...</p>}
      {data !== undefined && (
        <DataTable
          data={[...data.requests]}
          columns={columns}
          getRowId={(row) => row.request_id}
          paginationMode="server"
          pagination={pagination}
          onPaginationChange={setPagination}
          rowCount={data.total}
          pageSizeOptions={[10, 25, 50]}
          isLoading={query.isFetching}
          getRowCanExpand={() => true}
          renderSubComponent={({ row }) => (
            <div className="sticky left-0 w-[100cqw] bg-muted/20 p-4 whitespace-normal">
              <Exchange exchange={row.original.exchange} />
            </div>
          )}
          noDataMessage="No requests recorded for this run yet"
        />
      )}
    </section>
  );
}

export default function BenchmarkRequests({ accessToken, runId }: { accessToken: string | null; runId: string }) {
  const { userRole } = useAuthorized();
  if (!isProxyAdminTierRole(userRole)) return null;
  return <RequestList accessToken={accessToken} runId={runId} />;
}
