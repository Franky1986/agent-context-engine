import { useEffect, useMemo, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getDiagnostics } from '../../shared/api/monitor';
import type { DiagnosticsStatus } from '../../shared/api/types';
import { LoadingBlock } from '../../shared/components/PanelLoading';
import './diagnostics-panel.css';

export type DiagnosticsPanelProps = {
  initialData?: DiagnosticsStatus;
  language?: MonitorLanguage;
};

export function DiagnosticsPanel({ initialData, language = 'en' }: DiagnosticsPanelProps) {
  const [data, setData] = useState<DiagnosticsStatus | undefined>(initialData);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(!initialData);

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    setLoading(true);
    getDiagnostics()
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
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
  }, [initialData]);

  const lines = data?.lines ?? [];
  const runtimeLines = useMemo(() => lines.filter((line) => line.includes('runtime ') || line.includes('neo4j')), [lines]);

  if (loading && !data && !error) {
    return (
      <section className="diagnostics-panel" aria-busy="true">
        <div className="panel-heading">
          <p className="eyebrow">{t(language, 'diagnostics.heading')}</p>
          <h2>{t(language, 'common.loading')}...</h2>
          <span>{t(language, 'common.loading')}...</span>
        </div>
        <div className="diagnostics-columns diagnostics-columns-loading">
          <div>
            <h3>{t(language, 'diagnostics.runtimeConfig')}</h3>
            {Array.from({ length: 4 }).map((_, index) => <LoadingBlock key={index} lines={['title', 'long', 'default']} />)}
          </div>
          <div>
            <h3>{t(language, 'diagnostics.doctorOutput')}</h3>
            {Array.from({ length: 5 }).map((_, index) => <LoadingBlock key={index} lines={['default', 'long']} />)}
          </div>
        </div>
      </section>
    );
  }

  return (
    <section aria-busy={loading} className="diagnostics-panel">
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'diagnostics.heading')}</p>
        <h2>{data?.ok ? t(language, 'diagnostics.ok') : t(language, 'diagnostics.attention')}</h2>
        <span>{lines.length} {t(language, 'diagnostics.checks')} · exit {data?.exit_code ?? '-'}</span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}
      <div className="diagnostics-columns">
        <div>
          <h3>{t(language, 'diagnostics.runtimeConfig')}</h3>
          {runtimeLines.length ? runtimeLines.map((line, index) => <code key={index}>{line}</code>) : <p className="empty-copy">{t(language, 'diagnostics.noRuntimeLines')}</p>}
        </div>
        <div>
          <h3>{t(language, 'diagnostics.doctorOutput')}</h3>
          {lines.slice(0, 8).map((line, index) => <code data-state={line.split(' ', 1)[0]} key={index}>{line}</code>)}
        </div>
      </div>
    </section>
  );
}
