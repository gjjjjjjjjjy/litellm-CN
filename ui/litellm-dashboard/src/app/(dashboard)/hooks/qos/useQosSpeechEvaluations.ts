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
  speechPollMs,
  type QosRange,
  type QosSpeechEvaluationOptions,
  type QosSpeechEvaluationsResponse,
  type QosSpeechEvaluationStarted,
  type QosSpeechReview,
} from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

export const speechEvaluationKeys = createQueryKeys("qosSpeechEvaluations");

export const useQosSpeechEvaluations = (
  accessToken: string | null,
  range: QosRange,
  evaluationStartedAt: number | null,
): UseQueryResult<QosSpeechEvaluationsResponse> => {
  const options = {
    queryKey: speechEvaluationKeys.list({ filters: { range } }),
    queryFn: () =>
      apiClient.get<QosSpeechEvaluationsResponse>("/qos/speech/evaluations", {
        accessToken,
        query: qosWindow(range, new Date()),
      }),
    enabled: Boolean(accessToken),
    ...qosRefreshOptions(range, false),
    refetchInterval: () => speechPollMs(evaluationStartedAt, Date.now()),
    retry: false,
  };
  return useQuery<QosSpeechEvaluationsResponse>(options);
};

export const useSpeechEvaluationOptions = (
  accessToken: string | null,
  enabled: boolean,
): UseQueryResult<QosSpeechEvaluationOptions> => {
  const options = {
    queryKey: speechEvaluationKeys.detail("evaluation-options"),
    queryFn: () => apiClient.get<QosSpeechEvaluationOptions>("/qos/speech/evaluations/options", { accessToken }),
    enabled: Boolean(accessToken) && enabled,
    retry: false,
  };
  return useQuery<QosSpeechEvaluationOptions>(options);
};

export const useStartSpeechEvaluation = (
  accessToken: string | null,
): UseMutationResult<QosSpeechEvaluationStarted, Error, void> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.post<QosSpeechEvaluationStarted>("/qos/speech/evaluations", { accessToken }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: speechEvaluationKeys.all }),
  });
};

export interface SaveSpeechReview {
  readonly requestId: string;
  readonly overall: number;
}

export const useSaveSpeechReview = (
  accessToken: string | null,
): UseMutationResult<QosSpeechReview, Error, SaveSpeechReview> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, overall }: SaveSpeechReview) =>
      apiClient.put<QosSpeechReview>("/qos/speech/review", {
        accessToken,
        query: { request_id: requestId },
        body: { overall },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: speechEvaluationKeys.all }),
  });
};

export const fetchSpeechAudio = (accessToken: string | null, requestId: string): Promise<Blob> =>
  apiClient.getBlob("/qos/speech/audio", { accessToken, query: { request_id: requestId } });

export const fetchSpeechRecording = (accessToken: string | null): Promise<Blob> =>
  apiClient.getBlob("/qos/speech/recording", { accessToken });
