"use client";

import React from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import CollapsibleSection from "./CollapsibleSection";
import { SCHEDULED_RUNS_SHOWN, type ProbeRun, type RunMember } from "./qosData";

const RUN_TIME: Intl.DateTimeFormatOptions = {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
};

export const formatRunTime = (iso: string): string => new Date(iso).toLocaleString("en-US", RUN_TIME);

function RunCard({
  title,
  meta,
  latest,
  children,
}: {
  title: React.ReactNode;
  meta: React.ReactNode;
  latest: boolean;
  children: React.ReactNode;
}) {
  const titleId = React.useId();
  return (
    <Collapsible defaultOpen={latest} role="group" aria-labelledby={titleId} className="rounded-lg border">
      <CollapsibleTrigger className="group/run flex w-full items-center justify-between gap-3 rounded-lg px-4 py-3 text-left hover:bg-muted/50">
        <span className="flex min-w-0 flex-col gap-1">
          <span id={titleId} className="truncate font-medium">
            {title}
          </span>
          <span className="text-sm text-muted-foreground">{meta}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {latest && <Badge>Latest</Badge>}
          <ChevronDown
            aria-hidden
            className="size-4 -rotate-90 text-muted-foreground transition-transform group-data-[panel-open]/run:rotate-0"
          />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t p-4">{children}</CollapsibleContent>
    </Collapsible>
  );
}

interface ProbeRunsProps<T extends RunMember> {
  readonly id: string;
  readonly runs: readonly ProbeRun<T>[];
  readonly schedule: React.ReactNode;
  readonly title: (run: ProbeRun<T>) => React.ReactNode;
  readonly meta: (run: ProbeRun<T>) => React.ReactNode;
  readonly children: (run: ProbeRun<T>) => React.ReactNode;
}

/** The runs started by hand, newest open and the rest folded, then the scheduled runs, latest few first. */
export default function ProbeRuns<T extends RunMember>({
  id,
  runs,
  schedule,
  title,
  meta,
  children,
}: ProbeRunsProps<T>) {
  const [allScheduled, setAllScheduled] = React.useState(false);
  const manual = runs.filter((run) => !run.scheduled);
  const scheduled = runs.filter((run) => run.scheduled);
  const shown = allScheduled ? scheduled : scheduled.slice(0, SCHEDULED_RUNS_SHOWN);
  const card = (run: ProbeRun<T>, latest: boolean) => (
    <RunCard key={run.key} title={title(run)} meta={meta(run)} latest={latest}>
      {children(run)}
    </RunCard>
  );

  return (
    <>
      <CollapsibleSection
        id={`${id}.manual`}
        title="Manual evaluations"
        hint="Started with the Start evaluation button"
      >
        {manual.length === 0 && (
          <p className="text-sm text-muted-foreground">No evaluations were started by hand in this time range</p>
        )}
        {manual.slice(0, 1).map((run) => card(run, true))}
        {manual.length > 1 && <p className="mt-2 text-sm font-medium">Earlier manual evaluations</p>}
        {manual.slice(1).map((run) => card(run, false))}
      </CollapsibleSection>

      <CollapsibleSection id={`${id}.scheduled`} title="Scheduled evaluations">
        <p className="text-sm text-muted-foreground">{schedule}</p>
        {scheduled.length === 0 && (
          <p className="text-sm text-muted-foreground">No scheduled evaluations in this time range</p>
        )}
        {shown.map((run) => card(run, false))}
        {scheduled.length > SCHEDULED_RUNS_SHOWN && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            {allScheduled ? (
              <span>{scheduled.length} runs</span>
            ) : (
              <span>
                {scheduled.length} runs, only the latest {SCHEDULED_RUNS_SHOWN} listed
              </span>
            )}
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setAllScheduled(!allScheduled)}>
              {allScheduled ? "Show only the latest" : "Show all"}
            </Button>
          </p>
        )}
      </CollapsibleSection>
    </>
  );
}
