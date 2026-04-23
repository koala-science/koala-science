'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';

interface PaperRow {
  id: string;
  title: string;
  status: string;
  submitter_id: string;
  submitter_name: string | null;
  comment_count: number;
  verdict_count: number;
  created_at: string;
}

export default function AdminPapersPage() {
  return (
    <AdminGate>
      <div className="max-w-6xl mx-auto space-y-6">
        <header>
          <Link href="/admin" className="text-sm text-muted-foreground hover:underline">
            ← Admin
          </Link>
          <h1 className="font-heading text-3xl font-bold mt-1">Papers</h1>
        </header>

        <AdminTable<PaperRow>
          path="/admin/papers/"
          columns={[
            { header: 'Title', cell: (r) => r.title },
            { header: 'Status', cell: (r) => r.status },
            { header: 'Submitter', cell: (r) => r.submitter_name || '—' },
            { header: 'Comments', cell: (r) => r.comment_count },
            { header: 'Verdicts', cell: (r) => r.verdict_count },
            {
              header: 'Created',
              cell: (r) => new Date(r.created_at).toLocaleDateString(),
            },
          ]}
        />
      </div>
    </AdminGate>
  );
}
