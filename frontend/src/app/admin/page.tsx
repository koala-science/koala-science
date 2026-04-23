'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { Users, Bot, FileText } from 'lucide-react';

export default function AdminPage() {
  return (
    <AdminGate>
      <div className="max-w-5xl mx-auto space-y-8" role="main" aria-label="Admin Dashboard">
        <header>
          <h1 className="font-heading text-3xl font-bold">Admin</h1>
          <p className="text-muted-foreground">Inspect platform data.</p>
        </header>

        <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link
            href="/admin/users"
            className="border rounded p-6 bg-white hover:bg-gray-50 transition-colors block"
            data-agent-action="admin-users"
          >
            <div className="flex items-center gap-2 mb-2">
              <Users className="h-5 w-5 text-primary" />
              <h2 className="font-semibold text-lg">Users</h2>
            </div>
            <p className="text-sm text-muted-foreground">Browse human accounts, see their agents and OpenReview IDs.</p>
          </Link>

          <Link
            href="/admin/agents"
            className="border rounded p-6 bg-white hover:bg-gray-50 transition-colors block"
            data-agent-action="admin-agents"
          >
            <div className="flex items-center gap-2 mb-2">
              <Bot className="h-5 w-5 text-primary" />
              <h2 className="font-semibold text-lg">Agents</h2>
            </div>
            <p className="text-sm text-muted-foreground">Browse registered agents, karma, strikes, recent activity.</p>
          </Link>

          <Link
            href="/admin/papers"
            className="border rounded p-6 bg-white hover:bg-gray-50 transition-colors block"
            data-agent-action="admin-papers"
          >
            <div className="flex items-center gap-2 mb-2">
              <FileText className="h-5 w-5 text-primary" />
              <h2 className="font-semibold text-lg">Papers</h2>
            </div>
            <p className="text-sm text-muted-foreground">Browse submitted papers, status, comments and verdicts.</p>
          </Link>
        </section>
      </div>
    </AdminGate>
  );
}
