"use client";

import type { ComponentType, ReactNode } from "react";
import { Activity, CircleCheck, FlaskConical, PackagePlus, ServerCrash } from "lucide-react";

import { useQosActivity, type QosActivityEvent } from "@/app/(dashboard)/hooks/qos/useQosHome";
import { cn } from "@/lib/cva.config";
import { activityLine, relativeTimeLabel, type ActivityTone } from "./homeData";

const FeedPanel = ({
  icon: Icon,
  title,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  children: ReactNode;
}) => (
  <section className="flex max-h-40 min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">
    <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b px-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="size-4 text-muted-foreground" />
        {title}
      </h3>
    </header>
    {children !== null && (
      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3"
        role="region"
        aria-label={title}
        tabIndex={0}
      >
        {children}
      </div>
    )}
  </section>
);

const EmptyLine = ({ text }: { text: string }) => (
  <p className="py-3 text-center text-xs text-muted-foreground">{text}</p>
);

const TONE_BADGE: Readonly<Record<ActivityTone, string>> = {
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  error: "bg-destructive/10 text-destructive",
  info: "bg-primary/10 text-primary",
};

const ACTIVITY_ICON: Readonly<Record<QosActivityEvent["kind"], typeof Activity>> = {
  node_down: ServerCrash,
  node_recovered: CircleCheck,
  benchmark: FlaskConical,
  model_added: PackagePlus,
};

export const ActivityPanel = ({
  accessToken,
  refreshMs,
  now,
}: {
  accessToken: string | null;
  refreshMs: number | false;
  now: Date;
}) => {
  const activity = useQosActivity(accessToken, refreshMs).data;

  return (
    <FeedPanel icon={Activity} title="Activity">
      {activity === undefined || activity.events.length === 0 ? (
        <EmptyLine text="Nothing happened in the last 7 days" />
      ) : (
        <ol className="flex flex-col gap-3">
          {activity.events.map((event, index) => {
            const line = activityLine(event);
            const Icon = ACTIVITY_ICON[event.kind];
            return (
              <li
                key={`${event.kind}-${event.at}-${index}`}
                className="flex gap-2.5 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-right-2 motion-safe:duration-500"
              >
                <span
                  className={cn("flex size-6 shrink-0 items-center justify-center rounded-lg", TONE_BADGE[line.tone])}
                >
                  <Icon className="size-3.5" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-xs leading-relaxed font-medium">{line.title}</p>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground" title={line.description}>
                    {`${relativeTimeLabel(event.at, now)} · ${line.description}`}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </FeedPanel>
  );
};
