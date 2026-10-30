import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import type { components } from "@/lib/http/schema";
import { createQueryKeys } from "../common/queryKeysFactory";

export type QosActivity = components["schemas"]["QosActivityResponse"];
export type QosActivityEvent = QosActivity["events"][number];

const homeKeys = createQueryKeys("qosHome");
export const useQosActivity = (accessToken: string | null, refreshMs: number | false): UseQueryResult<QosActivity> => {
  const options = {
    queryKey: [...homeKeys.all, "activity"],
    queryFn: () => apiClient.get<QosActivity>("/qos/home/activity", { accessToken, query: { days: 7 } }),
    enabled: Boolean(accessToken),
    refetchInterval: refreshMs,
    retry: false,
  };
  return useQuery<QosActivity>(options);
};
