import { FormEvent, useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import type { MemoryView, MonitorLanguage } from '../../app/monitorUi';
import { queryGraph } from '../../shared/api/monitor';
import type { GraphQueryEdge, GraphQueryNode, GraphQueryResponse } from '../../shared/api/types';
import type { GraphInspectTarget } from './GraphInspectPanel';
import { LoadingBlock } from '../../shared/components/PanelLoading';
import './knowledge-focus-panel.css';

export type KnowledgeFocusPanelProps = {
  focusTarget?: GraphInspectTarget;
  selectedSessionId?: string;
  focusQuery?: string;
  initialData?: GraphQueryResponse;
  onSelectNode?: (node: { id: string; label?: string | null }) => void;
  onSelectEdge?: (edge: { id: string; type?: string | null; source?: string | null; target?: string | null }) => void;
  onFocusQueryChange?: (query: string) => void;
  language?: MonitorLanguage;
  memoryView?: MemoryView;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function compactText(value: unknown, limit = 48, fallback = '-') {
  const normalized = text(value, fallback);
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
}

function preferredFocus(language: MonitorLanguage, focusTarget?: GraphInspectTarget, focusQuery?: string, selectedSessionId?: string) {
  if (focusQuery) {
    return { query: focusQuery, eyebrow: t(language, 'knowledge.linkedFocus'), title: compactText(focusQuery, 64, focusQuery) };
  }
  if (focusTarget?.label || focusTarget?.id) {
    return {
      query: text(focusTarget.label, focusTarget.id),
      eyebrow: focusTarget.kind === 'entity' ? t(language, 'knowledge.entityFocus') : t(language, 'knowledge.relationFocus'),
      title: compactText(focusTarget.label, 64, focusTarget.id),
    };
  }
  if (selectedSessionId) {
    return { query: selectedSessionId, eyebrow: t(language, 'knowledge.sessionFocus'), title: compactText(selectedSessionId, 64, selectedSessionId) };
  }
  return { query: 'sessions', eyebrow: t(language, 'knowledge.focus'), title: t(language, 'knowledge.currentConnectedMemory') };
}

function typeColor(value: unknown) {
  const palette = ['#0f766e', '#2563eb', '#7c3aed', '#b45309', '#be123c', '#0369a1', '#4d7c0f'];
  const source = text(value, 'node');
  let total = 0;
  for (let index = 0; index < source.length; index += 1) total += source.charCodeAt(index);
  return palette[total % palette.length];
}

type PositionedNode = GraphQueryNode & { cx: number; cy: number; radius: number };

function buildLayout(nodes: GraphQueryNode[], focusLabel: string): PositionedNode[] {
  if (!nodes.length) return [];
  const limited = nodes.slice(0, 9);
  const focusNeedle = focusLabel.trim().toLowerCase();
  const centerIndex = limited.findIndex((node) => {
    const label = text(node.label ?? node.name ?? node.id, '').trim().toLowerCase();
    return focusNeedle !== '' && (label === focusNeedle || text(node.id, '').trim().toLowerCase() === focusNeedle);
  });
  const centerNode = limited[Math.max(0, centerIndex)];
  const others = limited.filter((node) => node !== centerNode);
  const positioned: PositionedNode[] = [{ ...centerNode, cx: 170, cy: 150, radius: 34 }];
  others.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(others.length, 1);
    positioned.push({ ...node, cx: 170 + Math.cos(angle) * 105, cy: 150 + Math.sin(angle) * 105, radius: 24 });
  });
  return positioned;
}

function findPosition(positions: PositionedNode[], id: string | null | undefined) {
  if (!id) return undefined;
  return positions.find((node) => node.id === id);
}

function labelBoxWidth(label: string) {
  return Math.min(168, Math.max(58, label.length * 7 + 18));
}

