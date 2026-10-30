import { useMutation, useQuery, useQueryClient, type Query, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import {
  recordedRequests,
  type QosBenchmarkDeleted,
  type QosBenchmarkDetail,
  type QosBenchmarkRequest,
  type QosBenchmarkRequests,
  type QosBenchmarkRun,
  type QosBenchmarkStarted,
  type QosTargetModel,
} from "@/app/(dashboard)/qos/_components/qosData";
import type { BenchmarkExport } from "@/app/(dashboard)/qos/_components/benchmarkCsv";
import { createQueryKeys } from "../common/queryKeysFactory";

const benchmarkKeys = createQueryKeys("qosBenchmarks");
const POLL_MS = 3000;

const fetchBenchmarkDetail = (accessToken: string | null, runId: string): Promise<QosBenchmarkDetail> =>
  apiClient.get<QosBenchmarkDetail>(`/qos/benchmarks/${encodeURIComponent(runId)}`, { accessToken });

export const useQosBenchmarkRuns = (
  accessToken: string | null,
  polling: boolean,
): UseQueryResult<QosBenchmarkRun[]> => {
  const options = {
    queryKey: benchmarkKeys.lists(),
    queryFn: async () => (await apiClient.get<{ runs: QosBenchmarkRun[] }>("/qos/benchmarks", { accessToken })).runs,
    enabled: Boolean(accessToken),
    refetchInterval: polling ? POLL_MS : false,
    retry: false,
  } as const;
  return useQuery<QosBenchmarkRun[]>(options);
};

export const useQosBenchmarkDetail = (
  accessToken: string | null,
  runId: string | null,
  expectedTotal: number | null,
): UseQueryResult<QosBenchmarkDetail> => {
  const options = {
    queryKey: [...benchmarkKeys.details(), runId],
    queryFn: () => {
      if (runId === null) throw new Error("No benchmark run selected");
      return fetchBenchmarkDetail(accessToken, runId);
    },
    enabled: Boolean(accessToken) && runId !== null,
    refetchInterval: (query: Query<QosBenchmarkDetail>) => {
      if (expectedTotal === null) return false;
      const detail = query.state.data;
      return detail === undefined || recordedRequests(detail) < expectedTotal ? POLL_MS : false;
    },
    retry: false,
  } as const;
  return useQuery<QosBenchmarkDetail>(options);
};

export const useQosBenchmarkRequests = (
  accessToken: string | null,
  runId: string,
  page: number,
  pageSize: number,
): UseQueryResult<QosBenchmarkRequests> => {
  const options = {
    queryKey: [...benchmarkKeys.detail(runId), "requests", page, pageSize],
    queryFn: () =>
      apiClient.get<QosBenchmarkRequests>(`/qos/benchmarks/${encodeURIComponent(runId)}/requests`, {
        accessToken,
        query: { page, page_size: pageSize },
      }),
    enabled: Boolean(accessToken),
    staleTime: Infinity,
    retry: false,
  };
  return useQuery<QosBenchmarkRequests>(options);
};

export const useQosTargets = (
  accessToken: string | null,
  refreshMs: number | false = false,
): UseQueryResult<QosTargetModel[]> => {
  const options = {
    queryKey: [...benchmarkKeys.all, "targets"],
    queryFn: async () => (await apiClient.get<{ models: QosTargetModel[] }>("/qos/targets", { accessToken })).models,
    enabled: Boolean(accessToken),
    refetchInterval: refreshMs,
    retry: false,
  } as const;
  return useQuery<QosTargetModel[]>(options);
};

export const useStartQosBenchmark = (accessToken: string | null) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (plan: QosBenchmarkRequest) =>
      apiClient.post<QosBenchmarkStarted>("/qos/benchmarks", { accessToken, body: plan }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarkKeys.lists() }),
  });
};

export const useDeleteQosBenchmark = (accessToken: string | null) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiClient.delete<QosBenchmarkDeleted>(`/qos/benchmarks/${encodeURIComponent(runId)}`, { accessToken }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarkKeys.all }),
  });
};

export const useExportQosBenchmarks = (accessToken: string | null) =>
  useMutation({
    mutationFn: (runs: readonly QosBenchmarkRun[]): Promise<BenchmarkExport[]> =>
      runs.reduce<Promise<BenchmarkExport[]>>(async (pending, run) => {
        const exported = await pending;
        const detail = await fetchBenchmarkDetail(accessToken, run.run_id);
        if (detail.deployment_levels.length === 0) {
          throw new Error(`Test ${run.run_id} has no recorded results. Refresh the list before exporting.`);
        }
        return [...exported, { run, detail }];
      }, Promise.resolve([])),
  });
