import { useEffect, useRef, useState } from 'react';
import { t } from '../../app/i18n';
import type { MemoryView, MonitorLanguage } from '../../app/monitorUi';
import { getGraphEntities, getGraphRelations, getGraphTableOptions } from '../../shared/api/monitor';
import type { GraphEntityListItem, GraphEntityListResponse, GraphRelationListItem, GraphRelationListResponse, GraphTableOptions } from '../../shared/api/types';
import { LoadingBlock, LoadingLine } from '../../shared/components/PanelLoading';
import './graph-panel.css';

export type GraphPanelProps = {
  initialEntities?: GraphEntityListResponse;
  initialRelations?: GraphRelationListResponse;
  initialOptions?: GraphTableOptions;
  onSelectEntity?: (entity: { id: string; name?: string | null; type?: string | null }) => void;
  onSelectRelation?: (relation: { id: string; type?: string | null }) => void;
  language?: MonitorLanguage;
  memoryView?: MemoryView;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

export function GraphPanel({
  initialEntities,
  initialRelations,
  initialOptions,
  onSelectEntity,
  onSelectRelation,
  language = 'en',
  memoryView = 'both',
}: GraphPanelProps) {
  const [entities, setEntities] = useState<GraphEntityListResponse | undefined>(initialEntities);
  const [relations, setRelations] = useState<GraphRelationListResponse | undefined>(initialRelations);
  const [options, setOptions] = useState<GraphTableOptions | undefined>(initialOptions);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState<Date | undefined>(initialEntities ? new Date() : undefined);
  const [loading, setLoading] = useState(!(initialEntities && initialRelations && initialOptions));
  const [refreshing, setRefreshing] = useState(false);
  const hasDataRef = useRef(Boolean(initialEntities && initialRelations && initialOptions));
  const lastLoadedKeyRef = useRef(initialEntities && initialRelations && initialOptions ? memoryView : '');

  useEffect(() => {
    if (initialEntities && initialRelations && initialOptions) return;
    let cancelled = false;
    const requestKey = memoryView;
    const load = () => {
      const backgroundRefresh = hasDataRef.current && lastLoadedKeyRef.current === requestKey;
      if (backgroundRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
        setRefreshing(false);
        setEntities(undefined);
        setRelations(undefined);
        setOptions(undefined);
      }
      Promise.all([getGraphEntities(5, memoryView), getGraphRelations(5, memoryView), getGraphTableOptions()])
        .then(([entityPayload, relationPayload, optionsPayload]) => {
          if (cancelled) return;
          setEntities(entityPayload);
          setRelations(relationPayload);
          setOptions(optionsPayload);
          hasDataRef.current = true;
          lastLoadedKeyRef.current = requestKey;
          setUpdatedAt(new Date());
          setError('');
          setLoading(false);
          setRefreshing(false);
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : String(err));
            setLoading(false);
            setRefreshing(false);
          }
        });
    };
    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [initialEntities, initialOptions, initialRelations, memoryView]);

  const entityRows: GraphEntityListItem[] = entities?.entities ?? entities?.rows ?? [];
  const relationRows: GraphRelationListItem[] = relations?.relations ?? relations?.rows ?? [];
  const entityTypeCount = options?.entity_types?.length ?? 0;
  const relationTypeCount = options?.relation_types?.length ?? 0;

  const openEntity = (entity: GraphEntityListItem) => {
    const id = text(entity.entity_id ?? entity.id);
    if (!id || id === '-') return;
    onSelectEntity?.({ id, name: entity.name, type: entity.type });
  };

  const openRelation = (relation: GraphRelationListItem) => {
    const id = text(relation.relation_id ?? relation.id);
    if (!id || id === '-') return;
    const type = text(relation.type ?? relation.relation_type, undefined);
    onSelectRelation?.({ id, type: type === '-' ? undefined : type });
  };

  return (
    <section aria-busy={loading || refreshing} className="graph-panel">
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'graph.heading.eyebrow')}</p>
        <h2>{t(language, 'graph.title')}</h2>
        <span>
          {loading
            ? `${t(language, 'common.loading')}...`
            : `${entityTypeCount} ${t(language, 'graph.entityTypes')} · ${relationTypeCount} ${t(language, 'graph.relationTypes')} · ${t(language, 'sessions.updated')} ${updatedAt ? updatedAt.toLocaleTimeString() : '-'}${refreshing ? ` · ${t(language, 'common.loading')}...` : ''}`}
        </span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}
      {loading ? (
        <div className="graph-columns graph-columns-loading">
          <div>
            <h3>{t(language, 'graph.heading.entities')}</h3>
            {Array.from({ length: 4 }).map((_, index) => (
              <article className="graph-row" key={index}>
                <LoadingBlock lines={['title', 'long', 'default']} />
              </article>
            ))}
          </div>
          <div>
            <h3>{t(language, 'graph.heading.relations')}</h3>
            {Array.from({ length: 4 }).map((_, index) => (
              <article className="graph-row" key={index}>
                <LoadingBlock lines={['title', 'long', 'default']} />
              </article>
            ))}
          </div>
        </div>
      ) : (
        <div className="graph-columns panel-loading-shell">
          <div className={refreshing ? 'panel-loading-dim' : ''} data-loading={refreshing ? 'true' : 'false'}>
            <h3>{t(language, 'graph.heading.entities')}</h3>
            {entityRows.length ? entityRows.map((entity, index) => (
              <article className="graph-row graph-row-button" key={entity.entity_id ?? entity.id ?? index}>
                <button type="button" className="graph-row-button-inner" onClick={() => openEntity(entity)}>
                  <strong>{text(entity.name ?? entity.entity_id ?? entity.id, t(language, 'graph.unnamed'))}</strong>
                  <span>{text(entity.type ?? entity.entity_type)} · {text((entity as Record<string, unknown>).origin_kind, t(language, 'graph.origin.graphFact'))} · {text(entity.last_seen_at)}</span>
                </button>
              </article>
            )) : <p className="empty-copy">{t(language, 'graph.noEntities')}</p>}
          </div>
          <div className={refreshing ? 'panel-loading-dim' : ''} data-loading={refreshing ? 'true' : 'false'}>
            <h3>{t(language, 'graph.heading.relations')}</h3>
            {relationRows.length ? relationRows.map((relation, index) => (
              <article className="graph-row graph-row-button" key={relation.relation_id ?? relation.id ?? index}>
                <button className="graph-row-button-inner" type="button" onClick={() => openRelation(relation)}>
                  <strong>{text(relation.type ?? relation.relation_type, t(language, 'graph.relationFallback'))}</strong>
                  <span>{text(relation.source_name ?? relation.source)} -&gt; {text(relation.target_name ?? relation.target)} · {text((relation as Record<string, unknown>).origin_kind, t(language, 'graph.origin.graphFact'))}</span>
                </button>
              </article>
            )) : <p className="empty-copy">{t(language, 'graph.noRelations')}</p>}
          </div>
          {refreshing ? (
            <div className="panel-loading-overlay graph-columns-overlay" aria-hidden="true">
              <LoadingLine variant="title" />
              <LoadingLine variant="long" />
              <LoadingLine variant="default" />
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
