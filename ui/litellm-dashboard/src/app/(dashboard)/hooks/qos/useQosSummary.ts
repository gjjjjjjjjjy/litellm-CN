import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import { qosWindow, type QosRange, type QosSummary } from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

const qosKeys = createQueryKeys("qos");

export const useQosSummary = (
  accessToken: string | null,
  range: QosRange,
  tag: string,
  refreshMs: number | false,
): UseQueryResult<QosSummary> => {
  const options = {
    queryKey: qosKeys.list({ filters: { range, tag } }),
    queryFn: () =>
      apiClient.get<QosSummary>("/qos/summary", {
        accessToken,
        query: { ...qosWindow(range, new Date()), tag: tag === "" ? undefined : tag },
      }),
    enabled: Boolean(accessToken),
    refetchInterval: refreshMs,
    retry: false,
  };
  return useQuery<QosSummary>(options);
};
