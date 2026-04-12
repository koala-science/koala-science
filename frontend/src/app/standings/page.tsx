import { redirect } from 'next/navigation';

export default function StandingsRedirectPage() {
  redirect('/metrics?tab=standings');
}
