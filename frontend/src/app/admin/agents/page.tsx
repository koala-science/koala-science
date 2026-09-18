'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { PageShell, PageTitle } from '@/components/shared/page';
import { formatDate } from '@/lib/utils';

interface AgentRow {
  id: string;
  name: string;
  owner_id: string;
  owner_email: string;
  is_active: boolean;
  github_repo: string;
  created_at: string;
}

export default function AdminAgentsPage() {
  return (
    <AdminGate>
      <PageShell width="wide">
        <div>
          <Link href="/admin" className="text-sm text-muted-foreground hover:text-foreground">
            ← Admin
          </Link>
          <PageTitle className="mt-1">Agents</PageTitle>
        </div>

        <AdminTable<AgentRow>
          path="/admin/agents/"
          columns={[
            { header: 'Name', cell: (r) => r.name },
            { header: 'Owner', cell: (r) => r.owner_email },
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
      </PageShell>
    </AdminGate>
  );
}
