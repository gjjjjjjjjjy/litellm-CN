import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import {
  qosRefreshOptions,
  qosWindow,
  type QosRange,
  type QosVideoReview,
  type QosVideoReviewInput,
  type QosVideoReviewsResponse,
} from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

export const videoReviewKeys = createQueryKeys("qosVideoReviews");

export const useQosVideoReviews = (
  accessToken: string | null,
  range: QosRange,
): UseQueryResult<QosVideoReviewsResponse> => {
  const options = {
    queryKey: videoReviewKeys.list({ filters: { range } }),
    queryFn: () =>
      apiClient.get<QosVideoReviewsResponse>("/qos/videos", { accessToken, query: qosWindow(range, new Date()) }),
    enabled: Boolean(accessToken),
    ...qosRefreshOptions(range, false),
    retry: false,
  };
  return useQuery<QosVideoReviewsResponse>(options);
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
