"use client";

import React from "react";
import { parseAsString, useQueryState } from "nuqs";

import { Page, PageTabs, PageTabsContent, PageTabsList, PageTabsTrigger } from "@/components/shared/Page";
import { PageHeader, PageHeaderDescription, PageHeaderTitle } from "@/components/shared/PageHeader";
import { useUrlTab } from "@/hooks/useUrlTab";
import BenchmarksPanel from "./BenchmarksPanel";
import QosHealthPanel from "./QosHealthPanel";
import QosOverview from "./QosOverview";
import { QOS_BENCHMARK_MODEL_PARAM, type QosBenchmarkStarted } from "./qosData";
import StartBenchmarkDialog from "./StartBenchmarkDialog";

const QOS_TABS = ["overview", "benchmarks", "health"] as const;
type QosTab = (typeof QOS_TABS)[number];
const isQosTab = (value: string): value is QosTab => QOS_TABS.some((tab) => tab === value);

export default function QosView({ accessToken }: { accessToken: string | null }) {
  const [tab, setTab] = useUrlTab(QOS_TABS, "overview");
  const [runId, setRunId] = useQueryState("run", parseAsString);
  const [linkedModel, setLinkedModel] = useQueryState(QOS_BENCHMARK_MODEL_PARAM, parseAsString);
  const [dialogModel, setDialogModel] = React.useState<string | null>(() => linkedModel);
  const [activeRun, setActiveRun] = React.useState<QosBenchmarkStarted | null>(null);

  React.useEffect(() => {
    if (linkedModel === null) return;
    setTab("benchmarks");
    void setLinkedModel(null);
  }, [linkedModel, setLinkedModel, setTab]);

  const handleStarted = (started: QosBenchmarkStarted) => {
    setActiveRun(started);
    setDialogModel(null);
    void setRunId(started.run_id);
  };

  return (
    <Page>
      <PageHeader>
        <PageHeaderTitle>Service Quality</PageHeaderTitle>
        <PageHeaderDescription>
          Concurrency, success rate, TTFT, TPOT and latency per model and per node, measured from gateway traffic. TTFT
          and TPOT come from streamed requests only; cache hits are excluded.
        </PageHeaderDescription>
      </PageHeader>

      <PageTabs
        value={tab}
        onValueChange={(value: string) => {
          if (isQosTab(value)) setTab(value);
        }}
      >
        <PageTabsList>
          <PageTabsTrigger value="overview">Overview</PageTabsTrigger>
          <PageTabsTrigger value="benchmarks">Benchmarks</PageTabsTrigger>
          <PageTabsTrigger value="health">Health checks</PageTabsTrigger>
        </PageTabsList>
        <PageTabsContent value="overview">
          <QosOverview accessToken={accessToken} />
        </PageTabsContent>
        <PageTabsContent value="health">
          <QosHealthPanel accessToken={accessToken} />
        </PageTabsContent>
        <PageTabsContent value="benchmarks">
          <BenchmarksPanel
            accessToken={accessToken}
            activeRun={activeRun}
            selectedRunId={runId}
            onSelectRun={(id) => void setRunId(id)}
            onStartClick={() => setDialogModel("")}
          />
        </PageTabsContent>
      </PageTabs>

      {dialogModel !== null && (
        <StartBenchmarkDialog
          open
          onOpenChange={(open) => {
            if (!open) setDialogModel(null);
          }}
          accessToken={accessToken}
          initialModel={dialogModel}
          onStarted={handleStarted}
        />
      )}
    </Page>
  );
}
