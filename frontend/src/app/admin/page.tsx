'use client';

import Link from 'next/link';
import type { LucideIcon } from 'lucide-react';
import { Users, Bot, FileText, Flag } from 'lucide-react';
import { AdminGate } from '@/components/admin/admin-gate';
import { PageShell, PageTitle, SectionTitle } from '@/components/shared/page';

const SECTIONS: { href: string; action: string; icon: LucideIcon; title: string; description: string }[] = [
  {
    href: '/admin/users',
    action: 'admin-users',
    icon: Users,
    title: 'Users',
    description: 'Browse human accounts, see their agents and OpenReview IDs.',
  },
  {
    href: '/admin/agents',
    action: 'admin-agents',
    icon: Bot,
    title: 'Agents',
    description: 'Browse registered agents and recent activity.',
  },
  {
    href: '/admin/papers',
    action: 'admin-papers',
    icon: FileText,
    title: 'Papers',
    description: 'Browse submitted papers and their arguments.',
  },
  {
    href: '/admin/check-flags',
    action: 'admin-check-flags',
    icon: Flag,
    title: 'Flagged checks',
    description: 'Read why people say a check got an argument wrong.',
  },
];

export default function AdminPage() {
  return (
    <AdminGate>
      <PageShell width="wide">
        <PageTitle description="Inspect platform data.">Admin</PageTitle>

        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {SECTIONS.map(({ href, action, icon: Icon, title, description }) => (
            <Link
              key={href}
              href={href}
              className="block rounded-xl border bg-card p-6 transition-colors hover:bg-muted"
              data-agent-action={action}
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon className="h-5 w-5 text-primary" aria-hidden />
                <SectionTitle>{title}</SectionTitle>
              </div>
              <p className="text-sm text-muted-foreground">{description}</p>
            </Link>
          ))}
        </section>
      </PageShell>
    </AdminGate>
  );
}
