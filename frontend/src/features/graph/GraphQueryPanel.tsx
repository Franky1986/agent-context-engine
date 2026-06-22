import { FormEvent, useState } from 'react';
import { t } from '../../app/i18n';
import type { MemoryView, MonitorLanguage } from '../../app/monitorUi';
import { queryGraph } from '../../shared/api/monitor';
import type { GraphQueryEdge, GraphQueryNode, GraphQueryResponse } from '../../shared/api/types';
import { LoadingBlock } from '../../shared/components/PanelLoading';
import './graph-query-panel.css';

export type GraphQueryPanelProps = {
  initialData?: GraphQueryResponse;
  initialQuery?: string;
  onSelectNode?: (node: { id: string; label?: string | null }) => void;
  onSelectEdge?: (edge: { id: string; type?: string | null; source?: string | null; target?: string | null }) => void;
  language?: MonitorLanguage;
  memoryView?: MemoryView;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

export function GraphQueryPanel({
  initialData,
  initialQuery = 'sessions',
  onSelectNode,
  onSelectEdge,
  language = 'en',
  memoryView = 'both',
}: GraphQueryPanelProps) {
  const [query, setQuery] = useState(initialQuery);
  const [data, setData] = useState<GraphQueryResponse | undefined>(initialData);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    setLoading(true);
    try {
      setData(await queryGraph(query, 'search', 'sqlite', 40, memoryView));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const nodes: GraphQueryNode[] = data?.nodes ?? [];
  const edges: GraphQueryEdge[] = data?.edges ?? data?.links ?? [];

  if (loading && !data && !error) {
    return (
      <section className="graph-query-panel" aria-busy="true">
        <div className="panel-heading">
          <p className="eyebrow">{t(language, 'graph.query')}</p>
          <h2>{t(language, 'graph.queryTitle')}</h2>
          <small>{t(language, 'graph.queryHint')}</small>
          <span>{t(language, 'common.loading')}...</span>
        </div>
        <div className="graph-query-results">
          <div>
            <h3>{t(language, 'graph.nodes')}</h3>
            {Array.from({ length: 4 }).map((_, index) => <LoadingBlock key={index} lines={['title', 'long', 'default']} />)}
          </div>
          <div>
            <h3>{t(language, 'graph.edges')}</h3>
            {Array.from({ length: 4 }).map((_, index) => <LoadingBlock key={index} lines={['title', 'long', 'default']} />)}
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="graph-query-panel" aria-busy={loading}>
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'graph.query')}</p>
        <h2>{t(language, 'graph.queryTitle')}</h2>
        <small>{t(language, 'graph.queryHint')}</small>
        <span>{nodes.length} nodes · {edges.length} edges</span>
      </div>
      <form className="graph-query-form" onSubmit={submit}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t(language, 'graph.queryPlaceholder')} />
        <button type="submit">{loading ? t(language, 'graph.queryLoading') : t(language, 'graph.queryRun')}</button>
      </form>
      {error ? <p className="panel-error">{error}</p> : null}
      <div className="graph-query-results">
        <div>
          <h3>{t(language, 'graph.nodes')}</h3>
          {nodes.length ? nodes.slice(0, 6).map((node, index) => (
            <article className="graph-query-row graph-row-button" key={node.id ?? index}>
              <button
                className="graph-row-button-inner"
                type="button"
                onClick={() => node.id ? onSelectNode?.({ id: node.id, label: text(node.label ?? node.name, undefined) }) : undefined}
              >
                <strong>{text(node.label ?? node.name ?? node.id, t(language, 'graph.nodeFallback'))}</strong>
                <span>{text(node.type)} · {text((node as Record<string, unknown>).origin_kind, t(language, 'graph.origin.graphFact'))}</span>
              </button>
            </article>
          )) : <p className="empty-copy">{t(language, 'graph.noQueryResult')}</p>}
        </div>
        <div>
          <h3>{t(language, 'graph.edges')}</h3>
          {edges.length ? edges.slice(0, 6).map((edge, index) => (
            <article className="graph-query-row graph-row-button" key={edge.id ?? index}>
              <button
                className="graph-row-button-inner"
                type="button"
                onClick={() => edge.id ? onSelectEdge?.({ id: edge.id, type: text(edge.type ?? edge.label, undefined), source: text(edge.source, undefined), target: text(edge.target, undefined) }) : undefined}
              >
                <strong>{text(edge.type ?? edge.label, t(language, 'graph.edgeFallback'))}</strong>
                <span>{text(edge.source)} -&gt; {text(edge.target)} · {text((edge as Record<string, unknown>).origin_kind, t(language, 'graph.origin.graphFact'))}</span>
              </button>
            </article>
          )) : <p className="empty-copy">{t(language, 'graph.noEdges')}</p>}
        </div>
      </div>
    </section>
  );
}
