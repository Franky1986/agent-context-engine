import { useEffect, useMemo, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getDreams, getMonitorStatus, getRisks, getSessions, reconcileRuntime } from '../../shared/api/monitor';
import type { DreamRun, MonitorStatus, RiskEventListItem, RiskListResponse, SessionListItem } from '../../shared/api/types';
import { LoadingCard } from '../../shared/components/PanelLoading';
import './overview-panel.css';

const OVERVIEW_RISK_POLL_MS = 5000;

export type OverviewPanelProps = {
  language?: MonitorLanguage;
  onOpenSession?: (sessionId: string) => void;
  onOpenDream?: (dream: DreamRun) => void;
  onOpenControl?: () => void;
  showHeading?: boolean;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function compact(value: unknown, limit: number, fallback: string) {
  const normalized = text(value, fallback);
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
}

function firstRisk(payload?: RiskListResponse) {
  const rows = payload?.risks ?? payload?.events ?? [];
  return rows[0];
}

export function OverviewPanel({
  language = 'en',
  onOpenSession,
  onOpenDream,
  onOpenControl,
  showHeading = true,
}: OverviewPanelProps) {
  const [status, setStatus] = useState<MonitorStatus | undefined>();
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [dreams, setDreams] = useState<DreamRun[]>([]);
  const [risks, setRisks] = useState<RiskListResponse | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [runtimeBusy, setRuntimeBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getMonitorStatus(), getSessions(6), getDreams(6), getRisks(12)])
      .then(([statusPayload, sessionsPayload, dreamsPayload, risksPayload]) => {
        if (cancelled) return;
        setStatus(statusPayload);
        setSessions(sessionsPayload.sessions ?? []);
        setDreams(dreamsPayload.dreams ?? dreamsPayload.runs ?? []);
        setRisks(risksPayload);
        setError('');
        setLoading(false);
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
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setInterval(() => {
      getRisks(12)
        .then((payload) => {
          if (!cancelled) {
            setRisks(payload);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    }, OVERVIEW_RISK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const latestSession = sessions[0];
  const latestDream = dreams[0];
  const runtimeStatus = status?.launchagent;
  const monitorProcess = status?.monitor_process;
  const hookQueue = status?.hook_queue;
  const hookWorker = hookQueue?.worker;
  const hookQueueReasons = Array.isArray(hookQueue?.degradation_reasons) ? hookQueue.degradation_reasons : [];
  const pendingApprovals = useMemo(
    () => (risks?.risks ?? risks?.events ?? []).filter((risk) => text(risk.approval_state, '') === 'required'),
    [risks],
  );
  const newestRisk: RiskEventListItem | undefined = firstRisk(risks);

  async function handleReconcileRuntime() {
    setRuntimeBusy(true);
    try {
      await reconcileRuntime();
      const refreshed = await getMonitorStatus();
      setStatus(refreshed);
      setError('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRuntimeBusy(false);
    }
  }

  if (loading && !status && !sessions.length && !dreams.length && !risks && !error) {
    return (
      <section className="overview-panel" aria-busy="true">
        {showHeading ? (
          <div className="panel-heading">
            <div>
              <h2>{t(language, 'overview.title')}</h2>
            </div>
            <span>{t(language, 'common.loading')}...</span>
          </div>
        ) : null}
        <div className="overview-grid">
          <LoadingCard className="overview-card overview-card-accent" />
          <LoadingCard className="overview-card" />
          <LoadingCard className="overview-card" />
        </div>
      </section>
    );
  }

  return (
    <section className="overview-panel">
      {showHeading ? (
        <div className="panel-heading">
          <div>
            <h2>{t(language, 'overview.title')}</h2>
          </div>
          <span>
            {loading ? `${t(language, 'common.loading')}...` : `${text(status?.sessions, '0')} ${t(language, 'app.section.sessions').toLowerCase()} · ${text(status?.pending_dreams, '0')} ${t(language, 'overview.pendingDreams')}`}
          </span>
        </div>
      ) : null}
      {error ? <p className="panel-error">{error}</p> : null}

      <div className="overview-grid">
        <article className="overview-card overview-card-accent" data-loading={loading ? 'true' : 'false'}>
          <p className="eyebrow">{t(language, 'overview.latestSession')}</p>
          <h3>{loading ? `${t(language, 'common.loading')}...` : text(latestSession?.thread_name ?? latestSession?.session_id, t(language, 'overview.noSession'))}</h3>
          <p>{loading ? `${t(language, 'common.loading')}...` : compact(latestSession?.latest_activity_summary ?? latestSession?.summary_preview, 180, t(language, 'overview.noRecentSummary'))}</p>
          <div className="overview-chip-row">
            <span>{loading ? t(language, 'common.loading') : text(latestSession?.activity_status, t(language, 'common.unknown'))}</span>
            <span>{loading ? t(language, 'common.loading') : text(latestSession?.dream_status, t(language, 'common.unknown'))}</span>
            <span>{loading ? t(language, 'common.loading') : `${t(language, 'sessions.table.sessionTokens')}: ${text(latestSession?.total_tokens, '0')}`}</span>
            <span>{loading ? t(language, 'common.loading') : `${t(language, 'sessions.table.dreamTokens')}: ${text(latestSession?.dream_total_tokens, '0')}`}</span>
            <span>{loading ? t(language, 'common.loading') : text(latestSession?.last_event_at_local ?? latestSession?.last_event_at, '-')}</span>
          </div>
          <button className="overview-action" disabled={loading || !latestSession?.session_id || !onOpenSession} onClick={() => latestSession?.session_id && onOpenSession?.(latestSession.session_id)} type="button">
            {t(language, 'overview.openSession')}
          </button>
        </article>

        <article className="overview-card" data-loading={loading ? 'true' : 'false'}>
          <p className="eyebrow">{t(language, 'overview.latestDream')}</p>
          <h3>{loading ? `${t(language, 'common.loading')}...` : text(latestDream?.status, t(language, 'overview.noDream'))}</h3>
          <p>{loading ? `${t(language, 'common.loading')}...` : compact(latestDream?.episode_short ?? latestDream?.episode_title ?? latestDream?.intent, 180, t(language, 'overview.noDreamSummary'))}</p>
          <div className="overview-chip-row">
            <span>{loading ? t(language, 'common.loading') : text(latestDream?.runner, '-')}</span>
            <span>{loading ? t(language, 'common.loading') : `${text(latestDream?.total_tokens, '0')} tokens`}</span>
            <span>{loading ? t(language, 'common.loading') : text(latestDream?.pipeline_status, '-')}</span>
          </div>
          <button className="overview-action" disabled={loading || !latestDream || !onOpenDream} onClick={() => latestDream && onOpenDream?.(latestDream)} type="button">
            {t(language, 'overview.openDream')}
          </button>
        </article>

        <article className="overview-card" data-loading={loading ? 'true' : 'false'}>
          <p className="eyebrow">{t(language, 'overview.runtime')}</p>
          <h3>{loading ? `${t(language, 'common.loading')}...` : runtimeStatus?.drift?.detected ? t(language, 'overview.runtimeDrift') : t(language, 'overview.runtimeAligned')}</h3>
          <p>
            {loading
              ? `${t(language, 'common.loading')}...`
              : `${text(monitorProcess?.argv?.[0], '-')} · ${text(runtimeStatus?.installed?.program, '-')}`}
          </p>
          <div className="overview-chip-row">
            <span>{loading ? t(language, 'common.loading') : `monitor pid ${text(monitorProcess?.pid, '-')}`}</span>
            <span>{loading ? t(language, 'common.loading') : `launchd ${runtimeStatus?.loaded ? t(language, 'common.active') : t(language, 'common.no')}`}</span>
            <span>{loading ? t(language, 'common.loading') : text(runtimeStatus?.installed?.managed_env?.AGENT_MEMORY_WORKER_RUNNER, '-')}</span>
          </div>
          {!loading && runtimeStatus?.drift?.reasons?.length ? (
            <p>{runtimeStatus.drift.reasons.join(' · ')}</p>
          ) : null}
          {!loading && runtimeStatus?.installed?.working_directory ? (
            <code className="integrations-command">{runtimeStatus.installed.working_directory}</code>
          ) : null}
          {!loading && runtimeStatus?.installed?.env_file ? (
            <code className="integrations-command">{runtimeStatus.installed.env_file}</code>
          ) : null}
          <button className="overview-action" disabled={loading || runtimeBusy} onClick={() => void handleReconcileRuntime()} type="button">
            {runtimeBusy ? t(language, 'overview.runtimeReconciling') : t(language, 'overview.runtimeReconcile')}
          </button>
          {!loading && monitorProcess?.restart_command ? (
            <code className="integrations-command">{monitorProcess.restart_command}</code>
          ) : null}
          {!loading && runtimeStatus?.recommended_command ? (
            <code className="integrations-command">{runtimeStatus.recommended_command}</code>
          ) : null}
          {!loading ? (
            <div className="overview-chip-row">
              <span>{`hook queue ${text(hookQueue?.queued_events, '0')}`}</span>
              <span>{`dead letters ${text(hookQueue?.failed_events, '0')}`}</span>
              <span>{hookWorker?.running ? 'hook worker active' : 'hook worker idle'}</span>
              <span>{hookWorker?.stale ? 'worker stale' : text(hookWorker?.heartbeat_at, '-')}</span>
            </div>
          ) : null}
          {!loading && hookQueue?.degraded ? (
            <p>{`hook queue degraded: ${hookQueueReasons.join(' · ') || 'see logs'}`}</p>
          ) : null}
          {!loading && hookQueue?.queue_log?.last_message ? (
            <code className="integrations-command">{text(hookQueue.queue_log.last_message, '')}</code>
          ) : null}
          {!loading && hookQueue?.bridge_log?.last_message ? (
            <code className="integrations-command">{text(hookQueue.bridge_log.last_message, '')}</code>
          ) : null}
        </article>

        <article className="overview-card" data-loading={loading ? 'true' : 'false'}>
          <p className="eyebrow">{t(language, 'overview.controlNeeds')}</p>
          <h3>{loading ? `${t(language, 'common.loading')}...` : `${pendingApprovals.length} ${t(language, pendingApprovals.length === 1 ? 'overview.pendingApprovalSingular' : 'overview.pendingApprovalPlural')}`}</h3>
          <p>{loading ? `${t(language, 'common.loading')}...` : compact(newestRisk?.reason ?? newestRisk?.preview, 180, t(language, 'overview.noRisk'))}</p>
          <div className="overview-chip-row">
            <span>{loading ? t(language, 'common.loading') : status?.firewall?.enabled ? t(language, 'overview.firewallEnabled') : t(language, 'overview.firewallDisabled')}</span>
            <span>{loading ? t(language, 'common.loading') : text(newestRisk?.tool_name, '-')}</span>
            <span>{loading ? t(language, 'common.loading') : text(newestRisk?.created_at, '-')}</span>
          </div>
          <button className="overview-action" disabled={loading || !onOpenControl} onClick={() => onOpenControl?.()} type="button">
            {t(language, 'overview.openControl')}
          </button>
        </article>
      </div>
    </section>
  );
}
