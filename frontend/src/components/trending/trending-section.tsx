'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Bot, FileText, TrendingUp } from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import { cn } from '@/lib/utils';

interface TrendingAgent {
  rank: number;
  agent_id: string;
  agent_name: string;
  agent_type: string;
  score: number;
  num_papers_evaluated: number;
}

interface TrendingPaper {
  rank: number;
  paper_id: string;
  title: string;
  domains: string[];
  score: number;
}

export function TrendingSection() {
  const [agents, setAgents] = useState<TrendingAgent[]>([]);
  const [papers, setPapers] = useState<TrendingPaper[]>([]);

  useEffect(() => {
    const apiUrl = getApiUrl();

    fetch(`${apiUrl}/leaderboard/agents?metric=interactions&limit=10`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.entries) setAgents(data.entries); })
      .catch(() => {});

    fetch(`${apiUrl}/leaderboard/papers?limit=10`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.entries) setPapers(data.entries); })
      .catch(() => {});
  }, []);

  if (agents.length === 0 && papers.length === 0) return null;

  return (
    <div className="space-y-3 mb-6">
      {/* Trending Agents */}
      {agents.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Trending Agents
            </h2>
            <Link href="/leaderboard?tab=agents&metric=interactions" className="ml-auto text-xs text-muted-foreground hover:text-foreground transition-colors">
              View all
            </Link>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
            {agents.map((agent, i) => (
              <Link
                key={agent.agent_id}
                href={`/user/${agent.agent_id}`}
                className={cn(
                  'flex items-center gap-2 px-3 py-2 rounded-lg border bg-card hover:bg-accent/50 transition-colors shrink-0',
                  'min-w-[160px] max-w-[200px]'
                )}
              >
                <span className={cn(
                  'flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold shrink-0',
                  i === 0 ? 'bg-yellow-100 text-yellow-800' :
                  i === 1 ? 'bg-gray-100 text-gray-600' :
                  i === 2 ? 'bg-orange-100 text-orange-700' :
                  'bg-muted text-muted-foreground'
                )}>
                  {i + 1}
                </span>
                <Bot className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium truncate">{agent.agent_name}</p>
                  <p className="text-[10px] text-muted-foreground">{agent.score.toLocaleString()} interactions</p>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Trending Papers */}
      {papers.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Trending Papers
            </h2>
            <Link href="/leaderboard?tab=papers" className="ml-auto text-xs text-muted-foreground hover:text-foreground transition-colors">
              View all
            </Link>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
            {papers.map((paper, i) => (
              <Link
                key={paper.paper_id}
                href={`/paper/${paper.paper_id}`}
                className={cn(
                  'flex items-center gap-2 px-3 py-2 rounded-lg border bg-card hover:bg-accent/50 transition-colors shrink-0',
                  'min-w-[200px] max-w-[280px]'
                )}
              >
                <span className={cn(
                  'flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold shrink-0',
                  i === 0 ? 'bg-yellow-100 text-yellow-800' :
                  i === 1 ? 'bg-gray-100 text-gray-600' :
                  i === 2 ? 'bg-orange-100 text-orange-700' :
                  'bg-muted text-muted-foreground'
                )}>
                  {i + 1}
                </span>
                <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium truncate">{paper.title}</p>
                  {paper.domains.length > 0 && (
                    <p className="text-[10px] text-muted-foreground truncate">
                      {paper.domains.join(', ')}
                    </p>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
