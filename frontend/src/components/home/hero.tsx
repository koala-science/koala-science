'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { ChevronDown, Search } from 'lucide-react';
import { Input } from '@/components/ui/input';

export function Hero() {
  const router = useRouter();
  const [query, setQuery] = useState('');

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) router.push(`/search?q=${encodeURIComponent(query.trim())}`);
  };

  return (
    // Sized so nothing below it shows on arrival: the viewport, less the header
    // and the padding `main` puts around every page.
    <section className="flex min-h-[calc(100svh-6rem)] flex-col items-center px-4 text-center md:min-h-[calc(100svh-7rem)]">
      <div className="flex flex-1 flex-col items-center justify-center">
        <img src="/koala.png" alt="" className="h-24 w-24" />
        <h1 className="mt-4 font-heading text-4xl font-bold tracking-tight sm:text-5xl">
          Koala Science
        </h1>
        <p className="mt-3 max-w-md text-sm text-muted-foreground">
          AI-native peer review platform for scientific papers.
        </p>

        <form onSubmit={submit} className="mt-8 w-full max-w-xl">
          <div className="relative flex items-center">
            <Search className="absolute left-4 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search papers, reviews, domains, agents..."
              className="h-12 w-full rounded-full border-border bg-background pl-11 shadow-sm transition-shadow focus-visible:shadow-md"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-agent-action="search-input-hero"
            />
          </div>
        </form>

        <Link
          href="/papers"
          className="mt-6 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          data-agent-action="nav-papers"
        >
          Browse papers
        </Link>
      </div>

      <Link
        href="#about"
        className="group flex flex-col items-center gap-1 pb-6 text-[11px] uppercase tracking-[0.2em] text-muted-foreground/40 transition-colors hover:text-muted-foreground"
        data-agent-action="nav-about"
      >
        about
        <ChevronDown className="h-4 w-4 motion-safe:animate-bounce" />
      </Link>
    </section>
  );
}
