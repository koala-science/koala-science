'use client';

import Link from 'next/link';
import { AdminGate } from '@/components/admin/admin-gate';
import { AdminTable } from '@/components/admin/admin-table';
import { formatDate } from '@/lib/utils';

interface CheckFlagRow {
  id: string;
  reason: string;
  flagger_id: string;
  flagger_name: string;
  check_id: string;
  check_name: string;
  check_version: string;
  check_status: string;
  argument_id: string;
  argument_claim: string;
  paper_id: string;
  paper_title: string;
  created_at: string;
}

export default function AdminCheckFlagsPage() {
  return (
    <AdminGate>
      <div className="max-w-6xl mx-auto space-y-6">
        <header>
          <Link href="/admin" className="text-sm text-muted-foreground hover:underline">
            ← Admin
          </Link>
          <h1 className="font-heading text-3xl font-bold mt-1">Flagged checks</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Where a reader says a check got an argument wrong. Reasons are private to this page.
          </p>
        </header>

        <AdminTable<CheckFlagRow>
          path="/admin/check-flags/"
          emptyMessage="No checks have been flagged."
          columns={[
            {
              header: 'Check',
              className: 'align-top whitespace-nowrap',
              cell: (r) => (
                <span className="font-mono text-xs">
                  {r.check_name}
                  <span className="text-muted-foreground"> @{r.check_version}</span>
                  <span
                    className={
                      r.check_status === 'failed' ? 'block text-red-700' : 'block text-green-700'
                    }
                  >
                    {r.check_status}
                  </span>
                </span>
              ),
            },
            {
              header: 'Argument',
              className: 'align-top',
              cell: (r) => (
                <Link href={`/p/${r.paper_id}`} className="text-primary hover:underline">
                  <span className="line-clamp-2">{r.argument_claim}</span>
                  <span className="block text-xs text-muted-foreground line-clamp-1">
                    {r.paper_title}
                  </span>
                </Link>
              ),
            },
            {
              header: 'Reason',
              className: 'align-top',
              cell: (r) => <span className="whitespace-pre-wrap">{r.reason}</span>,
            },
            {
              header: 'Flagged by',
              className: 'align-top whitespace-nowrap',
              cell: (r) => r.flagger_name,
            },
            {
              header: 'When',
              className: 'align-top whitespace-nowrap',
              cell: (r) => formatDate(r.created_at),
            },
          ]}
        />
      </div>
    </AdminGate>
  );
}
