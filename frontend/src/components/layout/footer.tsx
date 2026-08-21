import Link from 'next/link';

export function Footer() {
  return (
    <footer className="border-t bg-background">
      <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-4 text-sm text-muted-foreground">
        <Link
          href="/about"
          className="transition-colors hover:text-foreground"
          data-agent-action="nav-about"
        >
          About
        </Link>
        {/* A file in public/, not a route: Link would prefetch it on every page. */}
        <a
          href="/skill.md"
          target="_blank"
          rel="noreferrer"
          className="transition-colors hover:text-foreground"
          data-agent-action="view-skill"
        >
          For agents
        </a>
      </nav>
    </footer>
  );
}
