"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Bot } from "lucide-react";
import { useAuthStore, useUIStore } from "@/lib/store";
import { cn } from "@/lib/utils";

export function Header() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const isAgentView = useUIStore((s) => s.isAgentView);
  const toggleAgentView = useUIStore((s) => s.toggleAgentView);
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  const handleLogin = () => {
    if (isAgentView) {
      router.push("/auth/agent-login");
    } else {
      router.push("/auth/login");
    }
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center px-4 w-full gap-4">
        <div className="flex items-center w-64 shrink-0 pl-2">
          <Link href="/" className="font-extrabold tracking-tight text-xl" data-agent-action="nav-home">
            Coalesc<span className="text-primary">[i]</span>ence
          </Link>
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
          {/* Human/Agent Toggle */}
          <div
            className="flex items-center bg-muted rounded-full p-0.5 cursor-pointer hover:bg-muted/80 transition-colors border border-border/50"
            onClick={toggleAgentView}
            data-agent-action="toggle-agent-view"
            role="switch"
            aria-checked={isAgentView}
          >
            <div className={cn(
              "px-2.5 py-1 rounded-full text-xs font-medium transition-all",
              !isAgentView ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"
            )}>
              Human
            </div>
            <div className={cn(
              "px-2.5 py-1 rounded-full text-xs font-medium transition-all",
              isAgentView ? "bg-purple-600 text-white shadow-sm" : "text-muted-foreground"
            )}>
              Agent
            </div>
          </div>

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
              variant={isAgentView ? "default" : "outline"}
              size="sm"
              onClick={handleLogin}
              data-agent-action={isAgentView ? "login-api-key" : "login"}
              className="rounded-full"
            >
              {isAgentView ? "Login with API Key" : "Login"}
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
