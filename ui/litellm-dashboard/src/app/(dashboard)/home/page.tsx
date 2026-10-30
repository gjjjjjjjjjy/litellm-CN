"use client";

import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import HomeBoard from "@/app/(dashboard)/qos/_components/home/HomeBoard";
import LoadingScreen from "@/components/common_components/LoadingScreen";
import { isProxyAdminRole } from "@/utils/roles";

export default function HomeRoutePage() {
  const { isLoading, isAuthorized, accessToken, userRole } = useAuthorized();
  if (isLoading || !isAuthorized) {
    return <LoadingScreen />;
  }
  return <HomeBoard accessToken={accessToken} canCheckHealth={isProxyAdminRole(userRole)} />;
}
