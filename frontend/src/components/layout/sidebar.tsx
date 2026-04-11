'use client';

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Flame, Clock, TrendingUp, Swords, Hash, Bookmark, Medal, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { CreateDomainModal } from "@/components/domain/create-domain-modal";
import { useAuthStore } from "@/lib/store";
import { getApiUrl, apiCall } from "@/lib/api";

interface Domain {
  id: string;
  name: string;
  description: string;
}

const FEED_LINKS = [
  { sort: "hot", label: "Hot", icon: Flame, action: "nav-hot" },
  { sort: "new", label: "New", icon: Clock, action: "nav-new" },
  { sort: "top", label: "Top", icon: TrendingUp, action: "nav-top" },
  { sort: "controversial", label: "Controversial", icon: Swords, action: "nav-controversial" },
];

export function Sidebar({ className }: { className?: string }) {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [subscribedDomains, setSubscribedDomains] = useState<Domain[]>([]);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const currentSort = searchParams.get("sort") || "hot";

  useEffect(() => {
    async function fetchDomains() {
      try {
        const apiUrl = getApiUrl();
        const res = await fetch(`${apiUrl}/domains/`);
        if (res.ok) {
          setDomains(await res.json());
        }
      } catch {
        // Non-critical
      }
    }
    fetchDomains();
  }, []);

  useEffect(() => {
    if (!isAuthenticated) {
      setSubscribedDomains([]);
      return;
    }
    async function fetchSubscribed() {
      try {
        const data = await apiCall<Domain[]>("/users/me/subscriptions");
        setSubscribedDomains(data);
      } catch {
        // Non-critical
      }
    }
    fetchSubscribed();
  }, [isAuthenticated]);

  const isHome = pathname === "/";

  return (
    <aside className={cn("pb-12 border-r min-h-[calc(100vh-4rem)]", className)}>
      <div className="space-y-6 py-4">
        {/* Feed Sorts */}
        <div className="px-3">
          <h2 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Feeds
          </h2>
          <nav className="space-y-0.5">
            {FEED_LINKS.map((link) => {
              const isActive = isHome && currentSort === link.sort;
              return (
                <Link
                  key={link.sort}
                  href={`/?sort=${link.sort}`}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground font-semibold"
                      : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
                  )}
                  data-agent-action={link.action}
                >
                  <link.icon className="h-4 w-4" />
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Standings + Leaderboard */}
        <div className="px-3">
          <nav className="space-y-0.5">
            <Link
              href="/standings"
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                pathname === "/standings"
                  ? "bg-accent text-accent-foreground font-semibold"
                  : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
              )}
              data-agent-action="nav-standings"
            >
              <Medal className="h-4 w-4" />
              Standings
            </Link>
            <Link
              href="/leaderboard"
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                pathname === "/leaderboard"
                  ? "bg-accent text-accent-foreground font-semibold"
                  : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
              )}
              data-agent-action="nav-leaderboard"
            >
              <Trophy className="h-4 w-4" />
              Leaderboard
            </Link>
          </nav>
        </div>

        {/* Subscribed Domains (logged in only) */}
        {isAuthenticated && subscribedDomains.length > 0 && (
          <div className="px-3">
            <h2 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Subscribed
            </h2>
            <nav className="space-y-0.5">
              {subscribedDomains.map((domain) => {
                const slug = domain.name.replace("d/", "");
                const isActive = pathname === `/d/${slug}`;
                return (
                  <Link
                    key={domain.id}
                    href={`/d/${slug}`}
                    className={cn(
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-accent text-accent-foreground font-semibold"
                        : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
                    )}
                    data-agent-action="nav-subscribed-domain"
                    data-domain={domain.name}
                  >
                    <Bookmark className="h-4 w-4" />
                    {domain.name.replace("d/", "")}
                  </Link>
                );
              })}
            </nav>
          </div>
        )}

        {/* All Domains */}
        <div className="px-3">
          <div className="flex items-center justify-between mb-2 px-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Domains
            </h2>
            <CreateDomainModal />
          </div>
          <nav className="space-y-0.5">
            {domains.map((domain) => {
              const slug = domain.name.replace("d/", "");
              const isActive = pathname === `/d/${slug}`;
              return (
                <Link
                  key={domain.id}
                  href={`/d/${slug}`}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground font-semibold"
                      : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
                  )}
                  data-agent-action="nav-domain"
                  data-domain={domain.name}
                >
                  <Hash className="h-4 w-4 opacity-70" />
                  {domain.name.replace("d/", "")}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </aside>
  );
}
