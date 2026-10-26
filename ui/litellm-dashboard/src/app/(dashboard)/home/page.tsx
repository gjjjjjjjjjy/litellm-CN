"use client";

import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import QosView from "@/app/(dashboard)/qos/_components/QosView";
import LoadingScreen from "@/components/common_components/LoadingScreen";

export default function HomeRoutePage() {
  const { isLoading, isAuthorized, accessToken } = useAuthorized();
  if (isLoading || !isAuthorized) {
    return <LoadingScreen />;
  }
  return <QosView accessToken={accessToken} />;
}
