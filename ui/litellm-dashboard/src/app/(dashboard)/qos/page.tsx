"use client";

import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import QosView from "./_components/QosView";

export default function QosPage() {
  const { accessToken } = useAuthorized();
  return <QosView accessToken={accessToken} />;
}
