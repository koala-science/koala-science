'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { formatDate } from '@/lib/utils';

interface UserRow {
  id: string;
  email: string;
  name: string;
  is_superuser: boolean;
  is_active: boolean;
  orcid_id: string | null;
  openreview_ids: string[];
  agent_count: number;
  created_at: string;
}

export default function AdminUsersPage() {
  return (
    <AdminGate>
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <Link href="/admin" className="text-sm text-muted-foreground hover:underline">
              ← Admin
            </Link>
            <h1 className="font-heading text-3xl font-bold mt-1">Users</h1>
          </div>
        </header>

        <AdminTable<UserRow>
          path="/admin/users/"
          columns={[
            { header: 'Email', cell: (r) => r.email },
            { header: 'Name', cell: (r) => r.name },
            { header: 'Super', cell: (r) => (r.is_superuser ? 'Yes' : '') },
            { header: 'Active', cell: (r) => (r.is_active ? 'Yes' : 'No') },
            { header: 'Agents', cell: (r) => r.agent_count },
            { header: 'OpenReview', cell: (r) => r.openreview_ids.join(', ') },
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
