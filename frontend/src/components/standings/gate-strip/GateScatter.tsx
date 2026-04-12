'use client';

import { useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import type { StandingsEntry, StandingsResponse } from '../lib/types';
import { classifyGateReason } from '../lib/gate-reasons';

interface GateScatterProps {
  data: StandingsResponse;
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
}

// Native SVG, no chart library. Log-x (n_verdicts), linear-y
// (gt_corr_composite). Agents with corr==None clamp to y=-1.05 with a
// striped marker so they're visibly "not measured" rather than "measured
// worst". Clicking a dot dispatches selection via `onSelect`.
export function GateScatter({ data, selectedAgentId, onSelect }: GateScatterProps) {
  const VIEW_W = 600;
  const VIEW_H = 320;
  const PAD_L = 36;
  const PAD_R = 12;
  const PAD_T = 12;
  const PAD_B = 36;

  const plotW = VIEW_W - PAD_L - PAD_R;
  const plotH = VIEW_H - PAD_T - PAD_B;

  // X scale: log10(max(1, verdicts)). Floor at verdict threshold * 10 so the
  // threshold line never collapses against the right edge on a platform
  // that has a single dominant agent.
  const maxV = useMemo(() => {
    const m = data.entries.reduce(
      (acc, e) => (e.n_verdicts > acc ? e.n_verdicts : acc),
      0,
    );
    return Math.max(m, data.gate_min_verdicts * 10);
  }, [data.entries, data.gate_min_verdicts]);
  const xMaxLog = Math.log10(Math.max(1, maxV));

  const xOf = (v: number) => {
    const log = Math.log10(Math.max(1, v));
    return PAD_L + (log / xMaxLog) * plotW;
  };
  // Y scale: -1 at bottom, +1 at top, with a small pinned-to-axis band
  // below -1 for corr=null entries.
  const yOf = (corr: number) => {
    const clamped = Math.max(-1, Math.min(1, corr));
    return PAD_T + ((1 - clamped) / 2) * plotH;
  };
  const Y_NULL = PAD_T + plotH + 8; // below axis; clamped to viewBox via clip

  const xThreshold = xOf(data.gate_min_verdicts);
  const yZero = yOf(0);
  const yGateCorr = yOf(data.gate_min_corr);

  const passRegionLeft = xThreshold;
  const passRegionTop = PAD_T;
  const passRegionW = PAD_L + plotW - xThreshold;
  const passRegionH = yGateCorr - PAD_T;

  const xTicks = [1, 10, data.gate_min_verdicts, 100, 500, 1000].filter(
    t => t <= maxV,
  );
  const yTicks = [1, 0.5, 0, -0.5, -1];

  const [hover, setHover] = useState<{
    entry: StandingsEntry;
    x: number;
    y: number;
  } | null>(null);

  return (
    <div className="relative w-full">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={`Scatter of ${data.entries.length} agents: verdict count on the x axis (log), composite GT correlation on the y axis. Pass region is verdicts >= ${data.gate_min_verdicts} AND correlation > ${data.gate_min_corr}.`}
        className="w-full h-auto"
      >
        <defs>
          <pattern
            id="gate-scatter-null-stripe"
            width="4"
            height="4"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="4" height="4" fill="rgb(148 163 184)" />
            <rect width="1" height="4" fill="white" />
          </pattern>
        </defs>

        <rect
          x={passRegionLeft}
          y={passRegionTop}
          width={passRegionW}
          height={passRegionH}
          fill="rgb(16 185 129)"
          fillOpacity={0.1}
          data-testid="pass-region"
        />

        <line
          x1={PAD_L}
          y1={yZero}
          x2={VIEW_W - PAD_R}
          y2={yZero}
          stroke="currentColor"
          strokeOpacity={0.3}
          strokeDasharray="2 3"
        />
        <line
          x1={xThreshold}
          y1={PAD_T}
          x2={xThreshold}
          y2={PAD_T + plotH}
          stroke="rgb(16 185 129)"
          strokeOpacity={0.6}
          strokeDasharray="3 3"
        />

        <line
          x1={PAD_L}
          y1={PAD_T}
          x2={PAD_L}
          y2={PAD_T + plotH}
          stroke="currentColor"
          strokeOpacity={0.4}
        />
        <line
          x1={PAD_L}
          y1={PAD_T + plotH}
          x2={VIEW_W - PAD_R}
          y2={PAD_T + plotH}
          stroke="currentColor"
          strokeOpacity={0.4}
        />

        {xTicks.map(t => (
          <g key={`xt-${t}`}>
            <line
              x1={xOf(t)}
              y1={PAD_T + plotH}
              x2={xOf(t)}
              y2={PAD_T + plotH + 4}
              stroke="currentColor"
              strokeOpacity={0.4}
            />
            <text
              x={xOf(t)}
              y={PAD_T + plotH + 16}
              textAnchor="middle"
              fontSize="10"
              fill="currentColor"
              fillOpacity={0.6}
            >
              {t}
            </text>
          </g>
        ))}
        {yTicks.map(t => (
          <g key={`yt-${t}`}>
            <line
              x1={PAD_L - 4}
              y1={yOf(t)}
              x2={PAD_L}
              y2={yOf(t)}
              stroke="currentColor"
              strokeOpacity={0.4}
            />
            <text
              x={PAD_L - 6}
              y={yOf(t) + 3}
              textAnchor="end"
              fontSize="10"
              fill="currentColor"
              fillOpacity={0.6}
            >
              {t > 0 ? `+${t}` : t}
            </text>
          </g>
        ))}

        <text
          x={PAD_L + plotW / 2}
          y={VIEW_H - 4}
          textAnchor="middle"
          fontSize="11"
          fill="currentColor"
          fillOpacity={0.6}
        >
          verdicts (log)
        </text>
        <text
          x={10}
          y={PAD_T + plotH / 2}
          textAnchor="middle"
          fontSize="11"
          fill="currentColor"
          fillOpacity={0.6}
          transform={`rotate(-90 10 ${PAD_T + plotH / 2})`}
        >
          GT correlation
        </text>

        {data.entries.map(e => {
          const isNull = e.gt_corr_composite == null;
          const x = xOf(Math.max(1, e.n_verdicts));
          const y = isNull ? Y_NULL : yOf(e.gt_corr_composite as number);
          const kind = classifyGateReason(e);
          const fill = isNull
            ? 'url(#gate-scatter-null-stripe)'
            : kind === 'pass'
              ? 'rgb(16 185 129)'
              : kind === 'neg_corr'
                ? 'rgb(239 68 68)'
                : kind === 'no_gt'
                  ? 'rgb(148 163 184)'
                  : 'rgb(245 158 11)';
          const isSelected = e.agent_id === selectedAgentId;
          return (
            <circle
              key={e.agent_id}
              data-testid="scatter-dot"
              data-agent-id={e.agent_id}
              data-gate-kind={kind}
              data-corr-null={isNull ? 'true' : 'false'}
              cx={x}
              cy={y}
              r={isSelected ? 6 : 4}
              fill={fill}
              stroke={isSelected ? 'black' : 'white'}
              strokeWidth={isSelected ? 2 : 1}
              className="cursor-pointer transition-[r] motion-reduce:transition-none"
              onClick={() => onSelect(e.agent_id)}
              onMouseEnter={() => setHover({ entry: e, x, y })}
              onMouseLeave={() => setHover(null)}
            />
          );
        })}
      </svg>

      {hover && (
        <div
          className={cn(
            'pointer-events-none absolute z-10 rounded-md border border-border bg-background px-2 py-1 text-xs shadow-md',
            'max-w-[240px]',
          )}
          style={{
            left: `${(hover.x / VIEW_W) * 100}%`,
            top: `${(hover.y / VIEW_H) * 100}%`,
            transform: 'translate(-50%, -120%)',
          }}
        >
          <div className="font-semibold truncate">{hover.entry.agent_name}</div>
          <div className="tabular-nums text-muted-foreground">
            {hover.entry.n_verdicts} verdicts ·{' '}
            {hover.entry.gt_corr_composite == null
              ? 'corr: n/a'
              : `corr: ${hover.entry.gt_corr_composite.toFixed(2)}`}
          </div>
          {!hover.entry.passed_gate && (
            <div className="text-xs text-muted-foreground">
              distance: {hover.entry.distance_to_clear.toFixed(2)}
            </div>
          )}
        </div>
      )}

      {/* Visually-hidden table fallback for screen readers. */}
      <table className="sr-only">
        <caption>
          Agent gate positions. {data.n_passers} past the gate;{' '}
          {data.n_failers} excluded.
        </caption>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Verdicts</th>
            <th>GT correlation</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {data.entries.map(e => (
            <tr key={e.agent_id}>
              <td>{e.agent_name}</td>
              <td>{e.n_verdicts}</td>
              <td>
                {e.gt_corr_composite == null
                  ? 'n/a'
                  : e.gt_corr_composite.toFixed(2)}
              </td>
              <td>{e.passed_gate ? 'passer' : 'failer'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
