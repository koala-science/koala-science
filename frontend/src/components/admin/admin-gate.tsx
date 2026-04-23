'use client';

import Link from 'next/link';
import { useAuthStore } from '@/lib/store';

export function AdminGate({ children }: { children: React.ReactNode }) {
  const hydrated = useAuthStore((s) => s.hydrated);
  const user = useAuthStore((s) => s.user);

  if (!hydrated) {
    return <div className="p-4 text-muted-foreground">Loading...</div>;
  }

  if (!user?.is_superuser) {
    return (
      <div className="max-w-md mx-auto mt-20 text-center space-y-4">
        <h1 className="font-heading text-2xl font-bold">Not authorized</h1>
        <p className="text-muted-foreground">This area is restricted to superusers.</p>
        <Link href="/" className="text-primary hover:underline">
          Return home
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}
