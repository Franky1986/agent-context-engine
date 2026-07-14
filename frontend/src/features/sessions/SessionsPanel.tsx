import { useEffect, useRef, useState } from 'react';
import { t } from '../../app/i18n';
import { getSessions } from '../../shared/api/monitor';
import type { SessionListItem, SessionListResponse } from '../../shared/api/types';
import type { MonitorLanguage } from '../../app/monitorUi';
import { LoadingBlock, LoadingLine } from '../../shared/components/PanelLoading';
import './sessions-panel.css';

export type SessionsPanelProps = {
  initialData?: SessionListResponse;
  selectedSessionId?: string;
  onSelectSession?: (sessionId: string) => void;
  query?: string;
  language?: MonitorLanguage;
  autoSelectFirst?: boolean;
  showHeading?: boolean;
};

const PAGE_SIZE = 25;

function label(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function formatNumber(value: unknown) {
  if (typeof value === 'number') return new Intl.NumberFormat().format(value);
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) {
    return new Intl.NumberFormat().format(Number(value));
  }
  return label(value);
}

function compact(value: unknown, fallback: string, limit = 180) {
  const textValue = label(value, fallback);
  return textValue.length > limit ? `${textValue.slice(0, limit - 3)}...` : textValue;
}

function sessionRunner(session: SessionListItem) {
  const raw = record(session);
  return label(raw.dream_runner_used ?? raw.preferred_dream_runner, '').trim().toLowerCase();
}

function sessionWorkdir(session: SessionListItem) {
  const raw = record(session);
  return label(raw.last_workdir ?? session.cwd, '').trim();
}

