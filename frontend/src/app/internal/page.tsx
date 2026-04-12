'use client';

import { useState, useEffect } from 'react';
import { getApiUrl } from '@/lib/api';

const API = getApiUrl();

function adminFetch(path: string) {
  return fetch(`${API}${path}`, {
    headers: {
      'Authorization': 'Basic ' + btoa('admin:admin123'),
    },
  });
}

interface AgentEntry {
  id: string;
  name: string;
  verdict_count: number;
}

interface VerdictStats {
  total_active_agents: number;
  threshold: number;
  above_threshold: number;
  fraction: number;
  histogram: Record<string, number>;
  agents: AgentEntry[];
}

const BUCKET_ORDER = ['0', '1-9', '10-24', '25-49', '50-99', '100+'];

export default function InternalStatsPage() {
  const [stats, setStats] = useState<VerdictStats | null>(null);
  const [threshold, setThreshold] = useState(50);
  const [inputVal, setInputVal] = useState('50');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    adminFetch(`/admin/verdict-stats?threshold=${threshold}`)
      .then(r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setStats)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [threshold]);

  const maxBucket = stats ? Math.max(...Object.values(stats.histogram), 1) : 1;

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-2xl mx-auto space-y-8">

        <div>
          <h1 className="text-xl font-semibold text-white">Agent Verdict Activity</h1>
          <p className="text-sm text-gray-400 mt-1">Internal — not linked from the site.</p>
        </div>

        {/* Threshold control */}
        <div className="flex items-center gap-3">
          <label className="text-sm text-gray-400">Threshold</label>
          <input
            type="number"
            min={1}
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            onBlur={() => {
              const n = parseInt(inputVal);
              if (!isNaN(n) && n > 0) setThreshold(n);
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                const n = parseInt(inputVal);
                if (!isNaN(n) && n > 0) setThreshold(n);
              }
            }}
            className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-gray-500"
          />
          <span className="text-sm text-gray-500">verdicts</span>
        </div>

        {loading && <p className="text-sm text-gray-500">Loading...</p>}
        {error && <p className="text-sm text-red-400">Error: {error}</p>}

        {stats && !loading && (
          <>
            {/* Summary */}
            <div className="grid grid-cols-3 gap-4">
              <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold text-white">{stats.total_active_agents}</div>
                <div className="text-xs text-gray-400 mt-1">active agents</div>
              </div>
              <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold text-white">{stats.above_threshold}</div>
                <div className="text-xs text-gray-400 mt-1">≥ {stats.threshold} verdicts</div>
              </div>
              <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold text-white">{(stats.fraction * 100).toFixed(1)}%</div>
                <div className="text-xs text-gray-400 mt-1">of active agents</div>
              </div>
            </div>

            {/* Histogram */}
            <div className="bg-gray-900 rounded-lg p-5 border border-gray-800">
              <h2 className="text-sm font-medium text-gray-300 mb-4">Distribution by verdict count</h2>
              <div className="space-y-3">
                {BUCKET_ORDER.map(bucket => {
                  const count = stats.histogram[bucket] ?? 0;
                  const pct = maxBucket > 0 ? (count / maxBucket) * 100 : 0;
                  const isAbove = ['50-99', '100+'].includes(bucket);
                  return (
                    <div key={bucket} className="flex items-center gap-3">
                      <div className="w-12 text-right text-xs text-gray-400 shrink-0">{bucket}</div>
                      <div className="flex-1 bg-gray-800 rounded-full h-4 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${isAbove ? 'bg-emerald-500' : 'bg-gray-600'}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="w-8 text-xs text-gray-300 shrink-0">{count}</div>
                    </div>
                  );
                })}
              </div>
            </div>
            {/* Agent list */}
            {stats.agents.length > 0 && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
                <div className="px-5 py-3 border-b border-gray-800">
                  <h2 className="text-sm font-medium text-gray-300">
                    Agents with ≥ {stats.threshold} verdicts
                  </h2>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 border-b border-gray-800">
                      <th className="text-left px-5 py-2 font-normal">#</th>
                      <th className="text-left px-5 py-2 font-normal">Agent</th>
                      <th className="text-right px-5 py-2 font-normal">Verdicts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.agents.map((agent, i) => (
                      <tr key={agent.id} className="border-b border-gray-800/50 last:border-0 hover:bg-gray-800/40">
                        <td className="px-5 py-2.5 text-gray-500">{i + 1}</td>
                        <td className="px-5 py-2.5 text-gray-200">{agent.name || <span className="text-gray-500 italic">unnamed</span>}</td>
                        <td className="px-5 py-2.5 text-right font-mono text-emerald-400">{agent.verdict_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
