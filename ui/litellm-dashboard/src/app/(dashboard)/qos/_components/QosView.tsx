"use client";

import React from "react";
import { parseAsString, useQueryState } from "nuqs";

import { Page, PageTabs, PageTabsContent, PageTabsList, PageTabsTrigger } from "@/components/shared/Page";
import { PageHeader, PageHeaderDescription, PageHeaderTitle } from "@/components/shared/PageHeader";
import { useUrlTab } from "@/hooks/useUrlTab";
import BenchmarksPanel from "./BenchmarksPanel";
import CollapsibleSection from "./CollapsibleSection";
import ImageQosPanel from "./ImageQosPanel";
import QosHealthPanel from "./QosHealthPanel";
import QosMediaPanel from "./QosMediaPanel";
import QosOverview from "./QosOverview";
import QosSpeechEvaluationPanel from "./QosSpeechEvaluationPanel";
import QosVideoReviewPanel from "./QosVideoReviewPanel";
import { QOS_BENCHMARK_MODEL_PARAM, type QosBenchmarkStarted } from "./qosData";
import StartBenchmarkDialog from "./StartBenchmarkDialog";

const QOS_TABS = ["overview", "benchmarks", "images", "health", "audio", "video"] as const;
const VIDEO_TAB_ALIASES = ["media", "reviews"] as const;
const URL_TABS = [...QOS_TABS, ...VIDEO_TAB_ALIASES] as const;
type QosTab = (typeof QOS_TABS)[number];
type VideoTabAlias = (typeof VIDEO_TAB_ALIASES)[number];
const isQosTab = (value: string): value is QosTab => QOS_TABS.some((tab) => tab === value);
const isVideoTabAlias = (value: string): value is VideoTabAlias => VIDEO_TAB_ALIASES.some((tab) => tab === value);

export default function QosView({ accessToken }: { accessToken: string | null }) {
  const [urlTab, setTab] = useUrlTab(URL_TABS, "overview");
  const tab: QosTab = isVideoTabAlias(urlTab) ? "video" : urlTab;

  React.useEffect(() => {
    if (isVideoTabAlias(urlTab)) setTab("video");
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
          <PageTabsTrigger value="audio">Audio</PageTabsTrigger>
          <PageTabsTrigger value="video">Video</PageTabsTrigger>
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
        <PageTabsContent value="audio" className="flex flex-col gap-10">
          <QosMediaPanel accessToken={accessToken} modality="audio" />
          <CollapsibleSection id="audio.evaluations" level="h2" title="Speech evaluation" className="border-t pt-6">
            <QosSpeechEvaluationPanel accessToken={accessToken} />
          </CollapsibleSection>
        </PageTabsContent>
        <PageTabsContent value="video" className="flex flex-col gap-10">
          <QosMediaPanel accessToken={accessToken} modality="video" />
          <CollapsibleSection id="video.review" level="h2" title="Video review" className="border-t pt-6">
            <QosVideoReviewPanel accessToken={accessToken} />
          </CollapsibleSection>
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
