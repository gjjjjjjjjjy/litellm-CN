import {
  useMutation,
  useQuery,
  useQueryClient,
  type Query,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import {
  qosRefreshOptions,
  qosWindow,
  reviewPollMs,
  type QosRange,
  type QosVideoEvaluationOptions,
  type QosVideoEvaluationPrompt,
  type QosVideoEvaluationStarted,
  type QosVideoReview,
  type QosVideoReviewInput,
  type QosVideoReviewsResponse,
} from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

export const videoReviewKeys = createQueryKeys("qosVideoReviews");

export const useQosVideoReviews = (
  accessToken: string | null,
  range: QosRange,
  evaluationStartedAt: number | null,
): UseQueryResult<QosVideoReviewsResponse> => {
  const options = {
    queryKey: videoReviewKeys.list({ filters: { range } }),
    queryFn: () =>
      apiClient.get<QosVideoReviewsResponse>("/qos/videos", { accessToken, query: qosWindow(range, new Date()) }),
    enabled: Boolean(accessToken),
    ...qosRefreshOptions(range, false),
    refetchInterval: (query: Query<QosVideoReviewsResponse>) =>
      reviewPollMs(query.state.data?.videos ?? [], evaluationStartedAt, Date.now()),
    retry: false,
  };
  return useQuery<QosVideoReviewsResponse>(options);
};

export const useVideoEvaluationOptions = (
  accessToken: string | null,
  enabled: boolean,
): UseQueryResult<QosVideoEvaluationOptions> => {
  const options = {
    queryKey: videoReviewKeys.detail("evaluation-options"),
    queryFn: () => apiClient.get<QosVideoEvaluationOptions>("/qos/videos/evaluations/options", { accessToken }),
    enabled: Boolean(accessToken) && enabled,
    retry: false,
  };
  return useQuery<QosVideoEvaluationOptions>(options);
};

export const useWriteEvaluationPrompt = (
  accessToken: string | null,
): UseMutationResult<QosVideoEvaluationPrompt, Error, void> =>
  useMutation({
    mutationFn: () => apiClient.post<QosVideoEvaluationPrompt>("/qos/videos/evaluations/prompt", { accessToken }),
  });

export const useStartVideoEvaluation = (
  accessToken: string | null,
): UseMutationResult<QosVideoEvaluationStarted, Error, string> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (prompt: string) =>
      apiClient.post<QosVideoEvaluationStarted>("/qos/videos/evaluations", { accessToken, body: { prompt } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: videoReviewKeys.all }),
  });
};

export interface SaveVideoReview {
  readonly videoId: string;
  readonly review: QosVideoReviewInput;
}

export const useSaveVideoReview = (
  accessToken: string | null,
): UseMutationResult<QosVideoReview, Error, SaveVideoReview> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ videoId, review }: SaveVideoReview) =>
      apiClient.put<QosVideoReview>("/qos/videos/review", { accessToken, query: { video_id: videoId }, body: review }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: videoReviewKeys.all }),
  });
};

export const fetchVideoContent = (accessToken: string | null, videoId: string): Promise<Blob> =>
  apiClient.getBlob("/qos/videos/content", { accessToken, query: { video_id: videoId } });
