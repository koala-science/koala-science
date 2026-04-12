'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { getApiUrl } from '@/lib/api';
import { AlertTriangle, Play, RotateCcw, CheckSquare, Square, ChevronDown, ChevronRight } from 'lucide-react';

const API = getApiUrl();

function adminFetch(path: string, options: RequestInit = {}) {
  return fetch(`${API}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Basic ' + btoa('admin:admin123'),
      ...options.headers,
    },
  });
}

// --- Types ---

interface ResetGroup {
  label: string;
  description: string;
  items: string[];
}

interface ResetAction {
  label: string;
  description: string;
}

interface TriggerAction {
  label: string;
  description: string;
  type: 'script' | 'workflow';
}

// --- Main Page ---

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await fetch(`${API}/admin/stats`, {
      headers: { 'Authorization': 'Basic ' + btoa(`${username}:${password}`) },
    });
    if (res.ok) {
      // Store creds for subsequent requests
      (window as any).__adminAuth = btoa(`${username}:${password}`);
      setAuthed(true);
      setError('');
    } else {
      setError('Invalid credentials');
    }
  };

  if (!authed) {
    return (
      <div className="max-w-sm mx-auto mt-20">
        <h1 className="text-2xl font-bold mb-6">Admin</h1>
        <form onSubmit={handleLogin} className="space-y-4">
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full border rounded px-3 py-2 text-sm"
            autoFocus
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border rounded px-3 py-2 text-sm"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" className="w-full">Login</Button>
        </form>
      </div>
    );
  }

  return <AdminDashboard />;
}

function AdminDashboard() {
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [groups, setGroups] = useState<Record<string, ResetGroup>>({});
  const [actions, setActions] = useState<Record<string, ResetAction>>({});
  const [triggers, setTriggers] = useState<Record<string, TriggerAction>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['papers', 'agent_activity', 'paper_data', 'domain_data', 'platform_data', 'agent_identity']));
  const [resetting, setResetting] = useState(false);
  const [resetResult, setResetResult] = useState<any>(null);
  const [triggerResults, setTriggerResults] = useState<Record<string, any>>({});
  const [runningTriggers, setRunningTriggers] = useState<Set<string>>(new Set());

  useEffect(() => {
    adminFetch('/admin/stats').then(r => r.json()).then(setStats);
    adminFetch('/admin/reset-options').then(r => r.json()).then(data => {
      setGroups(data.groups);
      setActions(data.actions);
    });
    adminFetch('/admin/trigger-options').then(r => r.json()).then(setTriggers);
  }, []);

  const toggleItem = (key: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleGroup = (groupKey: string) => {
    const group = groups[groupKey];
    if (!group) return;
    const allSelected = group.items.every(i => selected.has(i));
    setSelected(prev => {
      const next = new Set(prev);
      group.items.forEach(i => allSelected ? next.delete(i) : next.add(i));
      return next;
    });
  };

  const toggleExpand = (groupKey: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  };

  const selectAll = () => {
    setSelected(new Set(Object.keys(actions)));
  };

  const selectNone = () => {
    setSelected(new Set());
  };

  const handleReset = async () => {
    if (selected.size === 0) return;
    if (!confirm(`Are you sure you want to reset ${selected.size} item(s)? This cannot be undone.`)) return;

    setResetting(true);
    setResetResult(null);
    try {
      const res = await adminFetch('/admin/reset', {
        method: 'POST',
        body: JSON.stringify(Array.from(selected)),
      });
      const data = await res.json();
      setResetResult(data);
      // Refresh stats
      adminFetch('/admin/stats').then(r => r.json()).then(setStats);
      setSelected(new Set());
    } catch (err) {
      setResetResult({ error: String(err) });
    } finally {
      setResetting(false);
    }
  };

  const handleTrigger = async (action: string) => {
    setRunningTriggers(prev => new Set(prev).add(action));
    setTriggerResults(prev => ({ ...prev, [action]: null }));
    try {
      const res = await adminFetch(`/admin/trigger/${action}`, { method: 'POST' });
      const data = await res.json();
      setTriggerResults(prev => ({ ...prev, [action]: data }));
      // Refresh stats after scripts
      if (triggers[action]?.type === 'script') {
        adminFetch('/admin/stats').then(r => r.json()).then(setStats);
      }
    } catch (err) {
      setTriggerResults(prev => ({ ...prev, [action]: { error: String(err) } }));
    } finally {
      setRunningTriggers(prev => {
        const next = new Set(prev);
        next.delete(action);
        return next;
      });
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <header>
        <h1 className="font-heading text-3xl font-bold">Admin</h1>
        <p className="text-muted-foreground">Reset data and trigger on-demand workflows.</p>
      </header>

      {/* Stats */}
      {stats && (
        <section className="border p-6 rounded shadow-sm bg-white">
          <h2 className="text-xl font-semibold mb-4 border-b pb-2">Database Stats</h2>
          <div className="grid grid-cols-3 md:grid-cols-5 gap-3">
            {Object.entries(stats).map(([key, count]) => (
              <div key={key} className="text-center p-2 bg-gray-50 rounded">
                <div className="text-lg font-bold">{count.toLocaleString()}</div>
                <div className="text-[11px] text-muted-foreground">{key.replace(/_/g, ' ')}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Reset Section */}
      <section className="border p-6 rounded shadow-sm bg-white">
        <div className="flex items-center justify-between mb-4 border-b pb-2">
          <div>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              Reset Data
            </h2>
            <p className="text-xs text-muted-foreground mt-1">Select items to delete. Users, agents, papers, and domains are never deleted.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={selectAll} className="text-xs">Select All</Button>
            <Button variant="ghost" size="sm" onClick={selectNone} className="text-xs">Clear</Button>
          </div>
        </div>

        <div className="space-y-2">
          {Object.entries(groups).map(([groupKey, group]) => {
            const allSelected = group.items.every(i => selected.has(i));
            const someSelected = group.items.some(i => selected.has(i));
            const isExpanded = expanded.has(groupKey);

            return (
              <div key={groupKey} className="border rounded">
                <div
                  className="flex items-center gap-2 px-4 py-3 bg-gray-50 cursor-pointer select-none hover:bg-gray-100 transition-colors"
                  onClick={() => toggleExpand(groupKey)}
                >
                  {isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleGroup(groupKey); }}
                    className="flex items-center"
                  >
                    {allSelected ? (
                      <CheckSquare className="h-4 w-4 text-primary" />
                    ) : someSelected ? (
                      <div className="h-4 w-4 border-2 border-primary rounded-sm bg-primary/20" />
                    ) : (
                      <Square className="h-4 w-4 text-muted-foreground" />
                    )}
                  </button>
                  <div className="flex-1">
                    <span className="text-sm font-semibold">{group.label}</span>
                    <span className="text-xs text-muted-foreground ml-2">{group.description}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {group.items.filter(i => selected.has(i)).length}/{group.items.length}
                  </span>
                </div>

                {isExpanded && (
                  <div className="divide-y">
                    {group.items.map(itemKey => {
                      const action = actions[itemKey];
                      if (!action) return null;
                      const isSelected = selected.has(itemKey);

                      return (
                        <label
                          key={itemKey}
                          className="flex items-start gap-3 px-4 py-3 pl-12 cursor-pointer hover:bg-gray-50 transition-colors"
                        >
                          <button onClick={() => toggleItem(itemKey)} className="mt-0.5">
                            {isSelected ? (
                              <CheckSquare className="h-4 w-4 text-primary" />
                            ) : (
                              <Square className="h-4 w-4 text-muted-foreground" />
                            )}
                          </button>
                          <div>
                            <div className="text-sm font-medium">{action.label}</div>
                            <div className="text-xs text-muted-foreground">{action.description}</div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            {selected.size} item{selected.size !== 1 ? 's' : ''} selected
          </div>
          <Button
            variant="destructive"
            disabled={selected.size === 0 || resetting}
            onClick={handleReset}
          >
            <RotateCcw className="h-4 w-4 mr-2" />
            {resetting ? 'Resetting...' : `Reset ${selected.size} Item${selected.size !== 1 ? 's' : ''}`}
          </Button>
        </div>

        {resetResult && (
          <div className={`mt-4 p-4 rounded text-sm ${resetResult.error ? 'bg-red-50 text-red-800' : 'bg-green-50 text-green-800'}`}>
            {resetResult.error ? (
              <p>Error: {resetResult.error}</p>
            ) : (
              <div>
                <p className="font-semibold mb-2">Reset complete — {resetResult.total_rows_affected} rows affected. Refresh other open tabs to see changes.</p>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-1 text-xs">
                  {Object.entries(resetResult.reset || {}).map(([key, count]) => (
                    <span key={key}>{key}: {String(count)}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Triggers Section */}
      <section className="border p-6 rounded shadow-sm bg-white">
        <h2 className="text-xl font-semibold mb-4 border-b pb-2 flex items-center gap-2">
          <Play className="h-5 w-5 text-primary" />
          On-Demand Triggers
        </h2>
        <p className="text-xs text-muted-foreground mb-4">Run scripts or trigger Temporal workflows manually.</p>

        <div className="space-y-3">
          {Object.entries(triggers).map(([key, trigger]) => {
            const isRunning = runningTriggers.has(key);
            const result = triggerResults[key];

            return (
              <div key={key} className="border rounded p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold">{trigger.label}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        trigger.type === 'workflow'
                          ? 'bg-purple-100 text-purple-700'
                          : 'bg-blue-100 text-blue-700'
                      }`}>
                        {trigger.type}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{trigger.description}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isRunning}
                    onClick={() => handleTrigger(key)}
                  >
                    <Play className="h-3 w-3 mr-1" />
                    {isRunning ? 'Running...' : 'Run'}
                  </Button>
                </div>

                {result && (
                  <div className={`mt-3 p-3 rounded text-xs ${
                    result.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
                  }`}>
                    {result.error && <p>Error: {result.error}</p>}
                    {result.workflow_id && <p>Workflow ID: <code className="font-mono">{result.workflow_id}</code></p>}
                    {result.output && (
                      <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] bg-white/60 p-2 rounded">
                        {result.output}
                      </pre>
                    )}
                    {result.exit_code !== undefined && (
                      <p className="mt-1">Exit code: {result.exit_code}</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
