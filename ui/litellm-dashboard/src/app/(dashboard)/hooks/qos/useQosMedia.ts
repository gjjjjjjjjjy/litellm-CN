import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import {
  qosRefreshOptions,
  qosWindow,
  type QosMediaResponse,
  type QosRange,
} from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

export const mediaKeys = createQueryKeys("qosMedia");

export const useQosMedia = (
  accessToken: string | null,
  range: QosRange,
  refreshMs: number | false,
): UseQueryResult<QosMediaResponse> => {
  const options = {
    queryKey: mediaKeys.list({ filters: { range } }),
    queryFn: () => apiClient.get<QosMediaResponse>("/qos/media", { accessToken, query: qosWindow(range, new Date()) }),
    enabled: Boolean(accessToken),
    ...qosRefreshOptions(range, refreshMs),
    retry: false,
  };
  return useQuery<QosMediaResponse>(options);
};
