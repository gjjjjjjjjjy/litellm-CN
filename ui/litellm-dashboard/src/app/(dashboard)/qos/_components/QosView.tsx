"use client";

import React from "react";
import { parseAsString, useQueryState } from "nuqs";

import { Page, PageTabs, PageTabsContent, PageTabsList, PageTabsTrigger } from "@/components/shared/Page";
import { PageHeader, PageHeaderDescription, PageHeaderTitle } from "@/components/shared/PageHeader";
import { useUrlTab } from "@/hooks/useUrlTab";
import BenchmarksPanel from "./BenchmarksPanel";
import ImageQosPanel from "./ImageQosPanel";
import QosHealthPanel from "./QosHealthPanel";
import QosMediaPanel from "./QosMediaPanel";
import QosOverview from "./QosOverview";
import QosVideoReviewPanel from "./QosVideoReviewPanel";
import { QOS_BENCHMARK_MODEL_PARAM, type QosBenchmarkStarted } from "./qosData";
import StartBenchmarkDialog from "./StartBenchmarkDialog";

const QOS_TABS = ["overview", "benchmarks", "images", "health", "media"] as const;
const REVIEWS_TAB = "reviews";
const URL_TABS = [...QOS_TABS, REVIEWS_TAB] as const;
type QosTab = (typeof QOS_TABS)[number];
const isQosTab = (value: string): value is QosTab => QOS_TABS.some((tab) => tab === value);

export default function QosView({ accessToken }: { accessToken: string | null }) {
  const [urlTab, setTab] = useUrlTab(URL_TABS, "overview");
  const tab: QosTab = urlTab === REVIEWS_TAB ? "media" : urlTab;

  React.useEffect(() => {
    if (urlTab === REVIEWS_TAB) setTab("media");
  }, [urlTab, setTab]);
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
        {tab === "images" ? (
          <PageHeaderDescription>
            Image generation success rate, end-to-end latency, provider queue and generation time, and cost.
          </PageHeaderDescription>
        ) : (
          <PageHeaderDescription>
            Concurrency, success rate, TTFT, TPOT and latency per model and per node, measured from gateway traffic.
            TTFT and TPOT come from streamed requests only; cache hits are excluded.
          </PageHeaderDescription>
        )}
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
          <PageTabsTrigger value="images">Images</PageTabsTrigger>
          <PageTabsTrigger value="health">Health checks</PageTabsTrigger>
          <PageTabsTrigger value="media">Audio and video</PageTabsTrigger>
        </PageTabsList>
        <PageTabsContent value="overview">
          <QosOverview accessToken={accessToken} />
        </PageTabsContent>
        <PageTabsContent value="health">
          <QosHealthPanel accessToken={accessToken} />
        </PageTabsContent>
        <PageTabsContent value="images">
          <ImageQosPanel accessToken={accessToken} />
        </PageTabsContent>
        <PageTabsContent value="media" className="flex flex-col gap-10">
          <QosMediaPanel accessToken={accessToken} />
          <section aria-labelledby="qos-video-review" className="flex flex-col gap-4 border-t pt-6">
            <h2 id="qos-video-review" className="text-lg font-semibold">
              Video review
            </h2>
            <QosVideoReviewPanel accessToken={accessToken} />
          </section>
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
