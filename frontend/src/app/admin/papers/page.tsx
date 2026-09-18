'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { PageShell, PageTitle } from '@/components/shared/page';
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
      <PageShell width="wide">
        <div>
          <Link href="/admin" className="text-sm text-muted-foreground hover:text-foreground">
            ← Admin
          </Link>
          <PageTitle className="mt-1">Papers</PageTitle>
        </div>

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
            { header: 'Agents', cell: (r) => r.reviewer_count },
            { header: 'Arguments', cell: (r) => r.argument_count },
            {
              header: 'Released',
              cell: (r) => r.released_at ? formatDate(r.released_at) : '—',
            },
          ]}
        />
      </PageShell>
    </AdminGate>
  );
}
