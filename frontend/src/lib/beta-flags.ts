// Beta-flag engine. The allowlist lives in frontend/beta-flags.json and is
// baked into the client bundle at build time. Gatekeepers edit that file via
// PR — the review history is the audit trail.
//
// Allow-list entries can take any of these forms:
//   "*"                                      everyone (use for GA rollout)
//   "<actor-id-uuid>"                        exact actor_id match
//   "name:<display_name>"                    exact name match (case-sensitive)
//   "type:human|delegated_agent|sovereign_agent"   any actor of this type
//
// To add a new flag:
//   1. Append an entry under "flags" in beta-flags.json with a description
//      and an allow list of identifiers from the list above.
//   2. Wrap the page / route with <BetaGate flag="yourflag"> and any nav
//      entries with <BetaVisible flag="yourflag">.
//   3. Call useBetaFlag("yourflag") anywhere you need an imperative check.
//
// Local dev: set NEXT_PUBLIC_BETA_ALL_ON=1 in frontend/.env.local to open
// every gate without editing the JSON.

import flagsFile from '../../beta-flags.json';

interface FlagConfig {
  description: string;
  allow: string[];
}

interface FlagsFile {
  _readme?: string;
  flags: Record<string, FlagConfig>;
}

export interface BetaUser {
  actor_id: string;
  actor_type: string;
  name: string;
}

const FLAGS: FlagsFile = flagsFile as FlagsFile;
const ALL_ON = process.env.NEXT_PUBLIC_BETA_ALL_ON === '1';

function matchesEntry(entry: string, user: BetaUser | null): boolean {
  if (entry === '*') return true;
  if (!user) return false;
  if (entry.startsWith('name:')) return user.name === entry.slice(5);
  if (entry.startsWith('type:')) return user.actor_type === entry.slice(5);
  return entry === user.actor_id;
}

export function isBetaAllowed(flag: string, user: BetaUser | null): boolean {
  if (ALL_ON) return true;
  const cfg = FLAGS.flags[flag];
  if (!cfg || !Array.isArray(cfg.allow)) return false;
  return cfg.allow.some((entry) => matchesEntry(entry, user));
}

export function listBetaFlags(): Array<{ flag: string } & FlagConfig> {
  return Object.entries(FLAGS.flags).map(([flag, cfg]) => ({ flag, ...cfg }));
}
