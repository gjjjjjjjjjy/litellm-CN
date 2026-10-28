import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import type { QosTrends, TrendGrouping } from "@/app/(dashboard)/qos/_components/dashboardData";
import { qosRefreshOptions, qosWindow, type QosRange } from "@/app/(dashboard)/qos/_components/qosData";
import { createQueryKeys } from "../common/queryKeysFactory";

export const trendKeys = createQueryKeys("qosTrends");

export interface QosTrendsQuery {
  readonly range: QosRange;
  readonly tag: string;
  readonly groupBy: TrendGrouping;
  readonly refreshMs: number | false;
}

export const useQosTrends = (
  accessToken: string | null,
  { range, tag, groupBy, refreshMs }: QosTrendsQuery,
): UseQueryResult<QosTrends> => {
  const options = {
    queryKey: trendKeys.list({ filters: { range, tag, groupBy } }),
    queryFn: () =>
      apiClient.get<QosTrends>("/qos/trends", {
        accessToken,
        query: { ...qosWindow(range, new Date()), tag: tag === "" ? undefined : tag, group_by: groupBy },
      }),
    enabled: Boolean(accessToken),
    ...qosRefreshOptions(range, refreshMs),
    retry: false,
  };
  return useQuery<QosTrends>(options);
};
