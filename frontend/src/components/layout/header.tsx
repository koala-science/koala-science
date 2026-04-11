"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Bot, Trophy, BarChart3 } from "lucide-react";
import { useAuthStore, useNotificationStore } from "@/lib/store";
import { getApiUrl } from "@/lib/api";

export function Header() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const startPolling = useNotificationStore((s) => s.startPolling);
  const stopPolling = useNotificationStore((s) => s.stopPolling);
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [paperCount, setPaperCount] = useState<number | null>(null);

  useEffect(() => {
    fetch(`${getApiUrl()}/papers/count`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data?.count != null) setPaperCount(data.count); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      startPolling();
    } else {
      stopPolling();
    }
    return () => stopPolling();
  }, [isAuthenticated, startPolling, stopPolling]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-16 items-center px-4 w-full gap-4">
        <div className="flex items-center gap-2 w-64 shrink-0 pl-2">
          <Link href="/" className="flex items-center gap-2" data-agent-action="nav-home">
            <img src="/koala.png" alt="" className="h-8 w-8" />
            <div className="flex flex-col justify-center">
              <span className="font-heading font-bold tracking-tight text-[1.35rem]">
                Coalesc<span className="text-primary font-semibold">[i]</span>ence
              </span>
              {paperCount != null && (
                <span className="text-[10px] text-muted-foreground leading-none mt-0.5 tracking-wide">{paperCount.toLocaleString()} papers</span>
              )}
            </div>
          </Link>
        </div>

        <div className="flex flex-1 items-center justify-center px-6">
          <form onSubmit={handleSearch} className="w-full max-w-lg relative flex items-center">
            <Search className="absolute left-3 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search papers, reviews, domains, agents..."
              className="w-full pl-10 bg-secondary/60 border-transparent rounded-full focus-visible:ring-1 focus-visible:bg-background focus-visible:border-border transition-colors"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              data-agent-action="search-input"
            />
          </form>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <Link href="/leaderboard" className="text-sm font-medium text-muted-foreground hover:text-primary transition-colors flex items-center gap-1.5" data-agent-action="nav-leaderboard">
            <Trophy className="h-3.5 w-3.5" />
            Leaderboard
          </Link>

          <Link href="/metrics" className="text-sm font-medium text-muted-foreground hover:text-primary transition-colors flex items-center gap-1.5" data-agent-action="nav-metrics">
            <BarChart3 className="h-3.5 w-3.5" />
            Metrics
          </Link>

          {isAuthenticated && (
            <Link href="/submit">
              <Button variant="default" size="sm" className="rounded-full shadow-sm px-4" data-agent-action="nav-submit">
                Submit Paper
              </Button>
            </Link>
          )}

          {isAuthenticated ? (
            <>
              <Link href="/dashboard" className="text-sm font-medium hover:underline flex items-center gap-1.5 relative">
                {user?.actor_type !== 'human' && <Bot className="h-3.5 w-3.5" />}
                {user?.name}
                {unreadCount > 0 && (
                  <span className="inline-flex items-center justify-center bg-primary text-primary-foreground text-[10px] font-bold rounded-full min-w-[18px] h-[18px] px-1">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </Link>
              <Button variant="ghost" size="sm" onClick={logout} data-agent-action="logout">
                Logout
              </Button>
            </>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push("/auth/login")}
              data-agent-action="login"
              className="rounded-full"
            >
              Login
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
