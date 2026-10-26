"use client";

import React from "react";
import { Coins } from "lucide-react";

import { HOME_USAGE_DAYS, useHomeUsage } from "@/app/(dashboard)/home/_components/useHomeUsage";
import { Leaderboard, useBreakdown } from "@/app/(dashboard)/usage/_components/components/overview/BreakdownChart";
import { formatCompact } from "@/app/(dashboard)/usage/_components/components/overview/overviewData";
import { Segmented } from "@/app/(dashboard)/usage/_components/components/overview/Primitives";
import { Skeleton } from "@/components/ui/skeleton";

type LeaderboardMetric = "tokens" | "requests";

const LEADERBOARD_METRICS: readonly { readonly value: LeaderboardMetric; readonly label: string }[] = [
  { value: "tokens", label: "Tokens" },
  { value: "requests", label: "Requests" },
];

/** Which models used the most tokens or requests over the last week, with the change between its two halves. */
export default function UsageLeaderboard() {
  const usage = useHomeUsage();
  const [metric, setMetric] = React.useState<LeaderboardMetric>("tokens");
  const { series, ranking } = useBreakdown(usage.results, { metric, dimension: "model_groups" }, 6);

  return (
    <section className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500">
            <Coins className="size-3.5" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-sm font-semibold">Usage by model</h2>
            <p className="text-[11px] text-muted-foreground">
              {usage.loading
                ? `Last ${HOME_USAGE_DAYS} days`
                : `Last ${HOME_USAGE_DAYS} days · ${formatCompact(usage.totals.tokens)} tokens in total`}
            </p>
          </div>
        </div>
        <Segmented label="Usage metric" value={metric} options={LEADERBOARD_METRICS} onChange={setMetric} />
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-1">
        {usage.failed && <p className="py-6 text-center text-sm text-destructive">Failed to load usage</p>}
        {usage.loading && !usage.failed && (
          <div className="flex flex-col gap-2 py-2">
            {[0, 1, 2, 3].map((index) => (
              <Skeleton key={index} className="h-8 w-full" />
            ))}
          </div>
        )}
        {!usage.loading && !usage.failed && (
          <Leaderboard ranking={ranking} series={series} metric={metric} dimension="model_groups" limit={6} />
        )}
      </div>
    </section>
  );
}
