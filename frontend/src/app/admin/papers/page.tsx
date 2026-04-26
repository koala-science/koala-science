'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { apiCall } from '@/lib/api';
import { formatDate } from '@/lib/utils';

interface PaperRow {
  id: string;
  title: string;
  status: string;
  submitter_id: string;
  submitter_name: string | null;
  comment_count: number;
  verdict_count: number;
  reviewer_count: number;
  released_at: string | null;
}

const NEXT_STATUS: Record<string, string> = {
  in_review: 'deliberating',
  deliberating: 'reviewed',
};

async function advancePaper(row: PaperRow) {
  const next = NEXT_STATUS[row.status];
  if (!next) return;
  const ok = window.confirm(
    `Advance "${row.title}" from ${row.status} to ${next}? This is irreversible.`,
  );
  if (!ok) return;
  try {
    await apiCall(`/admin/papers/${row.id}/advance`, { method: 'POST' });
    window.location.reload();
  } catch (e) {
    window.alert(`Advance failed: ${(e as Error).message}`);
  }
}

function AdvanceCell({ row }: { row: PaperRow }) {
  const next = NEXT_STATUS[row.status];
  if (!next) return <span className="text-muted-foreground">—</span>;
  return (
    <button
      onClick={() => advancePaper(row)}
      className="text-primary hover:underline"
    >
      → {next}
    </button>
  );
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
            { header: 'Reviewers', cell: (r) => r.reviewer_count },
            { header: 'Comments', cell: (r) => r.comment_count },
            { header: 'Verdicts', cell: (r) => r.verdict_count },
            {
              header: 'Released',
              cell: (r) => r.released_at ? formatDate(r.released_at) : '—',
            },
            { header: 'Action', cell: (r) => <AdvanceCell row={r} /> },
          ]}
        />
      </div>
    </AdminGate>
  );
}
