import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import type { ImageConfig, ImageHomeSummary, ImagePlan, ImageRatingInput, ImageRun } from "@/app/(dashboard)/qos/_components/imagePrompts";
import type { QosRange } from "@/app/(dashboard)/qos/_components/qosData";

const key = ["qosImages"] as const;

export const useImageHomeSummary = (accessToken: string | null) =>
  useQuery({
    queryKey: [...key, "homeSummary"],
    queryFn: () => apiClient.get<ImageHomeSummary>("/qos/images/home-summary", { accessToken }),
    enabled: Boolean(accessToken),
    refetchInterval: 60_000,
  });

export const useImageConfig = (accessToken: string | null) =>
  useQuery({
    queryKey: [...key, "config"],
    queryFn: () => apiClient.get<ImageConfig>("/qos/images/config", { accessToken }),
    enabled: Boolean(accessToken),
  });

export const useImageRuns = (accessToken: string | null, range: QosRange | "all") =>
  useQuery({
    queryKey: [...key, "runs", range],
    queryFn: () => apiClient.get<ImageRun[]>(
      range === "all" ? "/qos/images/runs" : `/qos/images/runs?range=${encodeURIComponent(range)}`,
      { accessToken },
    ),
    enabled: Boolean(accessToken),
    refetchInterval: 3000,
  });

export const useImageRun = (accessToken: string | null, runId: string | null) =>
  useQuery({
    queryKey: [...key, "run", runId],
    queryFn: () => apiClient.get<ImageRun>(`/qos/images/runs/${encodeURIComponent(runId!)}`, { accessToken }),
    enabled: Boolean(accessToken && runId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 3000 : false),
  });

export const useStartImageRun = (accessToken: string | null) => {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (plan: ImagePlan) => apiClient.post<ImageRun>("/qos/images/runs", { accessToken, body: plan }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: key }),
  });
};

export const useRateImage = (accessToken: string | null, runId: string) => {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, rating }: { itemId: string; rating: ImageRatingInput }) =>
      apiClient.put<ImageRun>(`/qos/images/runs/${encodeURIComponent(runId)}/items/${itemId}/rating`, {
        accessToken,
        body: rating,
      }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: [...key, "run", runId] }),
  });
};
