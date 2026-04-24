import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatThousands(n: number): string {
  // Locale-independent thousands separator so SSR (Node ICU) and client
  // (browser ICU) render identical strings — avoids hydration mismatch.
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function formatDate(dateStr: string): string {
  // Date-only, hydration-safe (see formatFullDate).
  const normalized = dateStr.includes('Z') || dateStr.includes('+') ? dateStr : dateStr + 'Z';
  const d = new Date(normalized);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

export function formatFullDate(dateStr: string): string {
  // Formatted manually so server (Node ICU) and client (browser ICU) render
  // byte-identical strings — `toLocaleString` differs between them (e.g.
  // Node "Apr 23, 2026, 9:53 PM" vs Chrome "Apr 23, 2026 at 9:53 PM") and
  // trips React hydration.
  const normalized = dateStr.includes('Z') || dateStr.includes('+') ? dateStr : dateStr + 'Z';
  const d = new Date(normalized);
  const month = MONTHS[d.getUTCMonth()];
  const day = d.getUTCDate();
  const year = d.getUTCFullYear();
  const h24 = d.getUTCHours();
  const hour = ((h24 + 11) % 12) + 1;
  const minute = String(d.getUTCMinutes()).padStart(2, '0');
  const meridiem = h24 < 12 ? 'AM' : 'PM';
  return `${month} ${day}, ${year}, ${hour}:${minute} ${meridiem} UTC`;
}

export function timeAgo(dateStr: string): string {
  // Append Z if no timezone info — server returns naive UTC timestamps
  const normalized = dateStr.includes('Z') || dateStr.includes('+') ? dateStr : dateStr + 'Z';
  const seconds = Math.floor((Date.now() - new Date(normalized).getTime()) / 1000);
  if (seconds < 0) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}
