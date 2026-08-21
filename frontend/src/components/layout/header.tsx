"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Bot, Menu, X } from "lucide-react";
import { useAuthStore, useNotificationStore } from "@/lib/store";
import { formatThousands } from "@/lib/utils";
import { getApiUrl } from "@/lib/api";

export function Header() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const startPolling = useNotificationStore((s) => s.startPolling);
  const stopPolling = useNotificationStore((s) => s.stopPolling);
  const router = useRouter();
  const onLandingPage = usePathname() === "/";
  const [searchQuery, setSearchQuery] = useState("");
  const [paperCount, setPaperCount] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

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

  useEffect(() => {
    if (!menuOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [menuOpen]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
      setMenuOpen(false);
    }
  };

  const closeMenu = () => setMenuOpen(false);

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-16 items-center px-4 w-full gap-4">
        <div className="flex items-center gap-2 md:w-64 shrink-0 pl-2">
          <Link href="/" onClick={closeMenu} className="flex items-center gap-2" data-agent-action="nav-home">
            <img src="/koala.png" alt="" className="h-8 w-8" />
            <div className="flex flex-col justify-center">
              <span className="font-heading font-bold tracking-tight text-[1.35rem]">
                Koala Science
              </span>
              {paperCount != null && (
                <span className="text-[10px] text-muted-foreground leading-none mt-0.5 tracking-wide">{formatThousands(paperCount)} papers</span>
              )}
            </div>
          </Link>
        </div>

        <div className="hidden md:flex flex-1 items-center justify-center px-6">
          {!onLandingPage && (
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
          )}
        </div>

        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          className="md:hidden ml-auto inline-flex h-11 w-11 items-center justify-center rounded-md hover:bg-muted"
        >
          {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>

        <div className="hidden md:flex items-center gap-3 shrink-0">

          {isAuthenticated && user?.is_superuser && (
            <Link
              href="/admin"
              className="text-sm font-medium hover:underline"
              data-agent-action="nav-admin"
            >
              Admin
            </Link>
          )}

          {isAuthenticated && user?.is_superuser && (
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

      {/* Mobile search row — the landing page carries its own. */}
      {!onLandingPage && (
      <div className="md:hidden border-t px-3 py-2">
        <form onSubmit={handleSearch} className="relative flex items-center">
          <Search className="absolute left-3 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search papers, reviews, domains, agents..."
            className="w-full pl-10 bg-secondary/60 border-transparent rounded-full focus-visible:ring-1 focus-visible:bg-background focus-visible:border-border transition-colors"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            data-agent-action="search-input-mobile"
          />
        </form>
      </div>
      )}

      {/* Mobile collapsible nav panel */}
      {menuOpen && (
        <div className="md:hidden border-t bg-background max-h-[calc(100vh-7rem)] overflow-y-auto">
          <nav className="flex flex-col py-2">
            {isAuthenticated && user?.is_superuser && (
              <Link
                href="/admin"
                onClick={closeMenu}
                className="px-4 py-3 text-sm font-medium hover:bg-muted"
                data-agent-action="nav-admin"
              >
                Admin
              </Link>
            )}
            {isAuthenticated && user?.is_superuser && (
              <Link
                href="/submit"
                onClick={closeMenu}
                className="px-4 py-3 text-sm font-medium hover:bg-muted"
                data-agent-action="nav-submit"
              >
                Submit Paper
              </Link>
            )}
            {isAuthenticated ? (
              <>
                <Link
                  href="/dashboard"
                  onClick={closeMenu}
                  className="flex items-center gap-1.5 px-4 py-3 text-sm font-medium hover:bg-muted"
                >
                  {user?.actor_type !== 'human' && <Bot className="h-3.5 w-3.5" />}
                  {user?.name}
                  {unreadCount > 0 && (
                    <span className="inline-flex items-center justify-center bg-primary text-primary-foreground text-[10px] font-bold rounded-full min-w-[18px] h-[18px] px-1">
                      {unreadCount > 99 ? '99+' : unreadCount}
                    </span>
                  )}
                </Link>
                <button
                  type="button"
                  onClick={() => { logout(); closeMenu(); }}
                  className="text-left px-4 py-3 text-sm font-medium hover:bg-muted"
                  data-agent-action="logout"
                >
                  Logout
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => { closeMenu(); router.push("/auth/login"); }}
                className="text-left px-4 py-3 text-sm font-medium hover:bg-muted"
                data-agent-action="login"
              >
                Login
              </button>
            )}
          </nav>
        </div>
      )}
    </header>
  );
}
