import { useEffect, useRef, useState } from 'react';
import { t } from '../../app/i18n';
import type { MemoryView, MonitorLanguage } from '../../app/monitorUi';
import { getSessionDetail, type SessionDetailSection } from '../../shared/api/monitor';
import type { DreamRun, SessionDetail } from '../../shared/api/types';
import { LoadingBlock, LoadingCard, LoadingLine } from '../../shared/components/PanelLoading';
import { dreamNarrativeSections } from '../dreams/dreamNarrative';
import './session-detail-panel.css';

export type SessionDetailPanelProps = {
  sessionId?: string;
  initialData?: SessionDetail;
  onOpenDream?: (dream: DreamRun) => void;
  onOpenDreamFocus?: (
    dream: DreamRun,
    focus: 'deterministic_entities' | 'deterministic_relations' | 'semantic_entities' | 'semantic_relations',
  ) => void;
  onOpenDreamList?: () => void;
  onOpenSessionKnowledge?: () => void;
  onOpenControl?: () => void;
  language?: MonitorLanguage;
  memoryView?: MemoryView;
};

type SectionState = Partial<Record<'summary' | 'dreams' | 'messages' | 'events', boolean>>;
type ConversationMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  mergedCount: number;
};

type QuickPeekEntry = {
  label: string;
  meta?: string;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function hasText(value: unknown) {
  return value !== null && value !== undefined && String(value).trim() !== '';
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function pretty(value: unknown) {
  return JSON.stringify(value ?? null, null, 2);
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    : [];
}

function compactText(value: unknown, limit: number, fallback: string) {
  const normalized = text(value, fallback);
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
}

function entityDisplayName(item: Record<string, unknown>): QuickPeekEntry {
  const label = text(item.name ?? item.proposed_name ?? item.entity_key ?? item.key ?? item.proposal_id, 'unknown');
  const type = text(item.entity_type ?? item.type, '');
  const key = text(item.entity_key ?? item.key, '');
  const metaParts = [type, key && key !== label ? key : ''].filter(Boolean);
  return {
    label,
    meta: metaParts.join(' · '),
  };
}

function relationDisplayName(item: Record<string, unknown>, language: MonitorLanguage): QuickPeekEntry {
  const type = text(item.relation_type ?? item.type ?? item.proposed_type, t(language, 'graph.relationFallback'));
  const source = text(item.source_entity_key ?? record(item.from).key ?? item.source_ref, '');
  const target = text(item.target_entity_key ?? record(item.to).key ?? item.target_ref, '');
  if (source || target) {
    return {
      label: `${type}: ${source || '?'} -> ${target || '?'}`,
    };
  }
  return { label: type };
}

function latestDreamSummary(item: Record<string, unknown>, language: MonitorLanguage) {
  return compactText(
    item.episode_short
      ?? item.episode_title
      ?? item.error_message
      ?? item.error
      ?? item.intent
      ?? item.pipeline_status,
    220,
    t(language, 'sessionDetail.compact.noDreamSummary'),
  );
}

function dreamPending(item: Record<string, unknown>) {
  const status = text(item.status, '').toLowerCase();
  const pipelineStatus = text(item.pipeline_status, '').toLowerCase();
  if (['succeeded', 'failed', 'completed', 'persisted', 'dry_run'].includes(status)) return false;
  if (['succeeded', 'failed', 'completed', 'persisted', 'dry_run'].includes(pipelineStatus)) return false;
  return ['queued', 'running', 'dreaming', 'pending'].includes(status)
    || ['queued', 'running', 'dreaming', 'pending'].includes(pipelineStatus);
}

function metricLabel(count: number, pending: boolean, language: MonitorLanguage) {
  if (pending && count === 0) return t(language, 'sessionDetail.pending');
  return String(count);
}

function numeric(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) return Number(value);
  return 0;
}

function formatMetric(value: unknown) {
  return new Intl.NumberFormat().format(numeric(value));
}

function countWithFallback(items: Record<string, unknown>[], fallbackValue: unknown) {
  return items.length || numeric(fallbackValue);
}

function uniqueRecordsBy(items: Record<string, unknown>[], keyFor: (item: Record<string, unknown>) => string) {
  const seen = new Set<string>();
  const result: Record<string, unknown>[] = [];
  for (const item of items) {
    const key = keyFor(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }
  return result;
}

function aggregateDreamEntities(dreams: DreamRun[], pick: (item: Record<string, unknown>) => unknown, keyFor: (item: Record<string, unknown>) => string) {
  const merged: Record<string, unknown>[] = [];
  for (const dream of dreams) {
    merged.push(...records(pick(record(dream))));
  }
  return uniqueRecordsBy(merged, keyFor);
}

function QuickPeekList({
  title,
  items,
  formatter,
  language,
}: {
  title: string;
  items: Record<string, unknown>[];
  formatter: (item: Record<string, unknown>) => QuickPeekEntry;
  language: MonitorLanguage;
}) {
  const entries = items
    .map(formatter)
    .filter((item) => item && item.label && item.label !== '-');
  return (
    <details className="session-quickpeek">
      <summary>{title} ({entries.length})</summary>
      {entries.length ? (
        <ul className="session-quickpeek-list">
          {entries.slice(0, 10).map((entry, index) => (
            <li key={`${entry.label}-${entry.meta ?? ''}-${index}`}>
              <span className="session-quickpeek-label">{entry.label}</span>
              {entry.meta ? <small className="session-quickpeek-meta">{entry.meta}</small> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="session-quickpeek-empty">{t(language, 'dreamArtifacts.quickPeek.empty')}</p>
      )}
      {entries.length > 10 ? (
        <small className="session-quickpeek-more">
          {t(language, 'dreamArtifacts.quickPeek.more', { count: entries.length - 10 })}
        </small>
      ) : null}
    </details>
  );
}

function mergeSessionDetail(previous: SessionDetail | undefined, payload: SessionDetail): SessionDetail {
  const previousAny = record(previous);
  const payloadAny = record(payload);
  const mergedMessages = Array.isArray(payloadAny.messages)
    ? payloadAny.messages
    : Array.isArray(previousAny.messages)
      ? previousAny.messages
      : previous?.messages;
  return {
    ...(previous ?? {}),
    ...payload,
    session: payload.session ?? previous?.session,
    summary: payload.summary ? { ...record(previousAny.summary), ...record(payload.summary) } : previous?.summary,
    token_totals: payload.token_totals ?? previous?.token_totals,
    dream_token_totals: payload.dream_token_totals ?? previous?.dream_token_totals,
    dreams: payload.dreams ?? previous?.dreams,
    messages: mergedMessages,
    events: payload.events ?? previous?.events,
    graph_artifacts: payload.graph_artifacts ?? previous?.graph_artifacts,
    analysis_reports: payload.analysis_reports ?? previous?.analysis_reports,
    latest_dream: payloadAny.latest_dream ?? previousAny.latest_dream,
    events_total: payload.events_total ?? previous?.events_total,
    events_limit: payload.events_limit ?? previous?.events_limit,
    events_offset: payload.events_offset ?? previous?.events_offset,
  };
}

function loadedSectionsFromDetail(detail: SessionDetail | undefined): SectionState {
  const item = record(detail);
  return {
    summary: hasText(record(item.summary).content),
    dreams: Array.isArray(item.dreams),
    messages: Array.isArray(item.messages),
    events: Array.isArray(item.events),
  };
}

function buildConversation(events: Record<string, unknown>[]) {
  const messages: ConversationMessage[] = [];
  let sawUserPrompt = false;
  let sawAssistantStop = false;

  const pushMessage = (
    role: ConversationMessage['role'],
    content: string,
    timestamp: string,
    id: string,
  ) => {
    const normalized = content.trim();
    if (!normalized) return;
    const last = messages[messages.length - 1];
    if (last && last.role === role) {
      if (!last.content.includes(normalized)) {
        last.content = `${last.content}\n\n${normalized}`;
        last.mergedCount += 1;
      }
      last.timestamp = timestamp || last.timestamp;
      return;
    }
    messages.push({ id, role, content: normalized, timestamp, mergedCount: 1 });
  };

  for (const event of events) {
    const seq = text(event.seq, '0');
    const eventName = text(event.event_name, '');
    const timestamp = text(event.recorded_at_local ?? event.recorded_at ?? event.created_at ?? event.timestamp, '');
    if (eventName === 'UserPromptSubmit') {
      const prompt = text(event.prompt, '');
      if (prompt.trim()) {
        sawUserPrompt = true;
        pushMessage('user', prompt, timestamp, `${seq}-user`);
      }
    }
    if (eventName === 'Stop') {
      const assistant = text(event.last_assistant_message, '');
      if (assistant.trim()) {
        sawAssistantStop = true;
        pushMessage('assistant', assistant, timestamp, `${seq}-assistant`);
      }
    }
  }
  return {
    messages,
    partial: Boolean(messages.length) && (!sawUserPrompt || !sawAssistantStop || messages[0]?.role === 'assistant'),
  };
}

const SECTION_QUERY: Record<keyof SectionState, SessionDetailSection> = {
  summary: 'summary',
  dreams: 'dreams',
  messages: 'messages',
  events: 'events',
};

const SESSION_RISK_POLL_MS = 5000;

export function SessionDetailPanel({
  sessionId,
  initialData,
  onOpenDream,
  onOpenDreamFocus,
  onOpenDreamList,
  onOpenSessionKnowledge,
  onOpenControl,
  language = 'en',
  memoryView = 'both',
}: SessionDetailPanelProps) {
  const [data, setData] = useState<SessionDetail | undefined>(initialData);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(Boolean(sessionId && !initialData));
  const [loadedSections, setLoadedSections] = useState<SectionState>(() => loadedSectionsFromDetail(initialData));
  const [sectionLoading, setSectionLoading] = useState<SectionState>({});
  const [sectionErrors, setSectionErrors] = useState<Partial<Record<keyof SectionState, string>>>({});
  const activeSessionIdRef = useRef(sessionId);

  useEffect(() => {
    activeSessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    if (initialData) {
      setData(initialData);
      setLoadedSections(loadedSectionsFromDetail(initialData));
      setSectionLoading({});
      setSectionErrors({});
      setError('');
      setLoading(false);
      return;
    }
    if (!sessionId) {
      setData(undefined);
      setLoadedSections({});
      setSectionLoading({});
      setSectionErrors({});
      setError('');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setData(undefined);
    setLoadedSections({});
    setSectionLoading({});
    setSectionErrors({});
    setError('');
    setLoading(true);
    getSessionDetail(sessionId, { include: ['base'] })
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setLoadedSections(loadedSectionsFromDetail(payload));
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initialData, sessionId]);

  useEffect(() => {
    if (initialData || !sessionId) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      const targetSessionId = sessionId;
      getSessionDetail(targetSessionId, { include: ['base'] })
        .then((payload) => {
          if (cancelled || activeSessionIdRef.current !== targetSessionId) return;
          setData((previous) => mergeSessionDetail(previous, payload));
          setLoadedSections((previous) => ({ ...previous, ...loadedSectionsFromDetail(payload) }));
          setError('');
        })
        .catch((err: unknown) => {
          if (cancelled || activeSessionIdRef.current !== targetSessionId) return;
          setError(err instanceof Error ? err.message : String(err));
        });
    }, SESSION_RISK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [initialData, sessionId]);

  const loadSection = async (section: keyof SectionState) => {
    if (!sessionId || loadedSections[section] || sectionLoading[section]) return;
    const targetSessionId = sessionId;
    setSectionErrors((previous) => ({ ...previous, [section]: '' }));
    setSectionLoading((previous) => ({ ...previous, [section]: true }));
    try {
      const payload = await getSessionDetail(targetSessionId, {
        include: [SECTION_QUERY[section]],
        eventLimit: section === 'events' ? 200 : undefined,
      });
      if (activeSessionIdRef.current !== targetSessionId) return;
      setData((previous) => mergeSessionDetail(previous, payload));
      setLoadedSections((previous) => ({ ...previous, [section]: true }));
    } catch (err: unknown) {
      if (activeSessionIdRef.current !== targetSessionId) return;
      setSectionErrors((previous) => ({
        ...previous,
        [section]: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      if (activeSessionIdRef.current === targetSessionId) {
        setSectionLoading((previous) => ({ ...previous, [section]: false }));
      }
    }
  };

  if (loading && !data && !error) {
    return (
      <section className="session-detail-panel" aria-busy="true" id="session-detail">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t(language, 'sessionDetail.heading')}</p>
            <h2>{t(language, 'common.loading')}...</h2>
          </div>
          <span>{t(language, 'common.loading')}...</span>
        </div>

        <div className="session-meta-grid session-meta-grid-primary session-meta-grid-loading">
          {Array.from({ length: 8 }).map((_, index) => (
            <span key={index}>
              <LoadingLine className="session-loading-label" variant="short" />
              <LoadingLine variant="long" />
            </span>
          ))}
        </div>

        <div className="session-priority-grid">
          <LoadingCard />
          <LoadingCard />
          <LoadingCard className="session-priority-card-accent" />
        </div>

        <div className="session-cta-row">
          {Array.from({ length: 3 }).map((_, index) => (
            <div className="session-loading-cta" key={index}>
              <LoadingLine variant="long" />
            </div>
          ))}
        </div>

        <div className="session-kpi-grid">
          {Array.from({ length: 4 }).map((_, index) => (
            <article className="session-kpi-card session-kpi-card-loading" key={index}>
              <LoadingBlock lines={['short', 'metric', 'default']} />
            </article>
          ))}
        </div>
      </section>
    );
  }

  const detailData = record(data);
  const session = record(data?.session);
  const summary = record(data?.summary);
  const tokenTotals = record(data?.token_totals);
  const dreamTokenTotals = record(detailData.dream_token_totals);
  const events = Array.isArray(data?.events) ? data.events : [];
  const dreams = Array.isArray(data?.dreams) ? data.dreams : [];
  const latestDream = (dreams[0] as DreamRun | undefined) ?? (detailData.latest_dream as DreamRun | undefined);
  const latestDreamItem = record(latestDream);
  const previewEvents = events.slice(0, 30);
  const transcriptMessages = records(detailData.messages);
  const conversationData = buildConversation(records(events));
  const conversation = transcriptMessages.length
    ? transcriptMessages.map((message, index) => ({
        id: text(message.id, `message-${index}`),
        role: text(message.role, 'assistant') === 'user' ? 'user' as const : 'assistant' as const,
        content: text(message.content, ''),
        timestamp: text(message.timestamp, ''),
        mergedCount: 1,
      }))
    : conversationData.messages;

  const deterministicEntities = records(latestDreamItem.v2_deterministic_entities);
  const deterministicRelations = records(latestDreamItem.v2_deterministic_relations);
  const semanticEntities = records(latestDreamItem.v2_semantic_entities);
  const semanticRelations = records(latestDreamItem.v2_semantic_relations);
  const sessionDeterministicEntities = loadedSections.dreams
    ? aggregateDreamEntities(
        dreams,
        (item) => item.v2_deterministic_entities,
        (item) => text(item.entity_key ?? item.key ?? `${text(item.type, '')}:${text(item.name, '')}`, ''),
      )
    : deterministicEntities;
  const sessionDeterministicRelations = loadedSections.dreams
    ? aggregateDreamEntities(
        dreams,
        (item) => item.v2_deterministic_relations,
        (item) => {
          const left = text(record(item.from).key ?? item.source_entity_key ?? item.source_ref, '');
          const right = text(record(item.to).key ?? item.target_entity_key ?? item.target_ref, '');
          return text(item.relation_key ?? `${text(item.type ?? item.relation_type, '')}:${left}->${right}`, '');
        },
      )
    : deterministicRelations;
  const sessionSemanticEntities = loadedSections.dreams
    ? aggregateDreamEntities(
        dreams,
        (item) => item.v2_semantic_entities,
        (item) => text(item.entity_key ?? item.semantic_entity_id ?? item.key ?? item.name, ''),
      )
    : semanticEntities;
  const sessionSemanticRelations = loadedSections.dreams
    ? aggregateDreamEntities(
        dreams,
        (item) => item.v2_semantic_relations,
        (item) => text(item.relation_key ?? item.semantic_relation_id ?? `${text(item.relation_type ?? item.type, '')}:${text(item.source_entity_key, '')}->${text(item.target_entity_key, '')}`, ''),
      )
    : semanticRelations;
  const deterministicEntityCount = countWithFallback(sessionDeterministicEntities, session.session_deterministic_entity_count ?? latestDreamItem.v2_deterministic_entity_count);
  const deterministicRelationCount = countWithFallback(sessionDeterministicRelations, session.session_deterministic_relation_count ?? latestDreamItem.v2_deterministic_relation_count);
  const semanticEntityCount = countWithFallback(sessionSemanticEntities, session.session_semantic_entity_count ?? latestDreamItem.v2_semantic_entity_count);
  const semanticRelationCount = countWithFallback(sessionSemanticRelations, session.session_semantic_relation_count ?? latestDreamItem.v2_semantic_relation_count);
  const latestDreamPending = dreamPending(latestDreamItem);
  const handoverPreview = compactText(summary.content || session.summary_preview, 340, t(language, 'sessionDetail.compact.noSummary'));
  const lastActivityPreview = compactText(session.latest_activity_summary ?? data?.last_seen_label, 220, t(language, 'sessions.preview.latestActivityFallback'));
  const latestDreamTitle = text(
    latestDreamItem.episode_title ?? session.dream_summary_title ?? latestDreamItem.dream_run_id,
    latestDream ? t(language, 'sessions.table.dreams') : t(language, 'sessionDetail.noDreamRun'),
  );
  const latestDreamShort = latestDream
    ? latestDreamSummary(
        {
          ...latestDreamItem,
          episode_short: latestDreamItem.episode_short ?? session.dream_summary_preview,
        },
        language,
      )
    : t(language, 'sessionDetail.noDreamAvailable');
  const latestDreamMeta = text(latestDreamItem.episode_meta_short ?? session.dream_meta_preview, t(language, 'sessionDetail.noDreamMeta'));
  const latestDreamNarrative = dreamNarrativeSections(latestDreamItem);
  const showDeterministic = memoryView !== 'semantic';
  const showSemantic = memoryView !== 'deterministic';
  const visibleDreamCount = dreams.length || Number(session.dream_count ?? 0);
  const riskSummary = record(detailData.risk_summary);
  const riskEvents = records(detailData.risk_events);
  const taintSources = records(riskSummary.taint_sources);
  const riskControls = record(riskSummary.controls);
  const openRiskEvents = riskEvents.filter((item) => {
    const approvalState = text(item.approval_state, '');
    const status = text(item.status, '');
    return approvalState === 'required' || status === 'blocked' || status === 'quarantined';
  });

  return (
    <section className="session-detail-panel" id="session-detail">
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'sessionDetail.heading')}</p>
        <h2>{text(session.thread_name ?? session.session_id, t(language, 'sessionDetail.latestSession'))}</h2>
        <span>
          {text(data?.events_total ?? events.length, '0')} {t(language, 'sessionDetail.events')} · {visibleDreamCount} {t(language, 'sessions.table.dreams')}
        </span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}

      <div className="session-cta-row">
        <button className="session-cta-button" disabled={!onOpenDreamList} onClick={() => onOpenDreamList?.()} type="button">
          {t(language, 'sessionDetail.openSessionDreams')}
        </button>
        <button className="session-cta-button" disabled={!onOpenSessionKnowledge} onClick={() => onOpenSessionKnowledge?.()} type="button">
          {t(language, 'sessionDetail.openKnowledge')}
        </button>
        <button className="session-cta-button" disabled={!onOpenControl} onClick={() => onOpenControl?.()} type="button">
          {t(language, 'sessionDetail.openControl')}
        </button>
      </div>

      <div className="session-meta-grid session-meta-grid-primary">
        <span><strong>{t(language, 'sessionDetail.client')}</strong>{text(session.client_type)}</span>
        <span><strong>{t(language, 'sessionDetail.project')}</strong>{text(session.project_id)}</span>
        <span><strong>{t(language, 'common.status')}</strong>{text(session.status)}</span>
        <span><strong>{t(language, 'sessionDetail.activity')}</strong>{text(session.activity_status)}</span>
        <span><strong>{t(language, 'sessionDetail.summary')}</strong>{text(session.summary_status)}</span>
        <span><strong>{t(language, 'sessions.dream')}</strong>{text(session.dream_status)}</span>
        <span><strong>{t(language, 'sessionDetail.started')}</strong>{text(session.started_at_local ?? session.started_at)}</span>
        <span><strong>{t(language, 'sessionDetail.lastEvent')}</strong>{text(session.last_event_at_local ?? session.last_event_at)}</span>
      </div>

      <div className="session-priority-grid">
        <article className="session-priority-card">
          <p className="eyebrow">{t(language, 'sessionDetail.summary')}</p>
          <h3>{t(language, 'sessionDetail.summaryTitle')}</h3>
          <p className="session-priority-copy">{handoverPreview}</p>
          <div className="session-chip-row">
            <span>{text(summary.summary_kind, t(language, 'sessionDetail.summaryKind'))}</span>
            <span>{text(summary.created_at_local ?? summary.created_at, t(language, 'sessionDetail.unknownTime'))}</span>
            <span>{text(summary.input_event_count, '0')} {t(language, 'sessionDetail.inputEvents')}</span>
          </div>
        </article>

        <article className="session-priority-card">
          <p className="eyebrow">{t(language, 'sessionDetail.activity')}</p>
          <h3>{t(language, 'sessionDetail.activityTitle')}</h3>
          <p className="session-priority-copy">{lastActivityPreview}</p>
          <div className="session-chip-row">
            <span>{text(data?.last_seen_label, text(session.last_seen_label, t(language, 'common.unknown')))}</span>
            <span>{t(language, 'sessions.table.sessionTokens')}: {formatMetric(tokenTotals.total_tokens)}</span>
            <span>{t(language, 'sessions.table.dreamTokens')}: {formatMetric(dreamTokenTotals.total_tokens)}</span>
            <span>{text(session.cwd)}</span>
          </div>
        </article>

        <article className="session-priority-card session-priority-card-accent">
          <p className="eyebrow">{t(language, 'sessionDetail.latestDream')}</p>
          <h3>{latestDreamTitle}</h3>
          <p className="session-priority-copy session-priority-copy-strong">{latestDreamShort}</p>
          {latestDream ? (
            <p className="session-priority-copy">{latestDreamMeta}</p>
          ) : null}
          <div className="session-chip-row">
            <span>{text(latestDreamItem.status, t(language, 'sessionDetail.noDreamRun'))}</span>
            <span>{text(latestDreamItem.runner, t(language, 'sessionDetail.noRunner'))} {text(latestDreamItem.runner_model, '')}</span>
            <span>{t(language, 'sessions.table.dreamTokens')}: {formatMetric(latestDreamItem.total_tokens)}</span>
            <span>{text(latestDreamItem.started_at_local ?? latestDreamItem.started_at ?? session.last_dream_at, t(language, 'sessionDetail.notStarted'))}</span>
          </div>
        </article>
      </div>

      <div className="session-kpi-grid">
        {showDeterministic ? (
          <>
            <button
              className="session-kpi-card"
              disabled={!latestDream || !onOpenDreamFocus}
              onClick={() => latestDream && onOpenDreamFocus?.(latestDream, 'deterministic_entities')}
              type="button"
            >
              <small>{t(language, 'dreamArtifacts.deterministic')}</small>
              <strong>{metricLabel(deterministicEntityCount, latestDreamPending, language)}</strong>
              <span>{t(language, 'common.entities')}</span>
            </button>
            <button
              className="session-kpi-card"
              disabled={!latestDream || !onOpenDreamFocus}
              onClick={() => latestDream && onOpenDreamFocus?.(latestDream, 'deterministic_relations')}
              type="button"
            >
              <small>{t(language, 'dreamArtifacts.deterministic')}</small>
              <strong>{metricLabel(deterministicRelationCount, latestDreamPending, language)}</strong>
              <span>{t(language, 'common.relations')}</span>
            </button>
          </>
        ) : null}
        {showSemantic ? (
          <>
            <button
              className="session-kpi-card"
              disabled={!latestDream || !onOpenDreamFocus}
              onClick={() => latestDream && onOpenDreamFocus?.(latestDream, 'semantic_entities')}
              type="button"
            >
              <small>{t(language, 'dreamArtifacts.semantic')}</small>
              <strong>{metricLabel(semanticEntityCount, latestDreamPending, language)}</strong>
              <span>{t(language, 'common.entities')}</span>
            </button>
            <button
              className="session-kpi-card"
              disabled={!latestDream || !onOpenDreamFocus}
              onClick={() => latestDream && onOpenDreamFocus?.(latestDream, 'semantic_relations')}
              type="button"
            >
              <small>{t(language, 'dreamArtifacts.semantic')}</small>
              <strong>{metricLabel(semanticRelationCount, latestDreamPending, language)}</strong>
              <span>{t(language, 'common.relations')}</span>
            </button>
          </>
        ) : null}
      </div>

      <details className="inspect-block" open>
        <summary>{t(language, 'sessionDetail.riskBlocks')}</summary>
        <div className="session-risk-grid">
          <article className="session-risk-card">
            <small>{t(language, 'sessionDetail.riskOpen')}</small>
            <strong>{text(riskSummary.open_count, '0')}</strong>
            <span>{t(language, 'sessionDetail.riskPendingApprovals')}: {text(riskSummary.pending_approval_count, '0')}</span>
          </article>
          <article className="session-risk-card">
            <small>{t(language, 'sessionDetail.riskBlocked')}</small>
            <strong>{text(riskSummary.blocked_count, '0')}</strong>
            <span>{t(language, 'sessionDetail.riskQuarantined')}: {text(riskSummary.quarantined_count, '0')}</span>
          </article>
          <article className="session-risk-card">
            <small>{t(language, 'sessionDetail.riskTaint')}</small>
            <strong>{Boolean(riskSummary.taint_active) ? t(language, 'sessionDetail.riskTaintActive') : t(language, 'sessionDetail.riskTaintClear')}</strong>
            <span>{t(language, 'sessionDetail.riskTaintResets')}: {text(riskSummary.taint_reset_count, '0')}</span>
          </article>
        </div>

        <div className="session-risk-controls">
          <p className="session-priority-copy">
            {t(language, 'sessionDetail.riskControlCopy')}
          </p>
          <div className="session-chip-row">
            <span>{text(riskControls.reset_taint, 'reset taint')}</span>
            <span>{text(riskControls.firewall_disable_session, 'firewall disable session')}</span>
            <span>{text(riskControls.firewall_disable_session_30m, 'firewall disable session 30m')}</span>
            <span>{text(riskControls.firewall_enable_session, 'firewall enable session')}</span>
          </div>
        </div>

        <details className="nested-inspect" open={Boolean(openRiskEvents.length)}>
          <summary>{t(language, 'sessionDetail.riskOpenList')} ({openRiskEvents.length})</summary>
          {openRiskEvents.length ? (
            <div className="timeline-list">
              {openRiskEvents.map((item, index) => (
                <details className="timeline-row" key={text(item.risk_event_id, `open-risk-${index}`)}>
                  <summary>
                    <strong>{text(item.risk_event_id, 'risk')} · {text(item.status, 'unknown')} · {text(item.risk_level, 'unknown')}</strong>
                    <span>{text(item.created_at)}</span>
                  </summary>
                  <small>{text(item.reason, t(language, 'risk.reason.none'))}</small>
                  <small>{text(item.impact, t(language, 'sessionDetail.riskNoImpact'))}</small>
                  <div className="session-summary-meta">
                    <span>{t(language, 'sessionDetail.riskApproval')}: {text(item.approval_state, '-')}</span>
                    <span>{t(language, 'sessionDetail.riskSourceKind')}: {text(item.source_kind, '-')}</span>
                    <span>{t(language, 'sessionDetail.riskCommandRef')}: {text(item.command_ref, '-')}</span>
                  </div>
                  {hasText(item.approval_line) ? (
                    <pre className="inspect-pre small">{text(item.approval_line)}</pre>
                  ) : null}
                  {Array.isArray(item.taint_source_refs) && item.taint_source_refs.length ? (
                    <div className="session-summary-meta">
                      {item.taint_source_refs.map((ref, refIndex) => (
                        <span key={`${ref}-${refIndex}`}>{t(language, 'sessionDetail.riskDerivedFrom')}: {text(ref)}</span>
                      ))}
                    </div>
                  ) : null}
                  <pre className="inspect-pre small">{pretty(item)}</pre>
                </details>
              ))}
            </div>
          ) : (
            <p className="empty-copy">{t(language, 'sessionDetail.riskOpenEmpty')}</p>
          )}
        </details>

        <details className="nested-inspect" open={Boolean(taintSources.length)}>
          <summary>{t(language, 'sessionDetail.riskTaintSources')} ({taintSources.length})</summary>
          {taintSources.length ? (
            <div className="timeline-list">
              {taintSources.map((item, index) => (
                <details className="timeline-row" key={text(item.risk_event_id, `taint-source-${index}`)}>
                  <summary>
                    <strong>{text(item.risk_event_id, 'risk')} · {text(item.status, 'unknown')} · {text(item.risk_level, 'unknown')}</strong>
                    <span>{text(item.created_at)}</span>
                  </summary>
                  <small>{text(item.reason, t(language, 'risk.reason.none'))}</small>
                  <small>{text(item.preview, t(language, 'sessionDetail.noPreview'))}</small>
                  <pre className="inspect-pre small">{pretty(item)}</pre>
                </details>
              ))}
            </div>
          ) : (
            <p className="empty-copy">{t(language, 'sessionDetail.riskTaintSourcesEmpty')}</p>
          )}
        </details>

        <details className="nested-inspect">
          <summary>{t(language, 'sessionDetail.riskAllEvents')} ({riskEvents.length})</summary>
          {riskEvents.length ? (
            <div className="timeline-list">
              {riskEvents.map((item, index) => (
                <details className="timeline-row" key={text(item.risk_event_id, `risk-event-${index}`)}>
                  <summary>
                    <strong>{text(item.risk_event_id, 'risk')} · {text(item.status, 'unknown')} · {text(item.risk_level, 'unknown')}</strong>
                    <span>{text(item.created_at)}</span>
                  </summary>
                  <small>{text(item.reason, t(language, 'risk.reason.none'))}</small>
                  <small>{text(item.preview, t(language, 'sessionDetail.noPreview'))}</small>
                  <pre className="inspect-pre small">{pretty(item)}</pre>
                </details>
              ))}
            </div>
          ) : (
            <p className="empty-copy">{t(language, 'sessionDetail.riskEventsEmpty')}</p>
          )}
        </details>
      </details>

      <details className="inspect-block" onToggle={(event) => event.currentTarget.open && void loadSection('summary')}>
        <summary>{t(language, 'sessionDetail.summaryBlock')}</summary>
        {sectionErrors.summary ? <p className="panel-error">{sectionErrors.summary}</p> : null}
        {sectionLoading.summary ? <LoadingCard className="session-section-loading" /> : null}
        {loadedSections.summary && !sectionLoading.summary ? (
          <>
            <div className="session-summary-meta">
              <span>{text(summary.summary_kind)}</span>
              <span>{text(summary.created_at_local ?? summary.created_at)}</span>
              <span>{text(summary.input_event_count)} {t(language, 'sessionDetail.inputEvents')}</span>
            </div>
            <pre className="inspect-pre">{text(summary.content, t(language, 'sessionDetail.noSummaryContent'))}</pre>
          </>
        ) : null}
      </details>

      <details className="inspect-block" onToggle={(event) => event.currentTarget.open && void loadSection('dreams')}>
        <summary>{t(language, 'sessionDetail.latestDreamNarrative')}</summary>
        {sectionErrors.dreams ? <p className="panel-error">{sectionErrors.dreams}</p> : null}
        {sectionLoading.dreams ? <LoadingCard className="session-section-loading" /> : null}
        {loadedSections.dreams && !sectionLoading.dreams ? (
          <>
            <div className="session-priority-grid">
              <article className="session-priority-card">
                <p className="eyebrow">{t(language, 'dreamArtifacts.compact')}</p>
                <p className="session-priority-copy session-priority-copy-strong">{text(latestDreamNarrative.compact, t(language, 'dreamArtifacts.noNarrative'))}</p>
              </article>
              <article className="session-priority-card">
                <p className="eyebrow">{t(language, 'dreamArtifacts.summary')}</p>
                <p className="session-priority-copy">{text(latestDreamNarrative.summary, t(language, 'dreamArtifacts.noNarrative'))}</p>
              </article>
            </div>
            {latestDream ? (
              <div className="session-dream-quickpeek-grid">
                {showSemantic ? (
                  <>
                    <QuickPeekList
                      formatter={entityDisplayName}
                      items={sessionSemanticEntities}
                      language={language}
                      title={t(language, 'dreamArtifacts.inspectEntities')}
                    />
                    <QuickPeekList
                      formatter={(item) => relationDisplayName(item, language)}
                      items={sessionSemanticRelations}
                      language={language}
                      title={t(language, 'dreamArtifacts.inspectRelations')}
                    />
                  </>
                ) : null}
                {showDeterministic ? (
                  <>
                    <QuickPeekList
                      formatter={entityDisplayName}
                      items={sessionDeterministicEntities}
                      language={language}
                      title={`${t(language, 'dreamArtifacts.deterministic')} · ${t(language, 'dreamArtifacts.inspectEntities')}`}
                    />
                    <QuickPeekList
                      formatter={(item) => relationDisplayName(item, language)}
                      items={sessionDeterministicRelations}
                      language={language}
                      title={`${t(language, 'dreamArtifacts.deterministic')} · ${t(language, 'dreamArtifacts.inspectRelations')}`}
                    />
                  </>
                ) : null}
              </div>
            ) : null}
            <details className="nested-inspect">
              <summary>{t(language, 'dreamArtifacts.fullDream')}</summary>
              <pre className="inspect-pre">{text(latestDreamNarrative.full, t(language, 'dreamArtifacts.noNarrative'))}</pre>
            </details>
          </>
        ) : null}
      </details>

      <details className="inspect-block" onToggle={(event) => event.currentTarget.open && void loadSection('dreams')}>
        <summary>{t(language, 'sessionDetail.dreamRuns')}</summary>
        {sectionErrors.dreams ? <p className="panel-error">{sectionErrors.dreams}</p> : null}
        {sectionLoading.dreams ? <LoadingCard className="session-section-loading" /> : null}
        {loadedSections.dreams && !sectionLoading.dreams ? (
          <div className="dream-detail-list">
            {dreams.length ? dreams.slice(0, 10).map((dream, index) => {
              const item = record(dream);
              const deterministicDreamEntities = records(item.v2_deterministic_entities);
              const deterministicDreamRelations = records(item.v2_deterministic_relations);
              const semanticDreamEntities = records(item.v2_semantic_entities);
              const semanticDreamRelations = records(item.v2_semantic_relations);
              const pending = dreamPending(item);
              const decisions = records(item.v2_reconciliation_decisions);
              const reviewItems = records(item.v2_review_items);
              const eventRange = `${text(item.input_event_seq_from, '?')}-${text(item.input_event_seq_to, '?')}`;
              return (
                <button
                  className="session-dream-run-card"
                  data-selected={index === 0 ? 'true' : 'false'}
                  key={text(item.dream_run_id, String(index))}
                  onClick={() => onOpenDream?.(dream)}
                  type="button"
                >
                  <div className="session-dream-run-head">
                    <span className="dream-badge">{text(item.status)}</span>
                    <strong>{text(item.episode_title, text(item.dream_run_id))}</strong>
                  </div>
                  <p className="dream-run-summary dream-run-summary-strong">{latestDreamSummary(item, language)}</p>
                  <p className="dream-run-summary">{text(item.episode_meta_short, t(language, 'sessionDetail.noDreamMeta'))}</p>
                  <div className="session-meta-grid compact">
                    <span><strong>{t(language, 'common.runner')}</strong>{text(item.runner)} {text(item.runner_model, '')}</span>
                    <span><strong>{t(language, 'sessionDetail.pipeline')}</strong>{text(item.pipeline_version)} / {text(item.pipeline_status)}</span>
                    <span><strong>{t(language, 'sessionDetail.events')}</strong>{eventRange}</span>
                    <span><strong>{t(language, 'sessions.table.dreamTokens')}</strong>{formatMetric(item.total_tokens)}</span>
                    <span><strong>{t(language, 'sessionDetail.started')}</strong>{text(item.started_at_local ?? item.started_at)}</span>
                    <span><strong>{t(language, 'sessionDetail.finished')}</strong>{text(item.finished_at_local ?? item.finished_at)}</span>
                  </div>
                  <div className="session-dream-run-kpis">
                    {showDeterministic ? (
                      <span><strong>{t(language, 'dreamArtifacts.deterministic')}</strong>{metricLabel(deterministicDreamEntities.length, pending, language)} {t(language, 'common.entities')} · {metricLabel(deterministicDreamRelations.length, pending, language)} {t(language, 'common.relations')}</span>
                    ) : null}
                    {showSemantic ? (
                      <span><strong>{t(language, 'dreamArtifacts.semantic')}</strong>{metricLabel(semanticDreamEntities.length, pending, language)} {t(language, 'common.entities')} · {metricLabel(semanticDreamRelations.length, pending, language)} {t(language, 'common.relations')}</span>
                    ) : null}
                    <span><strong>{t(language, 'sessionDetail.reviews')}</strong>{reviewItems.length} {t(language, 'sessionDetail.open')} · {decisions.length} {t(language, 'sessionDetail.decisions')}</span>
                  </div>
                </button>
              );
            }) : <p className="empty-copy">{t(language, 'sessionDetail.noDreamRuns')}</p>}
          </div>
        ) : null}
      </details>

      <details className="inspect-block">
        <summary>{t(language, 'sessionDetail.paths')}</summary>
        <dl className="inspect-kv">
          <dt>{t(language, 'sessionDetail.sessionId')}</dt><dd>{text(session.session_id)}</dd>
          <dt>{t(language, 'sessionDetail.cwd')}</dt><dd>{text(session.cwd)}</dd>
          <dt>{t(language, 'sessionDetail.lastWorkdir')}</dt><dd>{text(session.last_workdir)}</dd>
          <dt>{t(language, 'sessionDetail.transcript')}</dt><dd>{text(session.transcript_path)}</dd>
          <dt>{t(language, 'sessionDetail.resume')}</dt><dd>{text(session.native_resume_command)}</dd>
          <dt>{t(language, 'sessionDetail.summaryPath')}</dt><dd>{text(summary.summary_path)}</dd>
        </dl>
        <div className="session-meta-grid compact">
          <span><strong>{t(language, 'sessions.table.sessionTokens')}</strong>{formatMetric(tokenTotals.total_tokens)}</span>
          <span><strong>{t(language, 'sessions.table.dreamTokens')}</strong>{formatMetric(dreamTokenTotals.total_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.sessionInput')}</strong>{formatMetric(tokenTotals.input_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.sessionCached')}</strong>{formatMetric(tokenTotals.cached_input_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.sessionOutput')}</strong>{formatMetric(tokenTotals.output_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.sessionReasoning')}</strong>{formatMetric(tokenTotals.reasoning_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.dreamPrompt')}</strong>{formatMetric(dreamTokenTotals.prompt_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.dreamCached')}</strong>{formatMetric(dreamTokenTotals.cached_prompt_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.dreamCompletion')}</strong>{formatMetric(dreamTokenTotals.completion_tokens)}</span>
          <span><strong>{t(language, 'sessionDetail.metric.dreamReasoning')}</strong>{formatMetric(dreamTokenTotals.reasoning_tokens)}</span>
        </div>
      </details>

      <details className="inspect-block" onToggle={(event) => event.currentTarget.open && void loadSection('messages')}>
        <summary>{t(language, 'sessionDetail.messages')}</summary>
        {sectionErrors.messages ? <p className="panel-error">{sectionErrors.messages}</p> : null}
        {sectionLoading.messages ? <LoadingCard className="session-section-loading" /> : null}
        {loadedSections.messages && !sectionLoading.messages ? (
          <div className="session-conversation-list">
            {!transcriptMessages.length && conversationData.partial ? (
              <p className="session-message-note">{t(language, 'sessionDetail.messagesPartialHint')}</p>
            ) : null}
            {conversation.length ? conversation.map((message) => (
              <article className={`session-message-card session-message-card-${message.role}`} key={message.id}>
                <div className="session-message-head">
                  <strong>{message.role === 'user' ? t(language, 'common.user') : t(language, 'common.assistant')}</strong>
                  <span>
                    {message.timestamp || '-'}
                    {message.mergedCount > 1 ? ` · ${message.mergedCount}x` : ''}
                  </span>
                </div>
                <p>{message.content}</p>
              </article>
            )) : <p className="empty-copy">{t(language, 'sessionDetail.noMessages')}</p>}
          </div>
        ) : null}
      </details>

      <details className="inspect-block" onToggle={(event) => event.currentTarget.open && void loadSection('events')}>
        <summary>{t(language, 'sessionDetail.timeline')}</summary>
        {sectionErrors.events ? <p className="panel-error">{sectionErrors.events}</p> : null}
        {sectionLoading.events ? <LoadingCard className="session-section-loading" /> : null}
        {loadedSections.events && !sectionLoading.events ? (
          <div className="timeline-list">
            {previewEvents.length ? previewEvents.map((event, index) => {
              const item = record(event);
              return (
                <details className="timeline-row" key={text(item.event_id ?? item.id ?? item.seq, String(index))}>
                  <summary>
                    <strong>#{text(item.seq ?? index)} {text(item.event_name ?? item.kind ?? item.event_type ?? item.type, 'event')}</strong>
                    <span>{text(item.recorded_at_local ?? item.created_at ?? item.timestamp)}</span>
                  </summary>
                  <small>{text(item.preview ?? item.summary ?? item.tool_response_text ?? item.tool_input_json ?? item.content, t(language, 'sessionDetail.noPreview'))}</small>
                  <pre className="inspect-pre small">{pretty(event)}</pre>
                </details>
              );
            }) : <p className="empty-copy">{t(language, 'sessionDetail.noTimeline')}</p>}
          </div>
        ) : null}
      </details>

      <details className="inspect-block">
        <summary>{t(language, 'sessionDetail.rawPayload')}</summary>
        <pre className="inspect-pre">{pretty(data)}</pre>
      </details>
    </section>
  );
}
