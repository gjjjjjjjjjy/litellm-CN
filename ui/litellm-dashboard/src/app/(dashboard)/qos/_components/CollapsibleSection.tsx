"use client";

import React from "react";
import { ChevronDown } from "lucide-react";
import { z } from "zod";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/cva.config";
import { storageKey, useStoredValue, type StorageKey } from "@/lib/storage";

const openKey = (id: string): StorageKey<boolean> => storageKey("local", `qos.section.${id}.open`, z.boolean(), true);

interface CollapsibleSectionProps {
  readonly id: string;
  readonly title: string;
  readonly level?: "h2" | "h3";
  readonly help?: React.ReactNode;
  readonly hint?: string;
  readonly className?: string;
  readonly children: React.ReactNode;
}

/** A section that folds down to its title when clicked, remembered per browser under its id. */
export default function CollapsibleSection({
  id,
  title,
  level = "h3",
  help,
  hint,
  className,
  children,
}: CollapsibleSectionProps) {
  const key = React.useMemo(() => openKey(id), [id]);
  const [open, setOpen] = useStoredValue(key);
  const headingId = React.useId();
  const Heading = level;

  return (
    <section aria-labelledby={headingId} className={className}>
      <Collapsible open={open} onOpenChange={setOpen} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Heading id={headingId} className={level === "h2" ? "text-lg font-semibold" : "text-base font-semibold"}>
            <CollapsibleTrigger className="group/section -mx-1.5 flex items-center gap-1.5 rounded-md px-1.5 hover:bg-muted">
              {title}
              <ChevronDown
                aria-hidden
                className="size-4 -rotate-90 text-muted-foreground transition-transform group-data-[panel-open]/section:rotate-0"
              />
            </CollapsibleTrigger>
          </Heading>
          {help}
          {hint !== undefined && <span className="text-sm text-muted-foreground">{hint}</span>}
        </div>
        <CollapsibleContent className={cn("flex flex-col gap-2", level === "h2" && "gap-6")}>
          {children}
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
