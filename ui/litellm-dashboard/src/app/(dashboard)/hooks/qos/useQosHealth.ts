import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import { qosWindow, type QosHealthResponse, type QosRange } from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

const healthKeys = createQueryKeys("qosHealth");

export const useQosHealth = (accessToken: string | null, range: QosRange): UseQueryResult<QosHealthResponse> => {
  const options = {
    queryKey: healthKeys.list({ filters: { range } }),
    queryFn: () => apiClient.get<QosHealthResponse>("/qos/health", { accessToken, query: qosWindow(range, new Date()) }),
    enabled: Boolean(accessToken),
    retry: false,
  };
  return useQuery<QosHealthResponse>(options);
};
