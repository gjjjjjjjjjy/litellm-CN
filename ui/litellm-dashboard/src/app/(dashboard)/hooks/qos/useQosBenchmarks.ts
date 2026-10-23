import { useMutation, useQuery, useQueryClient, type Query, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import {
  recordedRequests,
  type QosBenchmarkDeleted,
  type QosBenchmarkDetail,
  type QosBenchmarkRequest,
  type QosBenchmarkRun,
  type QosBenchmarkStarted,
} from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

const benchmarkKeys = createQueryKeys("qosBenchmarks");
const POLL_MS = 3000;

export const useQosBenchmarkRuns = (accessToken: string | null, polling: boolean): UseQueryResult<QosBenchmarkRun[]> => {
  const options = {
    queryKey: benchmarkKeys.lists(),
    queryFn: async () =>
      (await apiClient.get<{ runs: QosBenchmarkRun[] }>("/qos/benchmarks", { accessToken })).runs,
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
      return apiClient.get<QosBenchmarkDetail>(`/qos/benchmarks/${encodeURIComponent(runId)}`, { accessToken });
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
