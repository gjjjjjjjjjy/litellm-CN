"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { getBreadcrumb } from "@/components/leftnav";
import ThemeToggle from "@/components/ThemeToggle/ThemeToggle";
import { CommandPaletteTrigger } from "@/components/CommandPalette/CommandPaletteTrigger";
import { uiHref } from "@/utils/uiHref";

export function DashboardHeader({ navigationTrigger }: { navigationTrigger?: ReactNode }) {
  const { title } = getBreadcrumb(usePathname());

  return (
    <header className="flex h-14 flex-none items-center justify-between gap-4 border-b border-border bg-background px-4 max-md:gap-2 max-md:px-2">
      {navigationTrigger}
      <Breadcrumb className="min-w-0 max-md:flex-1">
        <BreadcrumbList className="flex-nowrap">
          <BreadcrumbItem className="flex-none max-md:hidden">
            <BreadcrumbLink href={uiHref("")}>AI Gateway</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator className="max-md:hidden" />
          <BreadcrumbItem className="min-w-0">
            <BreadcrumbPage className="truncate">{title}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <CommandPaletteTrigger />
      <div className="flex shrink-0 items-center gap-1">
        <CommandPaletteTrigger mobile />
        <ThemeToggle />
      </div>
    </header>
  );
}

export default DashboardHeader;