export function KnowledgeFocusPanel({
  focusTarget,
  selectedSessionId,
  focusQuery,
  initialData,
  onSelectNode,
  onSelectEdge,
  onFocusQueryChange,
  language = 'en',
  memoryView = 'both',
}: KnowledgeFocusPanelProps) {
  const preferred = preferredFocus(language, focusTarget, focusQuery, selectedSessionId);
  const [draftQuery, setDraftQuery] = useState(preferred.query);
  const [focusHistory, setFocusHistory] = useState<string[]>([]);
  const [data, setData] = useState<GraphQueryResponse | undefined>(initialData);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setDraftQuery(preferred.query);
  }, [preferred.query]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError('');
      try {
        const payload = await queryGraph(preferred.query || 'sessions', 'search', 'sqlite', 24, memoryView);
        if (!cancelled) setData(payload);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [preferred.query, memoryView]);

  const nodes: GraphQueryNode[] = data?.nodes ?? [];
  const edges: GraphQueryEdge[] = data?.edges ?? data?.links ?? [];
  const positioned = buildLayout(nodes, preferred.query);
  const shownNodeIds = new Set(positioned.map((node) => node.id));
  const visibleEdges = edges.filter((edge) => shownNodeIds.has(text(edge.source, '')) && shownNodeIds.has(text(edge.target, ''))).slice(0, 12);

  if (loading && !data && !error) {
    return (
      <section className="knowledge-focus-panel" aria-busy="true">
        <div className="panel-heading">
          <p className="eyebrow">{preferred.eyebrow}</p>
          <h2>{preferred.title}</h2>
          <span>{t(language, 'common.loading')}...</span>
        </div>
        <div className="knowledge-focus-grid">
          <div className="knowledge-focus-canvas">
            <LoadingBlock lines={['title', 'long', 'default', 'long']} />
          </div>
          <div className="knowledge-focus-sidebar">
            {Array.from({ length: 4 }).map((_, index) => <LoadingBlock key={index} lines={['title', 'long', 'default']} />)}
          </div>
        </div>
      </section>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onFocusQueryChange?.(draftQuery.trim() || preferred.query);
  };

  const navigateToFocus = (nextQuery: string) => {
    const normalized = nextQuery.trim();
    if (!normalized || normalized === preferred.query) return;
    setFocusHistory((items) => [...items, preferred.query]);
    onFocusQueryChange?.(normalized);
  };

  const goBack = () => {
    setFocusHistory((items) => {
      const previous = items[items.length - 1];
      if (previous) onFocusQueryChange?.(previous);
      return items.slice(0, -1);
    });
  };

  return (
    <section className="knowledge-focus-panel" aria-busy={loading}>
      <div className="panel-heading">
        <p className="eyebrow">{preferred.eyebrow}</p>
        <h2>{preferred.title}</h2>
        <span>{positioned.length} nodes · {visibleEdges.length} edges</span>
      </div>

      <form className="knowledge-focus-form" onSubmit={submit}>
        <input value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} placeholder={t(language, 'knowledge.placeholder')} />
        <button type="submit">{loading ? t(language, 'knowledge.loading') : t(language, 'knowledge.refocus')}</button>
      </form>

      {error ? <p className="panel-error">{error}</p> : null}

      <div className="knowledge-focus-toolbar">
        <div className="knowledge-focus-crumbs">
          <strong>{t(language, 'knowledge.youAreHere')}</strong>
          <span>{preferred.query}</span>
        </div>
        <button className="knowledge-focus-back" disabled={!focusHistory.length} onClick={goBack} type="button">
          {t(language, 'knowledge.backToPreviousFocus')}
        </button>
      </div>

      <div className="knowledge-focus-grid">
        <div className="knowledge-focus-canvas">
          {positioned.length ? (
            <svg viewBox="0 0 520 300" role="img" aria-label={t(language, 'knowledge.graphContext')}>
              <defs>
                <linearGradient id="knowledge-focus-bg" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#f8fffd" />
                  <stop offset="100%" stopColor="#edf7ff" />
                </linearGradient>
              </defs>
              <rect x="0" y="0" width="520" height="300" rx="18" fill="url(#knowledge-focus-bg)" />
              {visibleEdges.map((edge, index) => {
                const source = findPosition(positioned, text(edge.source, ''));
                const target = findPosition(positioned, text(edge.target, ''));
                if (!source || !target) return null;
                const midX = (source.cx + target.cx) / 2;
                const midY = (source.cy + target.cy) / 2;
                const type = text(edge.type ?? edge.label, 'edge');
                return (
                  <g key={edge.id ?? index}>
                    <line x1={source.cx} y1={source.cy} x2={target.cx} y2={target.cy} stroke="#8aa2b3" strokeWidth="2" opacity="0.9" />
                    <line x1={source.cx} y1={source.cy} x2={target.cx} y2={target.cy} stroke="transparent" strokeWidth="16" onClick={() => edge.id ? onSelectEdge?.({ id: edge.id, type: text(edge.type ?? edge.label, undefined), source: text(edge.source, undefined), target: text(edge.target, undefined) }) : undefined} />
                    <text x={midX} y={midY - 6} textAnchor="middle" className="knowledge-edge-label">{compactText(type, 18, type)}</text>
                  </g>
                );
              })}
              {positioned.map((node) => {
                const label = compactText(node.label ?? node.name ?? node.id, node.radius > 30 ? 24 : 18, text(node.id));
                const fill = typeColor(node.type);
                const boxWidth = labelBoxWidth(label);
                const labelAbove = node.cy > 180;
                const boxY = labelAbove ? node.cy - node.radius - 30 : node.cy + node.radius + 8;
                const textY = boxY + 14;
                return (
                  <g key={node.id}>
                    <circle
                      cx={node.cx}
                      cy={node.cy}
                      r={node.radius}
                      fill={fill}
                      opacity={node.radius > 30 ? 0.96 : 0.9}
                      stroke="#ffffff"
                      strokeWidth="3"
                      onClick={() => {
                        const nextFocus = text(node.label ?? node.name ?? node.id, '');
                        if (nextFocus) navigateToFocus(nextFocus);
                        if (node.id) onSelectNode?.({ id: node.id, label: text(node.label ?? node.name, undefined) });
                      }}
                    />
                    <rect x={node.cx - boxWidth / 2} y={boxY} rx="10" ry="10" width={boxWidth} height="22" fill="rgba(255,255,255,0.92)" stroke="rgba(15,76,102,0.18)" />
                    <text x={node.cx} y={textY} textAnchor="middle" className="knowledge-node-label">{label}</text>
                  </g>
                );
              })}
            </svg>
          ) : (
            <p className="empty-copy">{t(language, 'knowledge.noGraphContext')}</p>
          )}
        </div>

        <div className="knowledge-focus-sidebar">
          <div className="knowledge-focus-summary">
            <strong>{t(language, 'knowledge.currentFocus')}</strong>
            <span>{text(preferred.query, 'sessions')}</span>
          </div>
          <div className="knowledge-focus-summary">
            <strong>{t(language, 'knowledge.source')}</strong>
            <span>{preferred.eyebrow}</span>
          </div>
          <div className="knowledge-focus-summary">
            <strong>{t(language, 'knowledge.history')}</strong>
            <span>{focusHistory.length ? focusHistory.slice(-3).join(' -> ') : t(language, 'knowledge.noFocusHistory')}</span>
          </div>
          <div className="knowledge-focus-summary">
            <strong>{t(language, 'knowledge.visibleNodes')}</strong>
            <span>{positioned.length}</span>
          </div>
          <div className="knowledge-focus-list">
            {positioned.map((node) => (
              <button
                key={node.id}
                className="knowledge-focus-item"
                type="button"
                onClick={() => {
                  const nextFocus = text(node.label ?? node.name ?? node.id, '');
                  if (nextFocus) navigateToFocus(nextFocus);
                  if (node.id) onSelectNode?.({ id: node.id, label: text(node.label ?? node.name, undefined) });
                }}
              >
                <strong>{text(node.label ?? node.name ?? node.id, 'node')}</strong>
                <span>{text(node.type)}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
