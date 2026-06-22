import { useEffect, useMemo, useRef, useState } from 'react';
import { t } from '../../app/i18n';
import type { MemoryView, MonitorLanguage } from '../../app/monitorUi';
import { getGraphEntityDetail, getGraphRelationDetail, getSessions } from '../../shared/api/monitor';
import type { GraphRelationListItem, SessionListItem } from '../../shared/api/types';
import { LoadingBlock, LoadingLine } from '../../shared/components/PanelLoading';
import './graph-inspect-panel.css';

type RecordLike = Record<string, unknown>;

export type GraphInspectTarget = {
  kind: 'entity' | 'relation';
  id: string;
  label?: string;
};

export type GraphInspectPanelProps = {
  target?: GraphInspectTarget;
  onOpenSession?: (sessionId: string) => void;
  onSelectGraphTarget?: (target: GraphInspectTarget) => void;
  language?: MonitorLanguage;
  memoryView?: MemoryView;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function toRecord(value: unknown): RecordLike {
  return value && typeof value === 'object' ? (value as RecordLike) : {};
}

function asSessionRows(response: unknown): SessionListItem[] {
  const payload = toRecord(response);
  return Array.isArray(payload.sessions) ? (payload.sessions as SessionListItem[]) : [];
}

function uniqueSessions(rows: SessionListItem[]) {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const id = text(row.session_id);
    if (id === '-' || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function asRecordArray(value: unknown): RecordLike[] {
  return Array.isArray(value) ? value.filter((item): item is RecordLike => item && typeof item === 'object') : [];
}

function collectSessionIds(payload: RecordLike): string[] {
  const ids = new Set<string>();
  const entity = toRecord(payload.entity);
  const relation = toRecord(payload.relation);
  const directSession = text(entity.session_id, text(relation.session_id, ''));
  if (directSession !== '') ids.add(directSession);
  for (const list of [asRecordArray(payload.relations), asRecordArray(payload.endpoint_relations), asRecordArray(payload.evidence)]) {
    for (const item of list) {
      const candidate = text(item.session_id, '');
      if (candidate) ids.add(candidate);
    }
  }
  const fromEntity = text(entity.from_session_id, '');
  const toEntity = text(entity.to_session_id, '');
  if (fromEntity) ids.add(fromEntity);
  if (toEntity) ids.add(toEntity);
  return [...ids];
}

export function GraphInspectPanel({ target, onOpenSession, onSelectGraphTarget, language = 'en', memoryView = 'both' }: GraphInspectPanelProps) {
  const [detail, setDetail] = useState<RecordLike | undefined>();
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const hasDetailRef = useRef(false);
  const lastLoadedKeyRef = useRef('');

  useEffect(() => {
    if (!target?.id) {
      setDetail(undefined);
      setSessions([]);
      setLoading(false);
      setRefreshing(false);
      hasDetailRef.current = false;
      return;
    }
    let cancelled = false;
    const targetKey = `${target.kind}:${target.id}:${memoryView}`;
    const load = async () => {
      const backgroundRefresh = hasDetailRef.current && lastLoadedKeyRef.current === targetKey;
      if (backgroundRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
        setRefreshing(false);
        setDetail(undefined);
        setSessions([]);
      }
      setError('');
      const payload = target.kind === 'entity' ? await getGraphEntityDetail(target.id, memoryView) : await getGraphRelationDetail(target.id, memoryView);
      if (cancelled) return;
      const normalized = toRecord(payload);
      setDetail(normalized);
      const sessionIds = collectSessionIds(normalized);
      const sessionPayloads = await Promise.all(sessionIds.slice(0, 10).map((sessionId) => getSessions(10, { q: sessionId })));
      if (cancelled) return;
      setSessions(uniqueSessions(sessionPayloads.flatMap(asSessionRows)));
      hasDetailRef.current = true;
      lastLoadedKeyRef.current = targetKey;
    };

    load()
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      });

    const timer = window.setInterval(() => {
      load()
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
            setRefreshing(false);
          }
        });
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [target, memoryView]);

  const payload = useMemo(() => {
    if (!detail || !target) return undefined;
    return target.kind === 'entity' ? toRecord(detail.entity) : toRecord(detail.relation);
  }, [detail, target]);
  const relations = useMemo<GraphRelationListItem[]>(() => (detail ? asRecordArray(detail.relations) as GraphRelationListItem[] : []), [detail]);
  const endpointRelations = useMemo<GraphRelationListItem[]>(() => (detail ? asRecordArray(detail.endpoint_relations) as GraphRelationListItem[] : []), [detail]);
  const evidenceRows = useMemo<RecordLike[]>(() => asRecordArray(detail?.evidence), [detail]);
  const targetLabel = target ? text(payload?.name, text(payload?.label, text(payload?.relation_type, text(payload?.type, target.label || target.id)))) : '-';

  if (!target?.id) {
    return (
      <section className="graph-inspect-panel">
        <div className="panel-heading">
          <p className="eyebrow">{t(language, 'graph.inspect')}</p>
          <h2>{t(language, 'graph.inspectTitle')}</h2>
          <span>{t(language, 'graph.pickItem')}</span>
        </div>
        <p className="empty-copy">{t(language, 'graph.selectItem')}</p>
      </section>
    );
  }

  if (loading && !detail && !error) {
    return (
      <section className="graph-inspect-panel" aria-busy="true">
        <div className="panel-heading">
          <p className="eyebrow">{t(language, 'graph.inspect')}</p>
          <h2>{t(language, 'common.loading')}...</h2>
          <span>{target.kind}</span>
        </div>

        <div className="inspect-block">
          <LoadingBlock lines={['title', 'long', 'default', 'default']} />
        </div>
        <div className="inspect-block">
          <LoadingBlock lines={['title', 'long', 'default']} />
          <div className="graph-inspect-list graph-inspect-list-loading">
            {Array.from({ length: 3 }).map((_, index) => (
              <article className="inspect-row" key={index}>
                <LoadingBlock lines={['long', 'short']} />
              </article>
            ))}
          </div>
        </div>
        <div className="inspect-block">
          <LoadingBlock lines={['title', 'long', 'default']} />
        </div>
      </section>
    );
  }

  return (
    <section className="graph-inspect-panel panel-loading-shell" aria-busy={loading || refreshing}>
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'graph.inspect')}</p>
        <h2>{target.kind} · {targetLabel}</h2>
        <span>{text(target.id)}{refreshing ? ` · ${t(language, 'common.loading')}...` : ''}</span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}

      <div className={refreshing ? 'panel-loading-dim' : ''} data-loading={refreshing ? 'true' : 'false'}>
      <details className="inspect-block" open>
        <summary>{target.kind === 'entity' ? t(language, 'graph.entityDetail') : t(language, 'graph.relationDetail')}</summary>
        <dl className="inspect-kv">
          <dt>{t(language, 'common.id')}</dt><dd>{text(target.id)}</dd>
          <dt>{t(language, 'common.label')}</dt><dd>{targetLabel}</dd>
          <dt>{t(language, 'common.type')}</dt><dd>{text(payload?.type ?? payload?.relation_type)}</dd>
          <dt>{t(language, 'common.origin')}</dt><dd>{text(payload?.origin_kind)}</dd>
          <dt>{t(language, 'common.memoryKind')}</dt><dd>{text(payload?.memory_kind)}</dd>
          <dt>{t(language, 'common.session')}</dt><dd>{text(payload?.session_id)}</dd>
          <dt>{t(language, 'common.dreamRun')}</dt><dd>{text(payload?.dream_run_id)}</dd>
          <dt>{t(language, 'common.artifact')}</dt><dd>{text(payload?.artifact_id)}</dd>
          <dt>{t(language, 'common.firstSeen')}</dt><dd>{text(payload?.first_seen_at)}</dd>
          <dt>{t(language, 'common.lastSeen')}</dt><dd>{text(payload?.last_seen_at)}</dd>
          <dt>{t(language, 'common.confidence')}</dt><dd>{text(payload?.confidence)}</dd>
        </dl>
      </details>

      {target.kind === 'entity' ? (
        <details className="inspect-block">
          <summary>{t(language, 'graph.relations')}</summary>
          <div className="graph-inspect-list">
            {relations.length ? relations.slice(0, 12).map((relation) => {
              const row = toRecord(relation);
              const relationId = text(row.relation_id ?? row.id);
              const relationType = text(row.relation_type ?? row.type, t(language, 'graph.relationFallback'));
              const fromLabel = text(row.from_name ?? row.from_entity_id);
              const toLabel = text(row.to_name ?? row.to_entity_id);
              return (
                <article className="inspect-row" key={relationId}>
                  <span><strong>{relationType}</strong> · {fromLabel} → {toLabel}</span>
                  <button type="button" onClick={() => onSelectGraphTarget?.({ kind: 'relation', id: relationId, label: relationType })} disabled={relationId === '-'}>
                    {t(language, 'graph.inspectRelation')}
                  </button>
                </article>
              );
            }) : <p className="empty-copy">{t(language, 'graph.noLinkedRelations')}</p>}
          </div>
        </details>
      ) : (
        <details className="inspect-block">
          <summary>{t(language, 'graph.endpointRelations')}</summary>
          <div className="graph-inspect-list">
            {endpointRelations.length ? endpointRelations.slice(0, 12).map((relation) => {
              const row = toRecord(relation);
              const relationId = text(row.relation_id ?? row.id);
              const relationType = text(row.relation_type ?? row.type, t(language, 'graph.relationFallback'));
              const fromLabel = text(row.from_name ?? row.from_entity_id);
              const toLabel = text(row.to_name ?? row.to_entity_id);
              return (
                <article className="inspect-row" key={relationId}>
                  <span><strong>{relationType}</strong> · {fromLabel} → {toLabel}</span>
                  <button type="button" onClick={() => onSelectGraphTarget?.({ kind: 'relation', id: relationId, label: relationType })} disabled={relationId === '-'}>
                    {t(language, 'graph.inspectRelation')}
                  </button>
                </article>
              );
            }) : <p className="empty-copy">{t(language, 'graph.noEndpointRelations')}</p>}
          </div>
        </details>
      )}

      <details className="inspect-block" open>
        <summary>{t(language, 'graph.connectedSessions')}</summary>
        <div className="graph-inspect-list">
          {sessions.length ? sessions.map((sessionItem) => {
            const sessionId = text(sessionItem.session_id);
            return (
              <article className="inspect-row" key={sessionId}>
                <span><strong>{text(sessionItem.thread_name, sessionId)}</strong></span>
                <span>{sessionId} · {text(sessionItem.client_type)} · {text(sessionItem.project_id)}</span>
                <button type="button" onClick={() => onOpenSession?.(sessionId)} disabled={sessionId === '-'}>
                  {t(language, 'graph.openSession')}
                </button>
              </article>
            );
          }) : <p className="empty-copy">{t(language, 'graph.noLinkedSessions')}</p>}
        </div>
      </details>

      <details className="inspect-block">
        <summary>{t(language, 'graph.evidence')}</summary>
        <div className="graph-inspect-list">
          {evidenceRows.length ? evidenceRows.slice(0, 15).map((item, index) => {
            const row = toRecord(item);
            const evidenceId = text(row.evidence_id ?? `${index}`);
            const pathLabel = text(row.path ?? row.quote, 'evidence');
            return (
              <article className="inspect-row" key={evidenceId}>
                <span><strong>{pathLabel}</strong></span>
                <small>{text(row.session_id)} · {text(row.owner_type)} · {text(row.owner_id)}</small>
                <pre className="evidence-json">{JSON.stringify(row, null, 2)}</pre>
              </article>
            );
          }) : <p className="empty-copy">{t(language, 'graph.noEvidence')}</p>}
        </div>
      </details>
      </div>
      {refreshing ? (
        <div className="panel-loading-overlay graph-inspect-overlay" aria-hidden="true">
          <LoadingLine variant="title" />
          <LoadingLine variant="long" />
          <LoadingLine variant="default" />
        </div>
      ) : null}
    </section>
  );
}