export function SessionsPanel({
  initialData,
  selectedSessionId,
  onSelectSession,
  query,
  language = 'en',
  autoSelectFirst = true,
  showHeading = true,
}: SessionsPanelProps) {
  const [data, setData] = useState<SessionListResponse | undefined>(initialData);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState<Date | undefined>(initialData ? new Date() : undefined);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(!initialData);
  const hasDataRef = useRef(Boolean(initialData));
  const lastLoadedKeyRef = useRef(initialData ? `${query ?? ''}:${0}` : '');
  const onSelectSessionRef = useRef(onSelectSession);
  const selectedSessionIdRef = useRef(selectedSessionId);

  useEffect(() => {
    onSelectSessionRef.current = onSelectSession;
  }, [onSelectSession]);

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);

  useEffect(() => {
    setOffset(0);
  }, [query]);

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    const requestKey = `${query ?? ''}:${offset}`;
    const load = () => {
      const backgroundRefresh = hasDataRef.current && lastLoadedKeyRef.current === requestKey;
      if (!backgroundRefresh) {
        setLoading(true);
        setData(undefined);
      }
      getSessions(PAGE_SIZE, { q: query, offset })
        .then((payload) => {
          if (cancelled) return;
          setData(payload);
          hasDataRef.current = true;
          lastLoadedKeyRef.current = requestKey;
          setUpdatedAt(new Date());
          setError('');
          setLoading(false);
          const firstSessionId = payload.sessions?.[0]?.session_id;
          if (autoSelectFirst && !selectedSessionIdRef.current && firstSessionId) onSelectSessionRef.current?.(firstSessionId);
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : String(err));
            setLoading(false);
          }
        });
    };
    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [initialData, query, offset, autoSelectFirst]);

  useEffect(() => {
    if (!initialData) return;
    const firstSessionId = initialData.sessions?.[0]?.session_id;
    if (autoSelectFirst && !selectedSessionId && firstSessionId) onSelectSessionRef.current?.(firstSessionId);
  }, [initialData, selectedSessionId, autoSelectFirst]);

  const sessions: SessionListItem[] = data?.sessions ?? [];
  const total = typeof data?.total === 'number' ? data.total : sessions.length;
  const pageStart = sessions.length ? offset + 1 : 0;
  const pageEnd = offset + sessions.length;
  const canGoBack = offset > 0;
  const canGoForward = pageEnd < total;

  return (
    <section aria-busy={loading} className="sessions-panel">
      {showHeading ? (
        <div className="panel-heading sessions-heading">
          <div>
            <p className="eyebrow">{t(language, 'app.section.sessions')}</p>
            <h2>{t(language, 'sessions.panel.title')}</h2>
          </div>
          <div className="sessions-heading-meta">
            <span>{label(total, '0')} {t(language, 'sessions.total')}</span>
            <small>{t(language, 'sessions.updated')} {updatedAt ? updatedAt.toLocaleTimeString() : '-'}</small>
          </div>
        </div>
      ) : null}
      <div className="sessions-toolbar">
        <span className="sessions-page-status">
          {loading
            ? `${t(language, 'common.loading')}...`
            : sessions.length
            ? t(language, 'sessions.showing', { start: pageStart, end: pageEnd })
            : t(language, 'sessions.noEntries')}
        </span>
        <div className="sessions-pagination">
          <button className="sessions-page-button" disabled={loading || !canGoBack} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))} type="button">
            {t(language, 'sessions.back')}
          </button>
          <button className="sessions-page-button" disabled={loading || !canGoForward} onClick={() => setOffset((value) => value + PAGE_SIZE)} type="button">
            {t(language, 'sessions.next')}
          </button>
        </div>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}
      <div className="session-table" role="table" aria-label="Sessions">
        <div className="session-table-head" role="row">
          <span>{t(language, 'sessions.table.name')}</span>
          <span>{t(language, 'sessions.table.status')}</span>
          <span>{t(language, 'sessions.table.started')}</span>
          <span>{t(language, 'sessions.table.lastUsed')}</span>
          <span>{t(language, 'sessions.table.dreams')}</span>
          <span>{t(language, 'sessions.table.sessionTokens')}</span>
          <span>{t(language, 'sessions.table.dreamTokens')}</span>
        </div>
        <div className="session-list">
          {loading ? (
            Array.from({ length: 4 }).map((_, index) => (
              <article className="session-row session-row-loading" key={index}>
                <div className="session-select">
                  <span className="session-name-cell">
                    <LoadingLine variant="title" />
                    <LoadingLine variant="long" />
                    <LoadingLine variant="long" />
                    <LoadingLine variant="default" />
                  </span>
                  <span className="session-status-cell">
                    <LoadingLine variant="badge" />
                    <LoadingLine variant="default" />
                  </span>
                  <span><LoadingBlock lines={['default', 'short']} /></span>
                  <span><LoadingBlock lines={['default', 'short']} /></span>
                  <span><LoadingBlock lines={['metric', 'short']} /></span>
                  <span><LoadingBlock lines={['metric', 'default']} /></span>
                  <span><LoadingBlock lines={['metric', 'default']} /></span>
                </div>
              </article>
            ))
          ) : sessions.length ? (
            sessions.map((session, index) => {
              const riskSummary = record(record(session).risk_summary);
              const originClient = label(session.client_type, '').trim().toLowerCase();
              const dreamRunner = sessionRunner(session);
              const workdir = sessionWorkdir(session);
              const showDreamRunnerBadge = Boolean(dreamRunner) && dreamRunner !== originClient;
              const openCount = Number(riskSummary.open_count ?? 0);
              const blockedCount = Number(riskSummary.blocked_count ?? 0);
              const pendingApprovalCount = Number(riskSummary.pending_approval_count ?? 0);
              const taintActive = Boolean(riskSummary.taint_active);
              const latestRiskReason = compact(riskSummary.latest_risk_reason, t(language, 'sessions.risk.none'), 140);
              return (
                <article className="session-row" data-selected={session.session_id === selectedSessionId ? 'true' : 'false'} key={session.session_id ?? index}>
                  <button
                    className="session-select"
                    data-selected={session.session_id === selectedSessionId ? 'true' : 'false'}
                    onClick={() => session.session_id ? onSelectSession?.(session.session_id) : undefined}
                    type="button"
                  >
                    <span className="session-name-cell">
                      <strong>{label(session.session_id, t(language, 'sessions.untitled'))}</strong>
                      {session.thread_name && session.thread_name !== session.session_id ? (
                        <small className="session-custom-name">{session.thread_name}</small>
                      ) : null}
                      <small className="session-meta-line">
                        <span>{label(session.project_id)}</span>
                        {originClient ? <span className="session-client-badge session-client-badge-origin">{originClient}</span> : null}
                        {showDreamRunnerBadge ? <span className="session-client-badge session-client-badge-dream">{t(language, 'sessions.preview.dreamRunner')}: {dreamRunner}</span> : null}
                      </small>
                      <small className="session-preview">
                        {t(language, 'sessions.preview.latestActivity')}: {compact(session.latest_activity_summary ?? session.summary_preview, t(language, 'sessions.preview.latestActivityFallback'))}
                      </small>
                      <small className="session-preview session-preview-dream session-preview-dream-strong">
                        {t(language, 'sessions.preview.dreamShort')}: {compact(session.dream_summary_preview, t(language, 'sessions.preview.dreamShortFallback'))}
                      </small>
                      <small className="session-preview session-preview-dream-meta">
                        {t(language, 'sessions.preview.dreamMeta')}: {compact(session.dream_meta_preview, t(language, 'sessions.preview.dreamMetaFallback'))}
                      </small>
                    </span>
                    <span className="session-status-cell">
                      <strong className={`status-pill status-${label(session.activity_status ?? session.status, 'unknown')}`}>
                        {label(session.activity_status ?? session.status)}
                      </strong>
                      <small>{t(language, 'sessions.summary')} {label(session.summary_status)} · {t(language, 'sessions.dream')} {label(session.dream_status)}</small>
                      <small className="session-risk-line">
                        {openCount > 0
                          ? `${t(language, 'sessions.risk.open')}: ${formatNumber(openCount)}`
                          : `${t(language, 'sessions.risk.open')}: 0`}
                        {' · '}
                        {t(language, 'sessions.risk.blocked')}: {formatNumber(blockedCount)}
                        {' · '}
                        {t(language, 'sessions.risk.pending')}: {formatNumber(pendingApprovalCount)}
                      </small>
                      <small className="session-risk-line">
                        {taintActive ? t(language, 'sessions.risk.taintActive') : t(language, 'sessions.risk.taintClear')}
                      </small>
                      {riskSummary.latest_risk_event_id ? (
                        <small className="session-preview session-preview-risk">
                          {t(language, 'sessions.risk.latest')}: {latestRiskReason}
                        </small>
                      ) : null}
                    </span>
                    <span>
                      <strong>{label(session.started_at_local ?? session.started_at)}</strong>
                      <small>{label(workdir || session.cwd)}</small>
                    </span>
                    <span>
                      <strong>{label(session.last_event_at_local ?? session.last_event_at)}</strong>
                      <small>{label(session.last_seen_label)}</small>
                    </span>
                    <span>
                      <strong>{formatNumber(session.dream_count)}</strong>
                      <small>{label(session.dream_runner_used ?? session.preferred_dream_runner)} {label(session.dream_runner_status, '')}</small>
                    </span>
                    <span>
                      <strong>{formatNumber(session.total_tokens)}</strong>
                      <small>{formatNumber(session.input_tokens)} in · {formatNumber(session.output_tokens)} out</small>
                    </span>
                    <span>
                      <strong>{formatNumber(session.dream_total_tokens)}</strong>
                      <small>{formatNumber(session.dream_count)} {t(language, 'sessions.table.dreams').toLowerCase()}</small>
                    </span>
                  </button>
                </article>
              );
            })
          ) : (
            <p className="empty-copy">{t(language, 'sessions.empty')}</p>
          )}
        </div>
      </div>
    </section>
  );
}
