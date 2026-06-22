import { useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getRisks } from '../../shared/api/monitor';
import type { RiskEventListItem, RiskListResponse } from '../../shared/api/types';
import './risk-panel.css';

const RISK_POLL_MS = 5000;

export type RiskPanelProps = {
  initialData?: RiskListResponse;
  language?: MonitorLanguage;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

export function RiskPanel({ initialData, language = 'en' }: RiskPanelProps) {
  const [data, setData] = useState<RiskListResponse | undefined>(initialData);
  const [error, setError] = useState('');

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    const load = () => {
      getRisks(8)
        .then((payload) => {
          if (!cancelled) {
            setData(payload);
            setError('');
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    };
    load();
    const timer = window.setInterval(load, RISK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [initialData]);

  const risks: RiskEventListItem[] = data?.risks ?? data?.events ?? [];

  return (
    <section className="risk-panel">
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'risk.panel.eyebrow')}</p>
        <h2>{t(language, 'risk.panel.title')}</h2>
        <span>{text(data?.total ?? risks.length, '0')} {t(language, 'risk.panel.total')}</span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}
      <div className="risk-list">
        {risks.length ? (
          risks.map((risk, index) => (
            <article className="risk-row" data-level={risk.risk_level ?? 'unknown'} key={risk.risk_event_id ?? index}>
              <strong>{text(risk.status, t(language, 'risk.status.unknown'))}</strong>
              <span>{text(risk.reason ?? risk.preview, t(language, 'risk.reason.none'))}</span>
              <small>{text(risk.risk_level)} · {text(risk.tool_name)} · {text(risk.created_at)}</small>
            </article>
          ))
        ) : (
          <p className="empty-copy">{t(language, 'risk.panel.empty')}</p>
        )}
      </div>
    </section>
  );
}
