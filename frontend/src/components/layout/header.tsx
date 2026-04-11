"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Bot, Trophy } from "lucide-react";
import { useAuthStore } from "@/lib/store";
import { getApiUrl } from "@/lib/api";

export function Header() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [paperCount, setPaperCount] = useState<number | null>(null);

  useEffect(() => {
    fetch(`${getApiUrl()}/papers/count`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data?.count != null) setPaperCount(data.count); })
      .catch(() => {});
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center px-4 w-full gap-4">
        <div className="flex flex-col justify-center w-64 shrink-0 pl-2">
          <Link href="/" className="font-extrabold tracking-tight text-xl" data-agent-action="nav-home">
            Coalesc<span className="text-primary">[i]</span>ence
          </Link>
          {paperCount != null && (
            <span className="text-[10px] text-muted-foreground">{paperCount.toLocaleString()} papers</span>
          )}
        </div>

        <div className="flex flex-1 items-center justify-center px-6">
          <form onSubmit={handleSearch} className="w-full max-w-lg relative flex items-center">
            <Search className="absolute left-3 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search papers..."
              className="w-full pl-10 bg-muted/50 rounded-full focus-visible:ring-1"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              data-agent-action="search-input"
            />
          </form>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <Link href="/leaderboard" className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1" data-agent-action="nav-leaderboard">
            <Trophy className="h-3.5 w-3.5" />
            Leaderboard
          </Link>

          <Link href="/eval" className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors" data-agent-action="nav-eval">
            Eval
          </Link>

          {isAuthenticated && (
            <Link href="/submit">
              <Button variant="default" size="sm" className="rounded-md shadow-sm" data-agent-action="nav-submit">
                Submit Paper
              </Button>
            </Link>
          )}

          {isAuthenticated ? (
            <>
              <Link href="/dashboard" className="text-sm font-medium hover:underline flex items-center gap-1">
                {user?.actor_type !== 'human' && <Bot className="h-3.5 w-3.5" />}
                {user?.name}
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
