import { useEffect, useRef, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getDreams } from '../../shared/api/monitor';
import type { DreamRun, DreamRunListResponse } from '../../shared/api/types';
import { LoadingBlock } from '../../shared/components/PanelLoading';
import './dreams-panel.css';

export type DreamsPanelProps = {
  initialData?: DreamRunListResponse;
  selectedDreamId?: string;
  onSelectDream?: (dream: DreamRun) => void;
  language?: MonitorLanguage;
  autoSelectFirst?: boolean;
  sessionId?: string;
  showHeading?: boolean;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function formatNumber(value: unknown) {
  if (typeof value === 'number') return new Intl.NumberFormat().format(value);
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) {
    return new Intl.NumberFormat().format(Number(value));
  }
  return text(value);
}

function compactText(value: unknown, limit = 160, fallback: string) {
  const normalized = text(value, fallback);
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
}

const TECHNICAL_INTENTS = new Set([
  'no_dream_memory',
  'no_dream_content',
  'no_semantic_memory',
  'no_semantic_content',
  'memory_absence',
  'memory_absent',
]);

function prettifySlug(value: string) {
  return value
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function sameMeaningfulText(left: string, right: string) {
  const normalize = (value: string) => value.trim().toLowerCase().replace(/[\s_-]+/g, ' ');
  return normalize(left) !== '' && normalize(left) === normalize(right);
}

function dreamSignalLabel(dream: DreamRun, language: MonitorLanguage) {
  const intent = text(dream.intent, '').trim().toLowerCase();
  if (!intent) return dreamPending(dream) ? t(language, 'dreams.signal.pending') : t(language, 'dreams.noSignal');
  const labels: Record<string, string> = {
    no_dream_memory: t(language, 'dreams.signal.noDreamMemory'),
    no_dream_content: t(language, 'dreams.signal.noDreamContent'),
    no_semantic_memory: t(language, 'dreams.signal.noSemanticMemory'),
    no_semantic_content: t(language, 'dreams.signal.noSemanticContent'),
    memory_absence: t(language, 'dreams.signal.memoryAbsence'),
    memory_absent: t(language, 'dreams.signal.memoryAbsence'),
  };
  return labels[intent] ?? prettifySlug(intent);
}

function dreamSummaryText(dream: DreamRun, language: MonitorLanguage) {
  const intent = text(dream.intent, '').trim();
  const title = text(dream.episode_title, '').trim();
  const short = text(dream.episode_short, '').trim();
  if (short && (!intent || !sameMeaningfulText(short, intent))) {
    return compactText(short, 160, t(language, 'dreams.compact.noSummary'));
  }
  if (title && (!intent || !sameMeaningfulText(title, intent))) {
    return compactText(title, 160, t(language, 'dreams.compact.noSummary'));
  }
  if (intent) {
    return TECHNICAL_INTENTS.has(intent.toLowerCase()) ? dreamSignalLabel(dream, language) : compactText(prettifySlug(intent), 160, t(language, 'dreams.compact.noSummary'));
  }
  if (dreamPending(dream)) return t(language, 'dreams.summary.pending');
  return t(language, 'dreams.compact.noSummary');
}

function dreamSummarySubline(dream: DreamRun, language: MonitorLanguage) {
  const intent = text(dream.intent, '').trim();
  const title = text(dream.episode_title, '').trim();
  const short = text(dream.episode_short, '').trim();
  if (title && !sameMeaningfulText(title, short) && (!intent || !sameMeaningfulText(title, intent))) {
    return compactText(title, 160, '');
  }
  if (intent && !TECHNICAL_INTENTS.has(intent.toLowerCase())) {
    return compactText(prettifySlug(intent), 160, '');
  }
  if (dreamPending(dream)) return t(language, 'dreams.summary.pendingDetail');
  return '';
}

function dreamPending(dream: DreamRun) {
  const status = text(dream.status, '').toLowerCase();
  const pipelineStatus = text(dream.pipeline_status, '').toLowerCase();
  if (['succeeded', 'failed', 'completed', 'persisted', 'dry_run'].includes(status)) return false;
  if (['succeeded', 'failed', 'completed', 'persisted', 'dry_run'].includes(pipelineStatus)) return false;
  return ['queued', 'running', 'dreaming', 'pending'].includes(status)
    || ['queued', 'running', 'dreaming', 'pending'].includes(pipelineStatus);
}

export function DreamsPanel({
  initialData,
  selectedDreamId,
  onSelectDream,
  language = 'en',
  autoSelectFirst = false,
  sessionId,
  showHeading = true,
}: DreamsPanelProps) {
  const [data, setData] = useState<DreamRunListResponse | undefined>(initialData);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState<Date | undefined>(initialData ? new Date() : undefined);
  const [loading, setLoading] = useState(!initialData);
  const hasDataRef = useRef(Boolean(initialData));
  const lastLoadedKeyRef = useRef(initialData ? `${sessionId ?? ''}` : '');
  const onSelectDreamRef = useRef(onSelectDream);
  const selectedDreamIdRef = useRef(selectedDreamId);

  useEffect(() => {
    onSelectDreamRef.current = onSelectDream;
  }, [onSelectDream]);

  useEffect(() => {
    selectedDreamIdRef.current = selectedDreamId;
  }, [selectedDreamId]);

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    const requestKey = `${sessionId ?? ''}`;
    const load = () => {
      const backgroundRefresh = hasDataRef.current && lastLoadedKeyRef.current === requestKey;
      if (!backgroundRefresh) {
        setLoading(true);
        setData(undefined);
      }
      getDreams(25, { sessionId })
        .then((payload) => {
          if (cancelled) return;
          setData(payload);
          hasDataRef.current = true;
          lastLoadedKeyRef.current = requestKey;
          setUpdatedAt(new Date());
          setError('');
          setLoading(false);
          const dreams = payload.dreams ?? payload.runs ?? [];
          const selectedId = selectedDreamIdRef.current;
          const selected = selectedId ? dreams.find((dream) => dream.dream_run_id === selectedId) : undefined;
          const first = dreams.find((dream) => {
            const status = `${dream.status ?? ''} ${dream.pipeline_status ?? ''}`.toLowerCase();
            return status.includes('succeeded') || status.includes('completed') || status.includes('persisted');
          }) ?? dreams[0];
          if (selected) {
            onSelectDreamRef.current?.(selected);
          } else if (autoSelectFirst && !selectedId && first) {
            onSelectDreamRef.current?.(first);
          }
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
  }, [initialData, autoSelectFirst, sessionId]);

  const dreams: DreamRun[] = data?.dreams ?? data?.runs ?? [];

  return (
    <section aria-busy={loading} className="dreams-panel">
      {showHeading ? (
        <div className="panel-heading dreams-heading">
          <div>
            <p className="eyebrow">{t(language, 'app.section.dreams')}</p>
            <h2>{t(language, 'dreams.panel.title')}</h2>
            {sessionId ? <small>{t(language, 'dreams.filteredToSession')} {sessionId}</small> : null}
          </div>
          <div className="dreams-heading-meta">
            <span>{text(data?.total ?? dreams.length, '0')} {t(language, 'sessions.total')}</span>
            <small>{t(language, 'sessions.updated')} {updatedAt ? updatedAt.toLocaleTimeString() : '-'}</small>
          </div>
        </div>
      ) : null}
      {error ? <p className="panel-error">{error}</p> : null}
      <div className="dream-table" role="table" aria-label="Dream runs">
        <div className="dream-table-head" role="row">
          <span>{t(language, 'dreams.table.status')}</span>
          <span>{t(language, 'dreams.table.session')}</span>
          <span>{t(language, 'dreams.table.started')}</span>
          <span>{t(language, 'dreams.table.runner')}</span>
          <span>{t(language, 'dreams.table.summary')}</span>
          <span>{t(language, 'dreams.table.signal')}</span>
        </div>
      <div className="dream-list">
          {loading ? (
            Array.from({ length: 4 }).map((_, index) => (
              <article className="dream-row dream-row-loading" key={index}>
                <div className="dream-select">
                  <span><LoadingBlock lines={['badge', 'default']} /></span>
                  <span><LoadingBlock lines={['title', 'default']} /></span>
                  <span><LoadingBlock lines={['default', 'short']} /></span>
                  <span><LoadingBlock lines={['default', 'default']} /></span>
                  <span><LoadingBlock lines={['long', 'default']} /></span>
                  <span><LoadingBlock lines={['long', 'default']} /></span>
                </div>
              </article>
            ))
        ) : dreams.length ? (
          dreams.map((dream, index) => (
            <article className="dream-row" data-selected={dream.dream_run_id === selectedDreamId ? 'true' : 'false'} data-status={dream.status ?? 'unknown'} key={dream.dream_run_id ?? dream.run_id ?? index}>
              <button
                className="dream-select"
                data-selected={dream.dream_run_id === selectedDreamId ? 'true' : 'false'}
                onClick={() => onSelectDream?.(dream)}
                type="button"
              >
                <span>
                  <strong>{text(dream.status, 'unknown')}</strong>
                  <small>{text(dream.pipeline_status)} · {text(dream.created_by)}</small>
                </span>
                <span>
                  <strong>{text(dream.session_id, t(language, 'dreams.noSession'))}</strong>
                  <small>{text(dream.project_id)} · {text(dream.cwd)}</small>
                </span>
                <span>
                  <strong>{text(dream.started_at_local ?? dream.started_at)}</strong>
                  <small>{t(language, 'dreams.finished')} {text(dream.finished_at_local ?? dream.finished_at)}</small>
                </span>
                <span>
                  <strong>{text(dream.runner)} {text(dream.runner_model, '')}</strong>
                  <small>{formatNumber(dream.total_tokens)} tokens · {formatNumber(dream.input_event_count)} {t(language, 'sessionDetail.events')}</small>
                </span>
                <span>
                  <strong>{dreamSummaryText(dream, language)}</strong>
                  {dreamSummarySubline(dream, language) ? <small>{dreamSummarySubline(dream, language)}</small> : null}
                  <small>{compactText(dream.episode_meta_short, 180, t(language, 'sessions.preview.dreamMetaFallback'))}</small>
                </span>
                <span>
                  <strong>{dreamSignalLabel(dream, language)}</strong>
                  <small>{text(dream.error_message ?? dream.error, text(dream.pipeline_status, t(language, 'dreams.noError')))}</small>
                  <small>
                    {dreamPending(dream) && (dream.v2_deterministic_entities?.length ?? 0) === 0
                      ? t(language, 'dreams.pendingDet')
                      : `${formatNumber(dream.v2_deterministic_entities?.length ?? 0)} det`}
                    {' · '}
                    {dreamPending(dream) && (dream.v2_semantic_entities?.length ?? 0) === 0
                      ? t(language, 'dreams.pendingSem')
                      : `${formatNumber(dream.v2_semantic_entities?.length ?? 0)} sem`}
                    {' '}
                    {t(language, 'dreams.entities')}
                  </small>
                </span>
              </button>
            </article>
          ))
        ) : (
          <p className="empty-copy">{t(language, 'dreams.empty')}</p>
          )}
      </div>
      </div>
    </section>
  );
}
