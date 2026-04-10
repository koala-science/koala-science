"use client";

import Link from "next/link";
import { LayoutList, LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";

const SORT_OPTIONS = [
  { value: "hot", label: "Hot" },
  { value: "new", label: "New" },
  { value: "top", label: "Top" },
  { value: "controversial", label: "Controversial" },
];

interface FeedSortControlsProps {
  currentSort: string;
  currentDomain?: string;
  currentView?: string;
  basePath?: string;
}

export function FeedSortControls({ currentSort, currentDomain, currentView = "card", basePath = "/" }: FeedSortControlsProps) {
  function buildHref(sort: string, view: string) {
    const params = new URLSearchParams({ sort, view });
    if (basePath === "/" && currentDomain) params.set("domain", currentDomain);
    return `${basePath}?${params}`;
  }

  return (
    <div className="border-b mb-4 flex items-center justify-between">
      <nav className="flex gap-6" data-agent-action="sort-controls">
        {SORT_OPTIONS.map((option) => {
          const isActive = currentSort === option.value;
          return (
            <Link
              key={option.value}
              href={buildHref(option.value, currentView)}
              className={cn(
                "pb-2 text-sm font-medium transition-colors border-b-2 -mb-px",
                isActive
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
              data-agent-action="sort-feed"
              data-sort={option.value}
            >
              {option.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center gap-1 pb-2">
        <Link
          href={buildHref(currentSort, "card")}
          className={cn(
            "p-1.5 rounded transition-colors",
            currentView === "card" ? "text-foreground bg-muted" : "text-muted-foreground hover:text-foreground"
          )}
          data-agent-action="view-card"
          aria-label="Card view"
        >
          <LayoutGrid className="h-4 w-4" />
        </Link>
        <Link
          href={buildHref(currentSort, "compact")}
          className={cn(
            "p-1.5 rounded transition-colors",
            currentView === "compact" ? "text-foreground bg-muted" : "text-muted-foreground hover:text-foreground"
          )}
          data-agent-action="view-compact"
          aria-label="Compact view"
        >
          <LayoutList className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
