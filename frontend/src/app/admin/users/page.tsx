'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { PageShell, PageTitle } from '@/components/shared/page';
import { formatDate } from '@/lib/utils';

interface UserRow {
  id: string;
  email: string;
  name: string;
  is_superuser: boolean;
  is_active: boolean;
  orcid_id: string | null;
  openreview_id: string | null;
  agent_count: number;
  created_at: string;
}

export default function AdminUsersPage() {
  return (
    <AdminGate>
      <PageShell width="wide">
        <div>
          <Link href="/admin" className="text-sm text-muted-foreground hover:text-foreground">
            ← Admin
          </Link>
          <PageTitle className="mt-1">Users</PageTitle>
        </div>

        <AdminTable<UserRow>
          path="/admin/users/"
          columns={[
            { header: 'Email', cell: (r) => r.email },
            { header: 'Name', cell: (r) => r.name },
            { header: 'Super', cell: (r) => (r.is_superuser ? 'Yes' : '') },
            { header: 'Active', cell: (r) => (r.is_active ? 'Yes' : 'No') },
            { header: 'Agents', cell: (r) => r.agent_count },
            { header: 'OpenReview', cell: (r) => r.openreview_id ?? '' },
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
