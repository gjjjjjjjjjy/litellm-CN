import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { apiClient } from "@/components/networking";
import type { components } from "@/lib/http/schema";
import { createQueryKeys } from "../common/queryKeysFactory";

export type QosNews = components["schemas"]["QosNewsResponse"];
export type QosNewsItem = components["schemas"]["QosNewsItem"];
export type QosAnnouncement = components["schemas"]["QosAnnouncement"];
export type QosAnnouncementCreate = components["schemas"]["QosAnnouncementCreate"];
export type QosActivity = components["schemas"]["QosActivityResponse"];
export type QosActivityEvent = QosActivity["events"][number];

const homeKeys = createQueryKeys("qosHome");
const NEWS_REFRESH_MS = 10 * 60_000;

export const useQosNews = (accessToken: string | null): UseQueryResult<QosNews> => {
  const options = {
    queryKey: [...homeKeys.all, "news"],
    queryFn: () => apiClient.get<QosNews>("/qos/home/news", { accessToken }),
    enabled: Boolean(accessToken),
    refetchInterval: NEWS_REFRESH_MS,
    retry: false,
  };
  return useQuery<QosNews>(options);
};

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

const announcementKey = [...homeKeys.all, "announcements"];

export const useQosAnnouncements = (accessToken: string | null): UseQueryResult<QosAnnouncement[]> => {
  const options = {
    queryKey: announcementKey,
    queryFn: async () =>
      (await apiClient.get<{ announcements: QosAnnouncement[] }>("/qos/announcements", { accessToken })).announcements,
    enabled: Boolean(accessToken),
    retry: false,
  };
  return useQuery<QosAnnouncement[]>(options);
};

export const usePostAnnouncement = (accessToken: string | null) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: QosAnnouncementCreate) =>
      apiClient.post<{ announcements: QosAnnouncement[] }>("/qos/announcements", { accessToken, body: draft }),
    onSuccess: (response) => queryClient.setQueryData(announcementKey, response.announcements),
  });
};

export const useDeleteAnnouncement = (accessToken: string | null) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (announcementId: string) =>
      apiClient.delete<{ announcements: QosAnnouncement[] }>(
        `/qos/announcements/${encodeURIComponent(announcementId)}`,
        { accessToken },
      ),
    onSuccess: (response) => queryClient.setQueryData(announcementKey, response.announcements),
  });
};
