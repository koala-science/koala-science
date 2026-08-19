'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { formatDate } from '@/lib/utils';

interface PaperRow {
  id: string;
  title: string;
  submitter_id: string;
  submitter_name: string | null;
  argument_count: number;
  reviewer_count: number;
  released_at: string | null;
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
            {
              header: 'Title',
              cell: (r) => (
                <Link href={`/p/${r.id}`} className="text-primary hover:underline">
                  {r.title}
                </Link>
              ),
            },
            { header: 'Submitter', cell: (r) => r.submitter_name || '—' },
            { header: 'Reviewers', cell: (r) => r.reviewer_count },
            { header: 'Arguments', cell: (r) => r.argument_count },
            {
              header: 'Released',
              cell: (r) => r.released_at ? formatDate(r.released_at) : '—',
            },
          ]}
        />
      </div>
    </AdminGate>
  );
}
