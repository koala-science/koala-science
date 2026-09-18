/**
 * "3d ago", with the full date on hover. The one way a timestamp is shown.
 *
 * The relative text depends on the clock, so server and browser can disagree
 * by a unit at a boundary; the warning for that is suppressed rather than the
 * text being rendered client-only, which would flash.
 */

import { formatFullDate, timeAgo } from '@/lib/utils';

export function RelativeTime({ date, className }: { date: string; className?: string }) {
  return (
    <time dateTime={date} title={formatFullDate(date)} className={className} suppressHydrationWarning>
      {timeAgo(date)}
    </time>
  );
}
