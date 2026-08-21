import Link from 'next/link';
import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <main
      className="flex items-center justify-center min-h-[70vh] px-4"
      role="main"
      aria-label="Page not found"
    >
      <div className="w-full max-w-md text-center space-y-6">
        <img
          src="/koala.png"
          alt=""
          className="h-20 w-20 mx-auto opacity-80"
        />
        <div className="space-y-2">
          <p className="font-heading text-6xl sm:text-7xl font-bold tracking-tight text-muted-foreground/40">
            404
          </p>
          <h1 className="font-heading text-2xl sm:text-3xl font-bold">
            This page wandered off
          </h1>
          <p className="text-muted-foreground">
            The page you&apos;re looking for doesn&apos;t exist or has moved.
          </p>
        </div>
        <div className="flex flex-col sm:flex-row gap-2 justify-center pt-2">
          <Link href="/papers">
            <Button className="w-full sm:w-auto rounded-full px-5">
              Back to feed
            </Button>
          </Link>
          <Link href="/search">
            <Button variant="outline" className="w-full sm:w-auto rounded-full px-5">
              Search papers
            </Button>
          </Link>
        </div>
      </div>
    </main>
  );
}
