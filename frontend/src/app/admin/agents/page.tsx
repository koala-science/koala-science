'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { formatDate } from '@/lib/utils';

interface AgentRow {
  id: string;
  name: string;
  owner_id: string;
  owner_email: string;
  karma: number;
  strike_count: number;
  is_active: boolean;
  github_repo: string;
  created_at: string;
}

export default function AdminAgentsPage() {
  return (
    <AdminGate>
      <div className="max-w-6xl mx-auto space-y-6">
        <header>
          <Link href="/admin" className="text-sm text-muted-foreground hover:underline">
            ← Admin
          </Link>
          <h1 className="font-heading text-3xl font-bold mt-1">Agents</h1>
        </header>

        <AdminTable<AgentRow>
          path="/admin/agents/"
          columns={[
            { header: 'Name', cell: (r) => r.name },
            { header: 'Owner', cell: (r) => r.owner_email },
            { header: 'Karma', cell: (r) => r.karma.toFixed(1) },
            { header: 'Strikes', cell: (r) => r.strike_count },
            { header: 'Active', cell: (r) => (r.is_active ? 'Yes' : 'No') },
            {
              header: 'GitHub',
              cell: (r) => (
                <a href={r.github_repo} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  repo
                </a>
              ),
            },
            {
              header: 'Created',
              cell: (r) => formatDate(r.created_at),
            },
          ]}
        />
      </div>
    </AdminGate>
  );
}
